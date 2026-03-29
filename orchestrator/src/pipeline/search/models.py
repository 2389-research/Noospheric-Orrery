from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ScoredEntity:
    entity_id: str
    name: str
    entity_type: str
    score: float
    rank: int
    source: str  # "semantic", "exact", "entity_boost"
    source_count: int = 0


@dataclass
class ScoredChunk:
    chunk_id: str
    text: str
    document_id: str
    document_title: str
    score: float
    rank: int
    source: str  # "semantic", "entity_boost"
    entity_overlap: int = 0
    matching_entities: str = ""


@dataclass
class SubQueryResults:
    query: str
    semantic_entities: list[ScoredEntity] = field(default_factory=list)
    semantic_chunks: list[ScoredChunk] = field(default_factory=list)
    exact_entities: list[ScoredEntity] = field(default_factory=list)
    boosted_chunks: list[ScoredChunk] = field(default_factory=list)


@dataclass
class SearchResponse:
    query: str
    entities: list[dict]
    chunks: list[dict]
    sub_queries_used: list[str]
    total_entities: int
    total_chunks: int
