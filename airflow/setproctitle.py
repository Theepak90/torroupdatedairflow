"""Local shim to avoid macOS crashes/hangs in the native `setproctitle` extension.

Airflow (and its log server / gunicorn) imports `setproctitle` unconditionally.
On macOS, the native extension can spin/hang or segfault.

By placing this module in AIRFLOW_HOME, it is found before site-packages,
turning process-title changes into a harmless no-op.

CROSS-PLATFORM NOTE:
- macOS: Required to prevent crashes
- Windows/Linux: Harmless (can be ignored or removed - native extension works fine)
"""

from __future__ import annotations

from typing import Optional


def setproctitle(title: str) -> None:
    # Intentionally a no-op.
    return None


def getproctitle() -> str:
    # Best-effort; no real title tracking.
    return ""


def setthreadtitle(title: str) -> None:
    # Some callers use this; keep as no-op.
    return None


def getthreadtitle() -> Optional[str]:
    return None
