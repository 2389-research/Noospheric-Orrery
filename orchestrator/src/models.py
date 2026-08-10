from pydantic import BaseModel
from datetime import datetime

class DocumentSummary(BaseModel):
    id: str
    title: str
    status: str
    created_at: datetime
    domains: list[str] = []
    entity_count: int = 0

class DocumentDetail(BaseModel):
    id: str
    title: str
    source_path: str | None
    content: str
    metadata: dict | None
    status: str
    created_at: datetime
    domains: list[dict] = []
    entities: list[dict] = []

class DomainInfo(BaseModel):
    id: str
    path: str
    parent_path: str | None
    document_count: int
    spec_version: int | None
    children: list["DomainInfo"] = []

class EntitySummary(BaseModel):
    id: str
    canonical_name: str
    type: str
    source_count: int = 0
    domains: list[str] = []

class EntityDetail(BaseModel):
    id: str
    canonical_name: str
    type: str
    created_at: datetime
    sources: list[dict] = []
    merge_history: list[str] = []

class JobInfo(BaseModel):
    id: str
    type: str
    target: str
    status: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

class Stats(BaseModel):
    document_count: int
    entity_count: int
    domain_count: int
    active_jobs: int
    image_count: int = 0

class IngestResult(BaseModel):
    document_id: str
    title: str
    domains: list[str]
    entity_count: int
    jobs_queued: list[str]
    content_type: str = "text"

class DirectoryIngestRequest(BaseModel):
    path: str


class RepoIngestRequest(BaseModel):
    """A git checkout to summarize into a collection of code_intent documents.

    `path` is a server-side directory, not an upload: the repo is read where it sits
    and only the SUMMARIES are stored (the graph is a map over the code, not a copy
    of it). `name` becomes the collection's name and its unique `path` key.
    """
    path: str
    name: str
