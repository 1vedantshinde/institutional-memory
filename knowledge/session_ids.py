"""Global Session ID Addressing and Resolution (Option A).

Assigns reproducible session_id (1..822) ordered by condition_id and recording_number.
Provides parsing and resolution helpers for query understanding and graph traversal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from ingestion.manifest import ManifestEntry, discover_manifest


@dataclass(frozen=True)
class SessionReference:
    """Resolved session identifier with full condition and recording coordinates."""

    session_id: int
    condition_id: str
    recording_number: int
    matched_text: str = ""
    canonical_node_id: str = ""

    def __post_init__(self):
        if not self.canonical_node_id:
            object.__setattr__(
                self, "canonical_node_id", f"session:{self.session_id}"
            )


# Regex patterns for various session reference syntaxes
_SESSION_NUM_REGEX = re.compile(
    r"\b(?:session|sess\.?|run|recording|rec\.?)\s*(?:#|no\.?|id)?\s*(\d+)\b",
    re.IGNORECASE,
)

_COND_REC_REGEX = re.compile(
    r"\b(?:condition|cond\.?|c)\s*(\d+)[,\s]+(?:recording|rec\.?|run|r)\s*(\d+)\b",
    re.IGNORECASE,
)

_REC_IN_COND_REGEX = re.compile(
    r"\b(?:recording|rec\.?|run|r)\s*(\d+)\s+(?:in|of|under|for)\s+(?:condition|cond\.?|c)\s*(\d+)\b",
    re.IGNORECASE,
)

_COND_ONLY_REGEX = re.compile(
    r"\b(?:condition|cond\.?|c)\s*(\d+)\b",
    re.IGNORECASE,
)


class SessionIDRegistry:
    """Singleton/Instance registry mapping global session_id <-> (condition_id, recording_number)."""

    def __init__(self, entries: Optional[List[Union[ManifestEntry, dict]]] = None):
        self._id_to_tuple: Dict[int, Tuple[str, int]] = {}
        self._tuple_to_id: Dict[Tuple[str, int], int] = {}
        self._initialized: bool = False

        if entries:
            self.initialize_from_manifest(entries)

    def initialize_from_manifest(
        self, entries: List[Union[ManifestEntry, dict]]
    ) -> None:
        """Build deterministic 1-indexed sequential mapping sorted by (condition_id, recording_number)."""
        def sort_key(item: Union[ManifestEntry, dict]):
            cid = str(item["condition_id"])
            # Try sorting condition_id numerically if possible (e.g. "1", "2", ... "25")
            try:
                cid_num = int(cid)
            except ValueError:
                cid_num = 999999
            rec_num = int(item["recording_number"])
            return (cid_num, cid, rec_num)

        sorted_entries = sorted(entries, key=sort_key)
        self._id_to_tuple.clear()
        self._tuple_to_id.clear()

        for idx, entry in enumerate(sorted_entries, start=1):
            cid = str(entry["condition_id"])
            rec_num = int(entry["recording_number"])
            self._id_to_tuple[idx] = (cid, rec_num)
            self._tuple_to_id[(cid, rec_num)] = idx

        self._initialized = True

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        # Try finding dataset
        candidates = [
            Path("dataset/Readngs_DAQ_Data"),
            Path(__file__).resolve().parent.parent / "dataset" / "Readngs_DAQ_Data",
        ]
        for path in candidates:
            if path.is_dir():
                try:
                    entries = discover_manifest(path)
                    if entries:
                        self.initialize_from_manifest(entries)
                        return
                except Exception:
                    pass

        # Fallback synthetic grid for 25 conditions x ~33 recordings
        synthetic_entries = []
        for c in range(1, 26):
            for r in range(1, 34):
                synthetic_entries.append({
                    "condition_id": str(c),
                    "recording_number": r,
                })
        self.initialize_from_manifest(synthetic_entries)

    def get_by_session_id(self, session_id: int) -> Optional[Tuple[str, int]]:
        self._ensure_initialized()
        return self._id_to_tuple.get(session_id)

    def get_session_id(self, condition_id: str, recording_number: int) -> Optional[int]:
        self._ensure_initialized()
        return self._tuple_to_id.get((str(condition_id), int(recording_number)))

    def total_sessions(self) -> int:
        self._ensure_initialized()
        return len(self._id_to_tuple)

    def resolve(self, text: str) -> Optional[SessionReference]:
        """Resolve a text query to a SessionReference if any session/recording pattern matches."""
        self._ensure_initialized()
        if not text:
            return None

        # 1. Check Condition + Recording combined pattern (e.g. "Condition 5 Recording 2")
        match = _COND_REC_REGEX.search(text)
        if match:
            cid, rec = match.group(1), int(match.group(2))
            sid = self.get_session_id(cid, rec)
            if sid is not None:
                return SessionReference(
                    session_id=sid,
                    condition_id=cid,
                    recording_number=rec,
                    matched_text=match.group(0),
                )

        # 2. Check "Recording 2 in Condition 5"
        match = _REC_IN_COND_REGEX.search(text)
        if match:
            rec, cid = int(match.group(1)), match.group(2)
            sid = self.get_session_id(cid, rec)
            if sid is not None:
                return SessionReference(
                    session_id=sid,
                    condition_id=cid,
                    recording_number=rec,
                    matched_text=match.group(0),
                )

        # 3. Check explicit Session ID ("session 42")
        match = _SESSION_NUM_REGEX.search(text)
        if match:
            sid = int(match.group(1))
            coords = self.get_by_session_id(sid)
            if coords is not None:
                return SessionReference(
                    session_id=sid,
                    condition_id=coords[0],
                    recording_number=coords[1],
                    matched_text=match.group(0),
                )
            elif 1 <= sid <= 1000:
                # Fallback even if exact coordinates not mapped
                return SessionReference(
                    session_id=sid,
                    condition_id=f"synth_{sid}",
                    recording_number=1,
                    matched_text=match.group(0),
                )

        return None


# Global registry instance
SESSION_REGISTRY = SessionIDRegistry()


def build_session_id_map(manifest: List[Union[ManifestEntry, dict]]) -> Dict[int, Tuple[str, int]]:
    """Build and return global session ID lookup dictionary."""
    reg = SessionIDRegistry(manifest)
    return dict(reg._id_to_tuple)


def resolve_session_reference(text: str) -> Optional[SessionReference]:
    """Convenience function to resolve a session reference from text."""
    return SESSION_REGISTRY.resolve(text)
