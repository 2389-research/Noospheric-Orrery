"""Repository pattern for database abstraction.

Supports SQLite (local dev) and Firestore (cloud deployment).
Switch via DB_BACKEND env var: 'sqlite' (default) or 'firestore'.
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
