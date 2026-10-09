"""Trusted, versioned CSTLab data layout. Legacy checkouts retain their defaults."""
import json
import os
import re
from pathlib import Path


def default_workspace(platform):
    if value := os.environ.get('CST_AUTOMATION_ROOT'):
        return Path(value).expanduser().resolve()
    platform = Path(platform).resolve()
    config = platform / 'cstlab.local.json'
    if config.is_file():
        doc = json.loads(config.read_text(encoding='utf-8-sig'))
        if doc.get('schema_version') != 1 or not isinstance(doc.get('data_root'), str):
            raise ValueError('invalid CSTLab local configuration')
        return (platform / doc['data_root']).resolve()
    return platform


def settings(root):
    root = Path(root).resolve()
    marker = root / 'workspace.json'
    if not marker.exists():
        return None
    doc = json.loads(marker.read_text(encoding='utf-8'))
    if doc.get('schema_version') != 1 or doc.get('layout') != 'cstlab' or not isinstance(doc.get('software_root'), str):
        raise ValueError('unsupported CSTLab data schema/layout')
    software = (root / doc['software_root']).resolve()
    if not (software / 'brain/schemas').is_dir():
        raise ValueError('CSTLab software schema directory is missing')
    return {**doc, 'software': software}


def registered_projects(root):
    root = Path(root).resolve()
    doc = json.loads((root / 'system/projects.json').read_text(encoding='utf-8'))
    if doc.get('schema_version') != 1 or not isinstance(doc.get('projects'), list):
        raise ValueError('unsupported project registry')
    result = {}
    for item in doc['projects']:
        identity = item.get('id', '')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', identity) or identity.casefold() in {k.casefold() for k in result}:
            raise ValueError('invalid or duplicate project ID')
        path = root / 'projects' / identity
        if any(p.is_symlink() or p.is_junction() for p in (path, path.parent)) or not path.resolve().is_relative_to(root):
            raise ValueError('project must not escape data root or use a link')
        if not path.is_dir():
            raise ValueError('registered project is missing: ' + identity)
        result[identity] = path
    return result
