"""dataset.py — build everything the app needs from the raw pitch table, then let the raw table go."""
from __future__ import annotations

import ctypes
import gc

from compute import precompute_all_impl


def release_memory() -> None:
    """Hand freed memory back to the OS (glibc keeps it otherwise → RSS stays high after big computations)."""
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


def build_from_frame(df, source: str) -> dict:
    """Run the one-off precompute. The returned dict holds only compact weekly/matchup tables + small metadata;
    the raw pitch-level frame is NOT kept (it was the largest object by far)."""
    pc = precompute_all_impl(df)
    release_memory()
    return {"source": source, "pc": pc}
