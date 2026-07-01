"""Capture platform adapters for API, MCP, and shared runtime control."""

# --- stdlib shadow guard ---------------------------------------------------
# This package is named ``platform``, which collides with the standard-library
# ``platform`` module. Whenever ``src/`` is on ``sys.path`` -- tox sets
# ``PYTHONPATH=src`` and the ``-m src.platform.*`` entrypoints insert it so the
# ``media_ark`` brand module resolves -- a bare ``import platform`` would find
# THIS package instead of the stdlib. Some stdlib modules do exactly that at
# import time (e.g. Python 3.11's ``uuid`` runs ``platform.system()`` on load),
# which fails here with ``module 'platform' has no attribute 'system'``.
#
# Importing this package first pins the genuine stdlib module into
# ``sys.modules['platform']`` (loaded by explicit file path, so it works even
# when ``src/`` shadows it), making every later bare ``import platform`` resolve
# to the real one. The permanent fix is to rename this package; see NEXT.md.
import sys as _sys

if not hasattr(_sys.modules.get("platform"), "system"):
    import importlib.util as _ilu
    import os as _os
    import sysconfig as _sc

    _stdlib_platform = _os.path.join(_sc.get_paths()["stdlib"], "platform.py")
    _spec = _ilu.spec_from_file_location("platform", _stdlib_platform)
    if _spec and _spec.loader and _os.path.exists(_stdlib_platform):
        _module = _ilu.module_from_spec(_spec)
        _sys.modules["platform"] = _module
        _spec.loader.exec_module(_module)
        del _module
    del _ilu, _os, _sc, _stdlib_platform, _spec

del _sys
