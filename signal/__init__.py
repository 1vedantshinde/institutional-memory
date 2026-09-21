"""DAQ signal modules while preserving the standard-library :mod:`signal` API.

The required project package name collides with Python's standard ``signal``
module. Re-exporting that module's public attributes keeps dependencies such as
``psutil`` working, while this package still exposes ``signal.preprocessing``
and ``signal.windowing``.
"""

from __future__ import annotations

import importlib.util
import sys
import sysconfig
from pathlib import Path


_stdlib_signal_path = Path(sysconfig.get_path("stdlib")) / "signal.py"
_stdlib_signal_spec = importlib.util.spec_from_file_location(
    "_daq_stdlib_signal", _stdlib_signal_path
)
if _stdlib_signal_spec is None or _stdlib_signal_spec.loader is None:  # pragma: no cover
    raise ImportError("Unable to load the standard-library signal module")
_stdlib_signal = importlib.util.module_from_spec(_stdlib_signal_spec)
sys.modules[_stdlib_signal_spec.name] = _stdlib_signal
_stdlib_signal_spec.loader.exec_module(_stdlib_signal)

for _name in dir(_stdlib_signal):
    if not _name.startswith("__"):
        globals().setdefault(_name, getattr(_stdlib_signal, _name))
