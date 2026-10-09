import importlib.util
import json
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('verify_brain_manifests',ROOT/'scripts/validation/verify_brain_manifests.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def sample():
    job='job://'+'a'*64+'/'+'b'*32
    return dict(schema_version=1,kind='function-iteration',case_id='case',title='test',published_at='2026-09-22',
        source=dict(history_uri='workspace://history',history_sha256='c'*64,iteration=1,job_id=job),
        request=dict(topic='t',design='d',attempt='a',request_id='r',operation='analyze',why='test'),
        fact=dict(iter=1,job_id=job,status='completed',artifacts={}),evidence=[])


def test_function_projection_has_own_schema_and_binds_source():
    document=sample()
    assert module.validate(document,ROOT/'brain/schemas')=='function'
    document['source']['iteration']=2
    with pytest.raises(ValueError,match='identity'): module.validate(document,ROOT/'brain/schemas')


def test_missing_evidence_and_unfinalized_fact_are_rejected():
    document=sample();document['fact']['artifacts']={'x':'artifact://x'}
    with pytest.raises(ValueError,match='evidence'): module.validate(document,ROOT/'brain/schemas')
    document=sample();document['fact']['status']='running'
    from jsonschema import ValidationError
    with pytest.raises(ValidationError): module.validate(document,ROOT/'brain/schemas')
