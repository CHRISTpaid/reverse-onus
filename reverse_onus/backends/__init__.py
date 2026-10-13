from __future__ import annotations

from .base import Backend, BackendError, Cancelled, EngineResult, EngineTask

_CACHE: dict[str, Backend] = {}


def get_backend(name: str) -> Backend:
    if name in _CACHE:
        return _CACHE[name]
    if name == "mock":
        from .mock import MockBackend as B
    elif name == "acestep":
        from .acestep import AceStepBackend as B
    elif name == "yue2":
        from .yue2 import YuE2Backend as B
    else:
        raise BackendError(f"unknown backend '{name}' (mock|acestep|yue2)")
    _CACHE[name] = B()
    return _CACHE[name]


__all__ = ["Backend", "BackendError", "Cancelled", "EngineResult", "EngineTask", "get_backend"]
