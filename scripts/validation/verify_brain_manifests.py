"""Public pure verification helpers; historical drivers and data are excluded."""
import json, jsonschema

def validate(document, schemas):
    function = document.get('kind') == 'function-iteration'
    name = 'function-iteration-manifest.schema.json' if function else 'run-manifest.schema.json'
    jsonschema.validate(document, json.loads((schemas/name).read_text(encoding='utf-8')))
    if function:
        source, fact = document['source'], document['fact']
        if source['job_id'] != fact['job_id'] or source['iteration'] != fact['iter']:
            raise ValueError('Function manifest source/fact identity mismatch')
        if set(document['evidence']) != set(fact['artifacts'].values()):
            raise ValueError('Function manifest evidence differs from finalized fact')
    return 'function' if function else 'native'
