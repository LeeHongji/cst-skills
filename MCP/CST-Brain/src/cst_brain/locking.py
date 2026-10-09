from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable, TypeVar

from .paths import BrainPaths


class MutationLock(AbstractContextManager["MutationLock"]):
    """Serialize multi-file vault mutations across local agent processes."""

    def __init__(
        self,
        paths: BrainPaths,
        key: str = "vault",
        timeout_seconds: float = 15.0,
        stale_seconds: float = 300.0,
    ):
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        self.path = paths.state / "locks" / f"{digest}.lock"
        self.timeout_seconds = timeout_seconds
        self.stale_seconds = stale_seconds
        self.acquired = False

    def __enter__(self) -> "MutationLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout_seconds
        payload = json.dumps(
            {
                "pid": os.getpid(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
        )
        while True:
            try:
                descriptor = os.open(
                    self.path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > self.stale_seconds:
                        self.path.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Timed out waiting for Brain mutation lock: {self.path}"
                    )
                time.sleep(0.05)
                continue
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
            self.acquired = True
            return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.acquired:
            self.path.unlink(missing_ok=True)
            self.acquired = False


F = TypeVar("F", bound=Callable[..., Any])


def serialized_mutation(key: str) -> Callable[[F], F]:
    """Decorate a BrainOperations method with a cross-process vault lock."""

    def decorate(function: F) -> F:
        @wraps(function)
        def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
            with MutationLock(self.paths, key):
                return function(self, *args, **kwargs)

        return wrapped  # type: ignore[return-value]

    return decorate
