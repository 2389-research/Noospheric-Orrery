"""Repository pattern for database abstraction.

Uses SQLite with WAL mode for concurrent read/write.
"""

from .interfaces import (
    DocumentRepository,
    ChunkRepository,
    DomainRepository,
    EntityRepository,
    EntitySourceRepository,
    RelationshipRepository,
    JobRepository,
    SpecRepository,
    NormalizationRepository,
    LayoutRepository,
    DataStore,
)

__all__ = [
    "DocumentRepository",
    "ChunkRepository",
    "DomainRepository",
    "EntityRepository",
    "EntitySourceRepository",
    "RelationshipRepository",
    "JobRepository",
    "SpecRepository",
    "NormalizationRepository",
    "LayoutRepository",
    "DataStore",
]
