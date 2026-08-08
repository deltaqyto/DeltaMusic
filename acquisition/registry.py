from __future__ import annotations

import sys
from typing import Dict, List, Optional, Tuple, Type

from .interfaces import Backend

# name -> (module path, class name).
_BACKENDS: Dict[str, Tuple[str, str]] = {
    "windows": ("acquisition.backends.windows", "WindowsBackend"),
    # "linux": ("acquisition.backends.linux", "LinuxBackend"),  # Not implemented yet
}


def backend_names() -> List[str]:
    """Every registered backend name, available here or not."""
    return list(_BACKENDS)


def load_backend_class(name: str) -> Type[Backend]:
    try:
        module_path, class_name = _BACKENDS[name]
    except KeyError:
        raise ValueError(
            f"unknown backend {name!r}; registered backends are {backend_names()}"
        ) from None

    from importlib import import_module

    try:
        module = import_module(module_path)
    except ImportError as exc:
        raise ValueError(
            f"backend {name!r} could not be imported ({exc}). Its dependencies "
            f"are probably not installed on this machine."
        ) from exc
    return getattr(module, class_name)


def available_backends() -> List[Type[Backend]]:
    """Backend classes that report themselves usable here."""
    usable: List[Type[Backend]] = []
    for name in _BACKENDS:
        try:
            backend = load_backend_class(name)
        except ValueError:
            continue
        if backend.is_available():
            usable.append(backend)
    return usable


def select(name: Optional[str] = None) -> Type[Backend]:
    """Pick a backend class: the named one, else the first usable one."""
    if name:
        backend = load_backend_class(name)
        if not backend.is_available():
            raise ValueError(
                f"backend {name!r} is not available on this machine "
                f"(platform is {sys.platform!r}); check its dependencies are installed"
            )
        return backend

    usable = available_backends()
    if not usable:
        raise ValueError(
            f"no acquisition backend is available on {sys.platform!r}. "
            f"Registered backends: {backend_names()}. "
            f"On Windows this usually means the winrt packages are missing - "
            f"see requirements.txt."
        )
    return usable[0]
