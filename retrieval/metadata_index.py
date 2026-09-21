"""Exact structured lookup for DAQ signal-window metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from core.schema import Condition, Recording, SignalWindow


METADATA_FILTER_FIELDS = {"condition_id", "S", "F", "D", "recording_id", "channel"}


class MetadataFilterError(ValueError):
    """A query asks for unsupported or inconsistent DAQ metadata."""


@dataclass(frozen=True)
class IndexedWindow:
    """A window joined to its experimental condition and source recording."""

    window: SignalWindow
    recording: Recording
    condition: Condition


class MetadataIndex:
    """Exact-match index; this intentionally performs no lexical search."""

    def __init__(
        self,
        conditions: Iterable[Condition],
        recordings: Iterable[Recording],
        windows: Iterable[SignalWindow],
    ) -> None:
        self._conditions = {condition.condition_id: condition for condition in conditions}
        self._recordings = {recording.recording_id: recording for recording in recordings}
        self._windows: dict[str, IndexedWindow] = {}
        for window in windows:
            recording = self._recordings.get(window.recording_id)
            if recording is None:
                raise MetadataFilterError(f"window_references_unknown_recording:{window.recording_id}")
            condition = self._conditions.get(recording.condition_id)
            if condition is None:
                raise MetadataFilterError(
                    f"recording_references_unknown_condition:{recording.condition_id}"
                )
            self._windows[window.window_id] = IndexedWindow(window, recording, condition)

    def get(self, window_id: str) -> IndexedWindow:
        return self._windows[window_id]

    def filter(self, **filters: object) -> list[IndexedWindow]:
        """Return canonical windows matching every supplied exact field/value."""
        unsupported = set(filters) - METADATA_FILTER_FIELDS
        if unsupported:
            raise MetadataFilterError(f"unsupported_metadata_filters:{','.join(sorted(unsupported))}")
        matches: list[IndexedWindow] = []
        for indexed in self._windows.values():
            if indexed.recording.schema_status != "canonical":
                continue
            values = {
                "condition_id": indexed.condition.condition_id,
                "S": indexed.condition.S,
                "F": indexed.condition.F,
                "D": indexed.condition.D,
                "recording_id": indexed.recording.recording_id,
                "channel": indexed.window.channel,
            }
            if all(values[key] == value for key, value in filters.items()):
                matches.append(indexed)
        return sorted(matches, key=lambda item: item.window.window_id)
