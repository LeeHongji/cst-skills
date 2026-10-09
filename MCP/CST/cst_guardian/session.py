"""Quiet-mode-enforcing CST session, used inside a worker process.

Quiet mode is what stops CST from blocking on a prompt, but it does not make the
underlying conflict disappear -- CST simply takes the default answer without
asking.  Two things therefore travel with every session:

* ``quiet_mode`` is recorded in :class:`SessionInfo` so an iteration record can
  state whether prompts were suppressed while it ran.  A result produced under
  suppression is not self-evidently trustworthy.
* the caller is expected to have passed DRC first.  DRC is the safety net that
  makes suppression acceptable; quiet mode without it converts visible hangs
  into silent wrong defaults.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .paths import ensure_cst_paths


@dataclass
class SessionInfo:
    pid: int | None = None
    quiet_mode: bool = False
    quiet_mode_was_already_on: bool = False
    quiet_mode_enforced: bool = False
    launched: bool = False
    closed: bool = False
    install_root: str | None = None
    open_projects: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, object]:
        return {
            "pid": self.pid,
            "quiet_mode": self.quiet_mode,
            "quiet_mode_was_already_on": self.quiet_mode_was_already_on,
            "quiet_mode_enforced": self.quiet_mode_enforced,
            "launched": self.launched,
            "closed": self.closed,
            "install_root": self.install_root,
            "open_projects": list(self.open_projects),
        }


class GuardedSession:
    """Context manager that guarantees quiet mode for the life of the block.

    On exit the previous quiet-mode state is restored, so attaching to an
    engineer's interactive CST session does not silently leave prompts suppressed
    after the automation finishes.
    """

    def __init__(
        self,
        pid: int | None = None,
        *,
        launch_if_needed: bool = False,
        force_new: bool = False,
        restore_on_exit: bool = True,
        enforce_quiet: bool = True,
        close_launched: bool = True,
    ) -> None:
        """
        ``enforce_quiet=False`` deliberately leaves prompts visible.  L1
        (suppression) and L3 (known-dialog response) are alternative defences
        rather than cumulative ones: with quiet mode on, CST answers for itself
        and the dialog table is never exercised.  Verifying L3 therefore requires
        turning L1 off.  Production callers leave this at ``True``.

        ``close_launched`` shuts down an instance this session started.  Without
        it every failed run strands a full CST process holding licences and
        project locks, and the next run then fails with "Project is already open
        in another instance of CST Studio Suite".  An instance we merely attached
        to is never closed, because it belongs to somebody else.
        """
        self.pid = pid
        self.launch_if_needed = launch_if_needed
        self.force_new = force_new
        self.restore_on_exit = restore_on_exit
        self.enforce_quiet = enforce_quiet
        self.close_launched = close_launched
        self.info = SessionInfo()
        self.de: Any | None = None

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self) -> GuardedSession:
        root = ensure_cst_paths()
        self.info.install_root = str(root)
        import cst.interface as ci

        if self.force_new:
            self.de = ci.DesignEnvironment.new(
                options=["--quiet"] if self.enforce_quiet else []
            )
            self.info.launched = True
        elif self.pid is not None:
            self.de = ci.DesignEnvironment.connect(self.pid)
        elif self.launch_if_needed:
            before = set(ci.running_design_environments())
            self.de = ci.DesignEnvironment.connect_to_any_or_new()
            self.info.launched = bool(set(ci.running_design_environments()) - before)
        else:
            self.de = ci.DesignEnvironment.connect_to_any()

        with contextlib.suppress(Exception):
            self.info.pid = int(self.de.pid())
        self._enforce_quiet_mode()
        with contextlib.suppress(Exception):
            self.info.open_projects = [str(p) for p in self.de.list_open_projects()]
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if (
            self.restore_on_exit
            and self.info.quiet_mode_enforced
            and not self.info.quiet_mode_was_already_on
            and self.de is not None
        ):
            with contextlib.suppress(Exception):
                self.de.set_quiet_mode(False)
                self.info.quiet_mode = False
        if self.close_launched and self.info.launched and self.de is not None:
            with contextlib.suppress(Exception):
                self.de.close()
                self.info.closed = True

    def _enforce_quiet_mode(self) -> None:
        de = self.de
        if de is None:  # pragma: no cover - guarded by __enter__ ordering
            return
        if not self.enforce_quiet:
            with contextlib.suppress(Exception):
                self.info.quiet_mode = bool(de.in_quiet_mode())
                self.info.quiet_mode_was_already_on = self.info.quiet_mode
            return
        already_on = False
        with contextlib.suppress(Exception):
            already_on = bool(de.in_quiet_mode())
        self.info.quiet_mode_was_already_on = already_on
        if already_on:
            self.info.quiet_mode = True
            return
        de.set_quiet_mode(True)
        self.info.quiet_mode_enforced = True
        with contextlib.suppress(Exception):
            self.info.quiet_mode = bool(de.in_quiet_mode())

    # -- project handling --------------------------------------------------

    def open_project(self, path: str | Path) -> Any:
        """Open an existing project, refusing a path that is not a file.

        The path is resolved to an absolute one before CST sees it.  CST's working
        directory is not the caller's, so a relative path means something else (or
        nothing) to it -- and the observed failure is not an error but a hang, so
        the mistake costs a full timeout rather than an immediate complaint.
        """
        cst_path = Path(path).expanduser()
        if not cst_path.is_file():
            raise FileNotFoundError(str(cst_path))
        return self._require_de().open_project(str(cst_path.resolve()))

    def new_project(self, save_as: str | Path | None = None) -> Any:
        """Create an MWS project, refusing to overwrite an existing file.

        Refusing here rather than answering an overwrite prompt keeps the
        no-overwrite rule in code, where it is testable, instead of relying on a
        dialog response.
        """
        project = self._require_de().new_mws()
        if save_as is not None:
            target = Path(save_as).expanduser()
            if target.exists():
                raise FileExistsError(
                    f"{target} already exists; copy the source into a run workspace "
                    "instead of overwriting it"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            project.save(str(target.resolve()))
        return project

    def _require_de(self) -> Any:
        if self.de is None:
            raise RuntimeError("GuardedSession must be entered before use")
        return self.de
