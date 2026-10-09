"""Pytest configuration for Institutional Memory test suite."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Fix standard library 'signal' collision by ensuring the local package path is attached
signal_dir = ROOT / "signal"
if "signal" in sys.modules:
    sig = sys.modules["signal"]
    if not hasattr(sig, "__path__"):
        sig.__path__ = [str(signal_dir)]
