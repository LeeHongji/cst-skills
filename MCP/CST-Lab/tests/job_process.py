"""Owned subprocess used to test OS locks and abrupt death, never CST."""
import json
import os
from pathlib import Path
import sys

from cst_lab.contracts.iterations import append_iteration, iteration_line
from cst_lab.function_contract import RunRequest
from cst_lab.jobs import JobStore
from cst_lab.paths import LabPaths


def main():
    mode, root, platform, argument = sys.argv[1:]
    store = JobStore(Path(root), paths=LabPaths.resolve(platform))
    try:
        if mode == 'submit':
            ref = store.submit(RunRequest.parse(json.loads(argument)))
            print(json.dumps({'ref': ref, 'pid': os.getpid()}), flush=True)
            return
        if mode == 'append':
            append_iteration(Path(root) / 'race.jsonl', iteration_line(iter_number=0, audited=False), store.paths)
            print('appended', flush=True)
            return
        ref = argument
        if mode.startswith('publication-'):
            from cst_lab.function_evidence import complete_publication,prepare_analysis
            stage=store.root/'cst_runs/analysis'
            stage.mkdir(parents=True)
            (stage/'metrics.json').write_text('{"test_value":2.0}')
            manifest_hash=prepare_analysis(stage,ref)
            def die_at_publication(directory,state,key):
                intent=state['jobs'][key]['final_intent']
                if mode!='publication-intent':
                    complete_publication(store.root,store.root/state['attempt'],ref,intent['publication'],store.paths)
                if mode in ('publication-partial','publication-appended'):
                    history=(store.root/state['attempt']).parent/'iterations.jsonl'
                    payload=intent['payload'].encode('utf-8')
                    with history.open('ab') as handle:
                        handle.write(payload[:len(payload)//2] if mode=='publication-partial' else payload)
                        handle.flush();os.fsync(handle.fileno())
                os._exit(74)
            store._publish=die_at_publication
            with store.claim(ref) as session:
                job=store.get(ref)
                session.finish(iteration_line(iter_number=job['iteration'],parent=job['request']['parent'],
                    status='completed',audited=False,provenance='native',execution_kind='offline',
                    duration_s=.1,cache_hit=False,evidence=dict(kind='offline-analysis',
                        revision='r-'+ref.rsplit('/',1)[1],manifest_sha256=manifest_hash)),stage=stage)
            raise AssertionError('worker should have exited')
        if mode in ('partial', 'appended'):
            def die_during_publish(directory, state, key):
                intent = state['jobs'][key]['final_intent']
                path = (store.root / state['attempt']).parent / 'iterations.jsonl'
                payload = intent['payload'].encode('utf-8')
                with path.open('ab') as handle:
                    handle.write(payload[:len(payload)//2] if mode == 'partial' else payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os._exit(73)
            store._publish = die_during_publish
        with store.claim(ref) as session:
            if mode == 'hold':
                (Path(root) / 'claimed').write_text(str(os.getpid()))
                sys.stdin.read(1)
                return
            job = store.get(ref)
            session.finish(iteration_line(iter_number=job['iteration'], parent=job['request']['parent'],
                status='completed', audited=False, provenance='native', execution_kind='offline',
                duration_s=.25, cache_hit=False, acceptance={'status':'fail','gates':[]},
                metrics={'test_value': 2.0}, observation='Synthetic job protocol test; not an EM result'))
        print('finished', flush=True)
    except Exception as exc:
        print(json.dumps({'error': type(exc).__name__, 'message': str(exc)}), flush=True)
        sys.exit(2)


if __name__ == '__main__':
    main()
