from dataclasses import dataclass
from typing import Any, Callable, Literal, cast


type MetricType = Literal["COSINE", "L2", "EUCLIDEAN", "IP", "DOT", "MANHATTAN", "HAMMING"]
type VectorIndexAlgorithm = Literal["AUTOINDEX", "FLAT", "HNSW"]


_VALID_METRIC_TYPES = frozenset({"COSINE", "L2", "EUCLIDEAN", "IP", "DOT", "MANHATTAN", "HAMMING"})
_VALID_VECTOR_INDEX_ALGORITHMS = frozenset({"AUTOINDEX", "FLAT", "HNSW"})


@dataclass(frozen=True, slots=True)
class VectorIndex:
    """Declarative vector-index metadata attached to one vector field.

    `algorithm` is the backend-native index algorithm currently supported by the
    storage layer:
    - `AUTOINDEX` for Milvus
    - `FLAT` or `HNSW` for Redis vector search
    """

    dim: int
    metric_type: MetricType | None = None
    embedder: Callable[..., Any] | None = None
    algorithm: VectorIndexAlgorithm | None = None

    def __post_init__(self) -> None:
        dim = int(self.dim)
        if dim <= 0:
            raise ValueError(f"VectorIndex.dim must be > 0, got {self.dim!r}.")
        object.__setattr__(self, "dim", dim)

        if self.metric_type is not None:
            metric_type = str(self.metric_type).upper()
            if metric_type not in _VALID_METRIC_TYPES:
                raise ValueError(
                    f"VectorIndex.metric_type must be one of {sorted(_VALID_METRIC_TYPES)}, got {self.metric_type!r}."
                )
            object.__setattr__(self, "metric_type", cast(MetricType, metric_type))

        if self.algorithm is not None:
            algorithm = str(self.algorithm).upper()
            if algorithm not in _VALID_VECTOR_INDEX_ALGORITHMS:
                raise ValueError(
                    f"VectorIndex.algorithm must be one of {sorted(_VALID_VECTOR_INDEX_ALGORITHMS)}, got {self.algorithm!r}."
                )
            object.__setattr__(self, "algorithm", cast(VectorIndexAlgorithm, algorithm))


def coerce_vector_index(index: VectorIndex | Literal[False] | None) -> VectorIndex | Literal[False] | None:
    """Validate the `index=` payload used by the storage vector field API."""

    if index is None or index is False or isinstance(index, VectorIndex):
        return index
    raise TypeError(f"Vector field `index` must be VectorIndex | False | None, got {type(index).__name__}.")


__all__ = [
    "MetricType",
    "VectorIndexAlgorithm",
    "VectorIndex",
    "coerce_vector_index",
]