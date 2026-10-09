"""Generate public contract-test data, without historical research packages."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys


def generate(root):
    root=Path(root).resolve()
    sys.path[:0]=[str(root/'MCP/CST-CAD/src'),str(root/'MCP/CST-Lab/src')]
    from cst_cad import ir
    from cst_lab.contracts.design import write_design
    from cst_lab.contracts.topic import write_topic
    from cst_lab.contracts.attempt import write_attempt
    from cst_lab.paths import LabPaths
    legacy=root/'MCP/CST-Lab/tests/fixtures/dual-mode-open-loop-filters'
    if legacy.exists():
        if not legacy.resolve().is_relative_to(root) or any(p.is_symlink() or p.is_junction() for p in [legacy,*legacy.parents]):
            raise ValueError('Refusing linked fixture cleanup')
        shutil.rmtree(legacy)  # Exactly the copied historical test fixture, never a user topic.
    topic=root/'MCP/CST-Lab/tests/fixtures/public-contract-fixture'
    design=topic/'designs/filter-fixture';attempt=design/'attempts/a01-test'
    attempt.mkdir(parents=True,exist_ok=True)
    paths=LabPaths.resolve(root)
    write_topic(topic/'topic.md',dict(schema_version=1,topic_id=topic.name,title='Synthetic public contract fixture',
        shared_physics=['Internally specified lowpass test geometry; no paper claims'],
        sources=[dict(kind='internal',citation='MIT public lowpass fixture')]),
        'Synthetic contract data for validator tests, not a historical research topic.',paths)
    (topic/'notes.md').write_text('# Synthetic test notes\n',encoding='utf-8')
    gates=[]
    for identity,metric,band,comparator,threshold,mode in [
        ('interior_return_loss','s1_1_db',[1.010,1.090],'<',-8.,'pointwise'),
        ('interior_insertion_loss','s2_1_db',[1.010,1.090],'>',-1.,'pointwise'),
        ('lower_transmission_zero','s2_1_db',[.900,.990],'<',-40.,'aggregate'),
        ('upper_transmission_zero','s2_1_db',[1.150,1.250],'<',-40.,'aggregate')]:
        gate=dict(id=identity,metric=metric,band_ghz=band,comparator=comparator,threshold=threshold,mode=mode,
            note='Synthetic threshold selected only to test contract parsing; not measured or paper-derived.')
        if mode=='aggregate':gate['aggregate']='min'
        gates.append(gate)
    write_design(design/'design.md',dict(schema_version=1,design_id=design.name,topic_id=topic.name,
        title='Synthetic two-port contract fixture',model='model.py',ports=2,acceptance=gates),
        'Test gates do not describe the physical acceptance of the lowpass example.',paths)
    shutil.copy2(root/'examples/lowpass/model.py',design/'model.py')
    spec=importlib.util.spec_from_file_location('public_fixture_model',design/'model.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    doc=module.build();ir.write(doc,attempt/'geometry-ir.json')
    parameters={p['name']:p['value'] for p in doc['parameters']}
    assumptions=[dict(parameter=name,provenance='assumption' if index<6 else 'strong_inference',
        statement='Synthetic annotation to exercise provenance validation; no engineering conclusion.')
        for index,name in enumerate(parameters)]
    write_attempt(attempt/'attempt.json',dict(schema_version=1,topic_id=topic.name,design_id=design.name,
        attempt_id=attempt.name,topology_hash=ir.topology_hash(doc),model_intent_id=ir.model_intent_id(doc),
        baseline_parameters=parameters,approved_ranges={'l3':[13.,15.]},max_iterations=12,assumptions=assumptions),paths)
    test=root/'MCP/CST-Lab/tests/test_contracts.py'
    text=test.read_text(encoding='utf-8')
    text=text.replace('dual-mode-open-loop-filters','public-contract-fixture').replace('fig15-filter-d','filter-fixture').replace('a01-paper-ideal','a01-test')
    text=text.replace('FIG15_DESIGN','FIXTURE_DESIGN').replace('FIG15_ATTEMPT','FIXTURE_ATTEMPT')
    text=text.replace('assert "non-resonating" in body','assert "Synthetic" in body')
    start=text.index('    assert set(attempt["approved_ranges"]) == {')
    end=text.index('    assert len(attempt["baseline_parameters"])',start)
    text=text[:start]+'    assert set(attempt["approved_ranges"]) == {"l3"}\n'+text[end:]
    text=text.replace('test_the_real_','test_the_public_fixture_').replace('test_every_real_gate','test_every_fixture_gate')
    text=text.replace('The paper gives no numeric passband for Filter D, so a bare number would be\n    indistinguishable from a fabricated one.',
        'Synthetic test gates must state their source instead of masquerading as\n    paper or measured engineering requirements.')
    test.write_text(text,encoding='utf-8')


if __name__=='__main__':generate(Path(__file__).resolve().parents[2])
