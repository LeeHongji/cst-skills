"""Execute one prepared Function model inside an owned Guardian worker.

The native backend never accepts caller-provided VBA. Emission is rebuilt from
the approved IR. Core readback is required; unavailable detailed getters remain
explicitly deferred and never become successful native checks.
"""
from __future__ import annotations

from dataclasses import asdict
import math
from pathlib import Path
import time

from cst_lab.atomic import atomic_json
from cst_lab.function_contract import digest
from .solver_evidence import LogCheckpoint, evaluate_solver_evidence
from cst_lab.function_readback import leaves, verify_readback


class ExecutionBlocked(ValueError):
    pass


def execute_prepared(prepared, directory, backend, authorize, progress):
    """Ordered execution core. Only the native adapter is used by the CLI.

    Dependency injection is for isolated tests, never a request field. The
    caller owns timeout/process containment and a persistent job execution lease.
    Even failures produce a receipt; evidence publication belongs to the parent.
    """
    from cst_cad import emit_vba
    from .preconditions import check_history_code
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    document, setup = prepared.document, prepared.execution['setup']
    receipt = dict(schema_version=1, status='running', phase='authorizing',
                   solver_started=False, solver_returned=False, approval_validated=False,
                   execution=prepared.execution, approval_sha256=prepared.approval_sha256,
                   timings={}, history=[])
    started = time.monotonic()

    def record(phase, **details):
        receipt.update(phase=phase, **details)
        receipt['duration_s'] = time.monotonic() - started
        atomic_json(directory/'execution-receipt.json', receipt)
        progress(phase, details)

    record('authorizing')
    project = None
    incremental=getattr(prepared,'incremental',None)
    try:
        authorize()
        # The guarded engineering regression harness may exercise this core
        # without a CAD sign-off. It must never become an audited publication.
        # The production facade still requires signed approval in preflight.
        receipt['approval_validated'] = prepared.approval_sha256 is not None
        receipt['execution_authorized'] = True
        blocks = emit_vba.build_blocks(document)
        if digest([dict(title=b.title, code=b.code) for b in blocks]) != prepared.execution['emitted_sha256']:
            raise ValueError('emitter changed after preflight')
        for block in blocks:
            check_history_code(block.code)
        atomic_json(directory/'model-ir.json', document)
        atomic_json(directory/'effective-setup.json', setup)
        atomic_json(directory/'drc.json', prepared.drc_report)
        emit_vba.write_blocks(document, directory/'vba')
        receipt['model_update']='parent-parameter-update' if incremental else 'full-rebuild'
        if incremental:
            from cst_lab.function_incremental import copy_parent
            archive=directory/'incremental';archive.mkdir()
            atomic_json(archive/'source.json',incremental)
            record('copying-parent-model')
            copied=copy_parent(incremental,directory/'working/model.cst')
            project=backend.open_project(copied)
            receipt['runtime']=backend.runtime(project)
            if receipt['runtime']['cst_version']!=incremental['cst_version']:
                raise ExecutionBlocked('parent CST version differs from current native runtime')
            parent_observation=backend.observe(project,archive)
            parent_settings=backend.read_setup(project,incremental['setup'],archive)
            atomic_json(archive/'observation.json',parent_observation)
            atomic_json(archive/'settings.json',parent_settings)
            try:
                parent_verification=verify_readback(incremental['document'],parent_observation,incremental['setup'],parent_settings)
            except ValueError as exc:
                atomic_json(archive/'verification.json',dict(status='mismatch',error=str(exc)))
                raise ExecutionBlocked('native parent model differs before incremental update: '+str(exc)) from exc
            atomic_json(archive/'verification.json',parent_verification)
            if parent_verification['status']!='verified':raise ExecutionBlocked('native parent model differs before incremental update')
            authorize()
            record('updating-parent-parameters')
            changes=backend.update_parameters(project,incremental['updates'])
            atomic_json(archive/'parameter-update.json',changes)
            receipt['incremental_source_sha256']=digest(incremental)
        else:
            record('creating-project')
            project = backend.new_project(directory/'working/model.cst')
        receipt['runtime'] = backend.runtime(project)
        from cst_lab.function_setup import cache_identity
        receipt['cache_identity'], receipt['cache_key'] = cache_identity(document, setup, receipt['runtime'])
        record('building')
        for block in ([] if incremental else blocks):
            messages = backend.history(project, block)
            receipt['history'].append(dict(title=block.title, messages=messages))
            record('building', active_block=block.title)
            if any(str(m.get('type', '')).casefold() in ('error', 'fatal') for m in messages):
                raise RuntimeError(f'CST reported an error after {block.title}')
        backend.save(project)
        record('reading-model-and-settings')
        observation = backend.observe(project, directory)
        actual = backend.read_setup(project, setup, directory)
        atomic_json(directory/'observation.json', observation)
        atomic_json(directory/'native-settings.json', actual)
        verification = verify_readback(document, observation, setup, actual)
        atomic_json(directory/'readback-verification.json', verification)
        if verification['status'] != 'verified':
            raise ExecutionBlocked('Core native readback incomplete or mismatched: '+', '.join(verification['unresolved']))
        # Approval/model sources can change during the relatively slow build.
        authorize()
        backend.save(project)
        project_path = directory/'working/model.cst'
        if not project_path.is_file() or not project_path.stat().st_size:
            raise RuntimeError('CST save did not produce a nonempty working project')
        log_paths = backend.log_paths(project_path)
        checkpoints = {name: LogCheckpoint.capture(path) for name, path in log_paths.items()}
        atomic_json(directory/'log-checkpoints.json', {k: asdict(v) for k,v in checkpoints.items()})
        old_messages = backend.messages(project)
        record('solving', solver_started=True)
        solve_start = time.monotonic()
        try:
            backend.solve(project)
            receipt['solver_returned'] = True
        finally:
            receipt['timings']['solve_s'] = time.monotonic() - solve_start
            fresh = {k: checkpoint.read_fresh(log_paths[k]) for k,checkpoint in checkpoints.items()}
            all_messages = backend.messages(project)
            # A reset message list is recorded in full; log freshness remains independent.
            messages = all_messages[len(old_messages):] if all_messages[:len(old_messages)] == old_messages else all_messages
            atomic_json(directory/'fresh-solver-logs.json', fresh)
            atomic_json(directory/'solver-messages.json', messages)
            receipt['convergence'] = evaluate_solver_evidence(setup,
                log_text=fresh['model']['text'] or fresh['output']['text'],
                messages=messages, solver_returned=receipt['solver_returned'])
            record('solver-returned')
        backend.save(project)
        record('exporting')
        export = Path(backend.export(project, directory/'exports/s-parameters', setup))
        expected = directory/f'exports/s-parameters.s{len(document["ports"])}p'
        if export.resolve() != expected.resolve() or not export.is_file():
            raise RuntimeError('CST export is absent or has the wrong port-count suffix')
        from cst_lab.contracts.touchstone import read_touchstone
        data = read_touchstone(export)
        if data.ports != len(document['ports']) or len(data) < 2:
            raise RuntimeError('exported curves have incomplete port/sample coverage')
        for actual_frequency, key in ((data.frequencies_hz[0]/1e9, 'min'), (data.frequencies_hz[-1]/1e9, 'max')):
            if not math.isclose(actual_frequency, setup['frequency'][key], rel_tol=1e-6, abs_tol=1e-9):
                raise RuntimeError('exported frequency range differs from effective setup')
        receipt['export'] = dict(path=export.relative_to(directory).as_posix(),
                                 ports=data.ports, samples=len(data))
        from cst_lab.function_evidence import sha256
        receipt['export']['sha256']=sha256(export)
        if receipt['convergence']['converged'] is not True:
            raise RuntimeError('solver convergence is not proven by this invocation')
        authorize()
        record('execution-finished', status='executed')
    except Exception as exc:
        record('blocked' if isinstance(exc, ExecutionBlocked) else 'failed',
               status='blocked' if isinstance(exc, ExecutionBlocked) else 'failed',
               error=f'{type(exc).__name__}: {exc}')
    finally:
        if project is not None:
            try:
                backend.close(project)
                receipt['project_closed'] = True
            except Exception as exc:
                receipt.update(status='failed', error=f'project close failed: {exc}', project_closed=False)
        receipt['duration_s'] = time.monotonic() - started
        if incremental:
            from cst_lab.project_package import model_snapshot
            try:
                receipt['incremental_parent_unchanged']=digest(model_snapshot(Path(incremental['source'])))==incremental['model_snapshot_sha256']
            except (OSError,ValueError):receipt['incremental_parent_unchanged']=False
            if not receipt['incremental_parent_unchanged']:
                receipt.update(status='failed',error='incremental parent evidence changed during execution')
        atomic_json(directory/'execution-receipt.json', receipt)
    return receipt


class NativeBackend:
    """CST calls, isolated from the MCP server and from injected test doubles."""
    def __init__(self, session, executor_sha256):
        self.session, self.executor_sha256 = session, executor_sha256
        self._owned_projects = {}

    def new_project(self, path):
        if not self.session.info.launched or self.session.info.open_projects:
            raise ValueError('Function execution requires a newly owned empty CST session')
        path.parent.mkdir(parents=True, exist_ok=False)
        project=self.session.new_project(path)
        self._owned_projects[id(project)]=Path(path).resolve()
        return project

    def open_project(self, path):
        if not self.session.info.launched or self.session.info.open_projects:
            raise ValueError('reopen verification requires a newly owned empty CST session')
        project=self.session.open_project(path)
        self._owned_projects[id(project)]=Path(path).resolve()
        return project

    def runtime(self, project):
        from cst_lab.function_evidence import sha256
        binary=Path(self.session.info.install_root)/'AMD64/CST DESIGN ENVIRONMENT_AMD64.exe'
        return dict(cst_version=str(project.model3d.GetApplicationVersion()), executor_sha256=self.executor_sha256,
                    cst_binary_sha256=sha256(binary))

    def messages(self, project):
        return [dict(m) if isinstance(m, dict) else dict(text=str(m)) for m in project.get_messages()]

    def history(self, project, block):
        from .preconditions import add_to_history
        before = self.messages(project)
        add_to_history(project.model3d, block.caption, block.code)
        after = self.messages(project)
        return after[len(before):] if after[:len(before)] == before else after

    def save(self, project):
        path=self._owned_projects.get(id(project))
        if path is None:
            raise ValueError('Cannot save a project not opened by this owned backend')
        current=Path(project.filename()).resolve()
        if current!=path:
            raise ValueError('Native project filename changed outside its owned working copy')
        # CST's documented default allow_overwrite=False can refuse later saves.
        # Permit replacement only of the exact isolated copy tracked above.
        project.save(str(path),allow_overwrite=True)

    def update_parameters(self,project,updates):
        from .preconditions import set_parameter,parameter_number
        model=project.model3d
        before=self.messages(project)
        # Only the isolated copied model is touched. Clear any result metadata
        # before edits; never place StoreParameter/Rebuild in a History block.
        model._execute_vba_code('Sub Main\nDeleteResults\nEnd Sub')
        records=[]
        for name,(old,new) in updates.items():
            if not math.isclose(parameter_number(model,name),old,rel_tol=1e-9,abs_tol=1e-12):
                raise ValueError('native parent parameter precondition differs: '+name)
            records.append(set_parameter(model,name,new,allowed_range=(new,new),rebuild=False))
        model.RebuildOnParametricChange(False,False)
        after=self.messages(project)
        messages=after[len(before):] if after[:len(before)]==before else after
        if any(str(m.get('type','')).casefold() in ('error','fatal') for m in messages):
            raise RuntimeError('CST reported an error during parametric rebuild')
        return dict(parameters=records,messages=messages,method='DeleteResults; guarded StoreParameter; one RebuildOnParametricChange')

    def close(self, project):
        project.close()

    def observe(self, project, directory):
        from cst_cad.observation import VBA_TEMPLATE, parse
        path = directory/'observation.txt'
        project.model3d._execute_vba_code('Sub Main\n'+VBA_TEMPLATE.format(output=str(path).replace('"', '""'))+'\nEnd Sub')
        return parse(path.read_text(encoding='utf-8-sig'))

    def read_setup(self, project, setup, directory):
        m = project.model3d
        result = {}
        getters = {
            'solver': lambda: {'HF Frequency Domain': 'frequency_domain', 'HF Time Domain': 'time_domain'}[str(m.GetSolverType())],
            'frequency.min': lambda: float(m.Solver.GetFmin()),
            'frequency.max': lambda: float(m.Solver.GetFmax()),
        }
        # Documented getters only. Their return values are independent of the
        # requested setup; an unexpected unit/boundary remains a mismatch.
        for key, dimension in {'length':'Length','frequency':'Frequency','time':'Time','temperature':'Temperature'}.items():
            if key in setup['units']:
                getters['units.'+key]=lambda dimension=dimension: str(m.Units.GetUnit(dimension))
        for face in ('xmin','xmax','ymin','ymax','zmin','zmax'):
            getters['boundaries.'+face]=lambda face=face: str(getattr(m.Boundary,'Get'+face.capitalize())())
        for axis in ('x','y','z'):
            getters['boundaries.symmetry.'+axis]=lambda axis=axis: str(getattr(m.Boundary,'Get'+axis.upper()+'Symmetry')())
        def monitors():
            count=int(m.Monitor.GetNumberOfMonitors())
            if count<0:raise ValueError('invalid native monitor count')
            if count:raise ValueError(f'{count} native monitors exist; monitor execution is unsupported')
            return []
        getters['monitors']=monitors
        for name, query in getters.items():
            try:
                result[name] = dict(value=query(), method='native CST getter')
            except Exception as exc:
                result[name] = dict(error=str(exc))
        from .native_ports import read_ports
        result.update(read_ports(m, directory))
        mesh_type = {'tetrahedral': 'Tet', 'hexahedral': 'Hex'}[setup['mesh']['kind']]
        target = directory/'mesh-readback.txt'
        macro = '\n'.join(['Sub Main', f'Open "{str(target).replace(chr(34), chr(34)*2)}" For Output As #7',
            'With MeshSettings', f'.SetMeshType "{mesh_type}"',
            'Print #7, .Get("StepsPerWaveNear")', 'Print #7, .Get("StepsPerBoxNear")',
            'End With', 'Close #7', 'End Sub'])
        try:
            m._execute_vba_code(macro)
            values = target.read_text(encoding='utf-8-sig').splitlines()
            if len(values) != 2:
                raise ValueError('incomplete native mesh readback')
            for key, value in zip(('steps_per_wavelength_near', 'cells_per_max_cell_near'), values):
                result['mesh.'+key] = dict(value=float(value.replace(',', '.')), method=f'MeshSettings {mesh_type} map getter')
        except Exception as exc:
            result['mesh.steps_per_wavelength_near'] = dict(error=str(exc))
        # No guessed getters and no setter-as-getter guard bypass. Coverage gaps
        # remain visible; the verifier distinguishes core gates from fine reads.
        return result

    def log_paths(self, project_path):
        return dict(model=project_path.with_suffix('')/'Result/Model.log',
                    output=project_path.with_suffix('')/'Result/output.txt')

    def solve(self, project):
        project.model3d.run_solver()

    def export(self, project, stem, setup):
        from cst.post_processing.s_parameters import export_touchstone
        stem.parent.mkdir(parents=True, exist_ok=False)
        export_touchstone(project, str(stem), impedance=setup['settings']['norming_impedance'],
                          export_type='S', format='RI', renormalize=True)
        return stem.with_suffix(f'.s{len(setup["ports"])}p')


def verify_reopen(prepared, root, source, directory, expected_snapshot, backend, authorize, progress):
    """Open an independent cache-free copy, never the staged archive itself."""
    from cst_lab.project_package import copy_clean_model, model_snapshot
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    receipt=dict(schema_version=1,status='running',approval_validated=False,project_closed=False,
                 cache_free_before_open=False,source_unchanged=False,model_snapshot_sha256=expected_snapshot)
    project=None
    try:
        authorize();receipt['approval_validated']=prepared.approval_sha256 is not None
        receipt['execution_authorized']=True
        if digest(model_snapshot(source))!=expected_snapshot:raise ValueError('staged model changed before reopen')
        copied=directory/'working/model.cst'
        copy_clean_model(root,source,copied)
        if sorted(p.name for p in copied.with_suffix('').iterdir())!=['Model']:
            raise ValueError('reopen copy contains more than Model companion')
        receipt['cache_free_before_open']=True
        progress('reopening-clean-copy',{'model_snapshot_sha256':expected_snapshot})
        atomic_json(directory/'reopen-receipt.json',receipt)
        project=backend.open_project(copied)
        receipt['runtime']=backend.runtime(project)
        observed=backend.observe(project,directory)
        actual=backend.read_setup(project,prepared.execution['setup'],directory)
        receipt['verification']=verify_readback(prepared.document,observed,prepared.execution['setup'],actual)
        atomic_json(directory/'observation.json',observed)
        atomic_json(directory/'native-settings.json',actual)
        if receipt['verification']['status']!='verified':raise ExecutionBlocked('reopened core model/settings are not verified')
        authorize()
        receipt['status']='verified'
    except Exception as exc:
        receipt.update(status='failed',error=f'{type(exc).__name__}: {exc}')
    finally:
        if project is not None:
            try:backend.close(project);receipt['project_closed']=True
            except Exception as exc:receipt.update(status='failed',error=f'reopen close failed: {exc}')
        try:receipt['source_unchanged']=digest(model_snapshot(source))==expected_snapshot
        except Exception as exc:receipt.update(status='failed',error=f'staged model changed: {exc}')
        if not receipt['source_unchanged']:receipt['status']='failed'
        atomic_json(directory/'reopen-receipt.json',receipt)
    return receipt
