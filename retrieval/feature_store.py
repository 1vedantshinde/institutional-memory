"""Numeric feature-vector similarity storage for DAQ signal windows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np

from core.schema import SignalWindow


class FeatureStoreError(ValueError):
    """Feature vectors cannot be stored or compared safely."""


@dataclass(frozen=True)
class FeatureSimilarityHit:
    window: SignalWindow
    score: float
    distance_metric: str


class FeatureStore:
    """In-memory feature store with an insert/similarity_search interface."""

    def __init__(self) -> None:
        self._windows: dict[str, SignalWindow] = {}

    def insert(self, windows: Iterable[SignalWindow]) -> None:
        """Insert windows carrying finite feature vectors, keyed by window ID."""
        for window in windows:
            self._validate_vector(window.feature_vector, window.window_id)
            self._windows[window.window_id] = window

    def similarity_search(
        self,
        query_vector: Sequence[float],
        *,
        top_k: int = 5,
        candidate_window_ids: set[str] | None = None,
        metric: str = "cosine",
    ) -> list[FeatureSimilarityHit]:
        """Rank feature vectors within optional metadata-filtered candidates.

        Cosine scores are sorted descending. Euclidean search returns the
        negative distance as score, likewise sorting the closest result first.
        """
        query = self._validate_vector(query_vector, "query")
        if top_k <= 0:
            raise FeatureStoreError("top_k_must_be_positive")
        if metric not in {"cosine", "euclidean"}:
            raise FeatureStoreError("unsupported_distance_metric")
        hits: list[FeatureSimilarityHit] = []
        for window_id, window in self._windows.items():
            if candidate_window_ids is not None and window_id not in candidate_window_ids:
                continue
            vector = self._validate_vector(window.feature_vector, window_id)
            if vector.shape != query.shape:
                raise FeatureStoreError(f"feature_vector_dimension_mismatch:{window_id}")
            if metric == "cosine":
                denominator = np.linalg.norm(query) * np.linalg.norm(vector)
                score = float(np.dot(query, vector) / denominator) if denominator else 0.0
            else:
                score = -float(np.linalg.norm(query - vector))
            hits.append(FeatureSimilarityHit(window, score, metric))
        return sorted(hits, key=lambda hit: (-hit.score, hit.window.window_id))[:top_k]

    @staticmethod
    def _validate_vector(vector: Sequence[float] | None, label: str) -> np.ndarray:
        if vector is None:
            raise FeatureStoreError(f"missing_feature_vector:{label}")
        array = np.asarray(vector, dtype=float)
        if array.ndim != 1 or array.size == 0 or not np.all(np.isfinite(array)):
            raise FeatureStoreError(f"invalid_feature_vector:{label}")
        return array
