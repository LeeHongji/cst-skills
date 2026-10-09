"""Resolve topic ownership without depending on a user's directory layout.

Only the configured workspace and this platform's Git worktrees are trusted.
Requests never supply arbitrary filesystem roots. Ambiguous identities fail
closed instead of silently selecting a different experiment.
"""
from pathlib import Path
import os
import re
import subprocess

PLATFORM_ROOT = Path(__file__).resolve().parents[2]


def workspace_roots(platform=PLATFORM_ROOT, configured=None):
    roots = [Path(configured or os.environ.get('CST_AUTOMATION_ROOT') or platform).resolve()]
    from cst_lab.workspace import default_workspace, settings
    if not configured and not os.environ.get('CST_AUTOMATION_ROOT'):
        roots = [default_workspace(platform)]
    if settings(roots[0]):
        return roots
    result = subprocess.run(['git', '-C', str(platform), 'worktree', 'list', '--porcelain', '-z'],
                            stdin=subprocess.DEVNULL, capture_output=True, check=False, timeout=10)
    if result.returncode == 0:
        roots += [Path(field[9:]).resolve() for field in result.stdout.decode('utf-8').split('\0')
                  if field.startswith('worktree ')]
    return list(dict.fromkeys(p for p in roots if p.is_dir()))


class WorkspaceRouter:
    def __init__(self, roots=None):
        self._roots = roots

    def roots(self):
        return [Path(p).resolve() for p in self._roots] if self._roots is not None else workspace_roots()

    @staticmethod
    def _unique(matches, label):
        if not matches:
            raise ValueError(f'{label} not found in registered workspaces')
        if len(matches) != 1:
            raise ValueError(f'{label} is ambiguous across registered workspaces: {matches}')
        return matches[0]

    def topic_root(self, topic):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', topic):
            raise ValueError('invalid topic identifier')
        from cst_lab.workspace import settings, registered_projects
        return self._unique([p for p in self.roots() if (topic in registered_projects(p) if settings(p) else (p/'projects'/topic).is_dir())], f'topic {topic}')

    def attempt_root(self, attempt):
        parts = attempt.replace('\\', '/').split('/')
        if len(parts) != 7 or (parts[0], parts[2], parts[4], parts[6]) != ('projects', 'designs', 'attempts', 'attempt.json'):
            raise ValueError('attempt must be projects/<topic>/designs/<design>/attempts/<attempt>/attempt.json')
        if any(p in ('.', '..', '') for p in parts):
            raise ValueError('invalid attempt path')
        root = self.topic_root(parts[1])
        if not (root/attempt).resolve().is_relative_to(root):
            raise ValueError('attempt escapes workspace')
        return root

    def ref_root(self, ref):
        match = re.fullmatch(r'(?:job|artifact)://([0-9a-f]{64})/([0-9a-f]{32})(?:/(.+))?', ref)
        if not match or (ref.startswith('job://') and match[3]) or (ref.startswith('artifact://') and not match[3]):
            raise ValueError('invalid job/artifact reference')
        # State files contain multiple jobs for an attempt. Check exact job ID
        # through JobStore, not just existence of an attempt's state file.
        from cst_lab.jobs import JobStore, JobError
        matches = []
        for root in self.roots():
            from cst_lab.paths import LabPaths
            if not (LabPaths.resolve(root).registry_root/'function-jobs'/match[1]/'state.json').is_file():
                continue
            try:
                JobStore(root).get(f'job://{match[1]}/{match[2]}')
            except (KeyError, FileNotFoundError, JobError):
                continue
            matches.append(root)
        return self._unique(matches, 'job reference')

    def service(self, root):
        from cst_agent_api import FunctionService
        return FunctionService(root)

    def run(self, request):
        from cst_lab.function_contract import RunRequest
        normalized = RunRequest.parse(request).document
        return self.service(self.topic_root(normalized['topic'])).run(normalized)

    def get(self, ref):
        return self.service(self.ref_root(ref)).get(ref)
