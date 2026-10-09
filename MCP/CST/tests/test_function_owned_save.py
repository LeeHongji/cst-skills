from pathlib import Path
from types import SimpleNamespace

import pytest

from cst_guardian.function_execution import NativeBackend


class Project:
    def __init__(self,path):self.path=path;self.calls=[]
    def filename(self):return str(self.path)
    def save(self,path,**options):self.calls.append((Path(path),options))


def test_repeated_save_explicitly_overwrites_only_owned_working_copy(tmp_path):
    target=tmp_path/'working/model.cst';project=Project(target)
    session=SimpleNamespace(info=SimpleNamespace(launched=True,open_projects=[]),new_project=lambda path:project)
    backend=NativeBackend(session,'0'*64)
    assert backend.new_project(target)==project
    backend.save(project);backend.save(project)
    assert project.calls==[(target,{'allow_overwrite':True})]*2
    project.path=tmp_path/'user-source.cst'
    with pytest.raises(ValueError,match='filename changed'):backend.save(project)
    assert len(project.calls)==2


def test_backend_cannot_save_an_unowned_project(tmp_path):
    project=Project(tmp_path/'source.cst')
    with pytest.raises(ValueError,match='not opened'):NativeBackend(None,'0'*64).save(project)
    assert project.calls==[]
