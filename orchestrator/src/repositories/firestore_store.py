from __future__ import annotations
"""Firestore implementation of the DataStore repositories.

Uses Firebase Admin SDK to read/write Firestore collections.
Follows the schema from docs/firebase-migration-spec.md.

Collection structure:
  workspaces/{workspaceId}/documents/{docId}
  workspaces/{workspaceId}/domains/{domainPath}
  workspaces/{workspaceId}/entities/{entityId}
  ...

For now, uses a single default workspace until multi-tenancy is added.
"""

import json
import uuid
from datetime import datetime
from google.cloud import firestore

from .interfaces import (
    DataStore,
    DocumentRepository, ChunkRepository, DomainRepository,
    EntityRepository, EntitySourceRepository, RelationshipRepository,
    JobRepository, SpecRepository, NormalizationRepository,
    LayoutRepository, SimmerIterationRepository,
    Document, Chunk, Domain, Entity, EntitySource, Relationship,
    Job, Spec, SimmerIteration, NormalizationReview, DomainAssignment, CoEntity,
)


def _safe_doc_id(name: str) -> str:
    """Sanitize a string for use as a Firestore document ID.

    Firestore doc IDs cannot contain '/', or be '.' or '..'.
    Also avoid leading/trailing whitespace.
    """
    safe = name.strip().replace("/", "__SLASH__")
    if safe in (".", ".."):
        safe = f"__{safe}__"
    return safe or "__empty__"


def _encode_path(path: str) -> str:
    """Encode domain path for use as Firestore doc ID (/ not allowed)."""
    return path.replace("/", "__")


def _decode_path(encoded: str) -> str:
    """Decode Firestore doc ID back to domain path."""
    return encoded.replace("__", "/")


class FirestoreDocumentRepository(DocumentRepository):
    def __init__(self, db: firestore.Client, workspace_id: str):
        self._col = db.collection("workspaces").document(workspace_id).collection("documents")

    def count(self):
        results = self._col.count().get()
        return int(results[0][0].value) if results else 0

    def create(self, id, title, content, content_hash, source_path=None,
               content_type="text", image_path=None, thumbnail_path=None):
        doc = {
            "title": title,
            "content": content,
            "contentHash": content_hash,
            "sourcePath": source_path,
            "contentType": content_type,
            "status": "pending",
            "createdAt": firestore.SERVER_TIMESTAMP,
        }
        if image_path:
            doc["imagePath"] = image_path
        if thumbnail_path:
            doc["thumbnailPath"] = thumbnail_path
        self._col.document(id).set(doc)
        return id

    def get(self, doc_id):
        doc = self._col.document(doc_id).get()
        if not doc.exists:
            return None
        d = doc.to_dict()
        return Document(
            id=doc.id, title=d.get("title", ""), content=d.get("content"),
            content_hash=d.get("contentHash"), source_path=d.get("sourcePath"),
            status=d.get("status", "pending"),
            created_at=str(d.get("createdAt", "")),
            content_type=d.get("contentType", "text"),
            image_path=d.get("imagePath"),
            thumbnail_path=d.get("thumbnailPath"),
        )

    def list(self, limit=50, offset=0):
        query = self._col.order_by("createdAt", direction=firestore.Query.DESCENDING).limit(limit).offset(offset)
        docs = []
        for doc in query.stream():
            d = doc.to_dict()
            result = Document(id=doc.id, title=d.get("title", ""), status=d.get("status", ""),
                              created_at=str(d.get("createdAt", "")),
                              content_type=d.get("contentType", "text"),
                              image_path=d.get("imagePath"),
                              thumbnail_path=d.get("thumbnailPath"))
            # Get domains subcollection
            domain_docs = self._col.document(doc.id).collection("domains").stream()
            result.domains = [dd.id.replace("__", "/") for dd in domain_docs]
            docs.append(result)
        return docs

    def get_by_hash(self, content_hash):
        results = self._col.where("contentHash", "==", content_hash).limit(1).stream()
        for doc in results:
            return Document(id=doc.id, title=doc.to_dict().get("title", ""))
        return None

    def update_status(self, doc_id, status):
        self._col.document(doc_id).update({"status": status})

    def update_content(self, doc_id, content):
        self._col.document(doc_id).update({"content": content})

    def get_for_domain(self, domain_path, status_filter=None):
        # Query documents that have this domain in their domains subcollection
        # This requires a different approach in Firestore — use collection group query
        # For now, iterate domains collection
        docs = []
        domain_col = self._col.parent.collection("document_domains")
        results = domain_col.where("domainPath", "==", domain_path).stream()
        doc_ids = [r.to_dict()["documentId"] for r in results]
        for doc_id in doc_ids:
            doc = self.get(doc_id)
            if doc and (not status_filter or doc.status in status_filter):
                docs.append(doc)
        return docs

    def get_recent(self, limit=50):
        return self.list(limit=limit)

    def get_sample(self, limit=10, status_filter=None):
        query = self._col
        if status_filter:
            query = query.where("status", "in", status_filter)
        query = query.limit(limit)
        docs = []
        for doc in query.stream():
            d = doc.to_dict()
            docs.append(Document(id=doc.id, title=d.get("title", ""),
                                  content=d.get("content"), status=d.get("status", "")))
        return docs


class FirestoreChunkRepository(ChunkRepository):
    def __init__(self, db, workspace_id):
        self._db = db
        self._ws = workspace_id
        self._col = db.collection("workspaces").document(workspace_id).collection("chunks")

    def create_batch(self, chunks):
        batch = self._db.batch()
        for c in chunks:
            ref = self._col.document(c.id)
            batch.set(ref, {
                "documentId": c.document_id,
                "chunkIndex": c.chunk_index,
                "text": c.text,
                "offset": c.offset,
                "length": c.length,
            })
        batch.commit()

    def get_for_document(self, doc_id):
        results = self._col.where("documentId", "==", doc_id).order_by("chunkIndex").stream()
        return [Chunk(id=doc.id, document_id=doc.to_dict()["documentId"],
                       chunk_index=doc.to_dict()["chunkIndex"], text=doc.to_dict()["text"],
                       offset=doc.to_dict().get("offset", 0),
                       length=doc.to_dict().get("length", 0)) for doc in results]

    def get_all_with_embeddings(self):
        results = self._col.stream()
        return [Chunk(id=doc.id, document_id=doc.to_dict()["documentId"],
                       chunk_index=doc.to_dict()["chunkIndex"], text=doc.to_dict()["text"],
                       embedding=doc.to_dict().get("embedding")) for doc in results]

    def update_embedding(self, chunk_id, embedding):
        self._col.document(chunk_id).update({"embedding": embedding})

    def update_text(self, chunk_id, text):
        self._col.document(chunk_id).update({"text": text, "length": len(text)})


class FirestoreDomainRepository(DomainRepository):
    def __init__(self, db, workspace_id):
        self._db = db
        self._ws = workspace_id
        self._col = db.collection("workspaces").document(workspace_id).collection("domains")

    def create(self, id, path, parent_path=None):
        self._col.document(_encode_path(path)).set({
            "id": id,
            "path": path,
            "parentPath": parent_path,
            "documentCount": 0,
            "specVersion": None,
            "createdAt": firestore.SERVER_TIMESTAMP,
        })

    def get(self, path):
        doc = self._col.document(_encode_path(path)).get()
        if not doc.exists:
            return None
        d = doc.to_dict()
        return Domain(id=d.get("id", doc.id), path=d["path"],
                      parent_path=d.get("parentPath"),
                      document_count=d.get("documentCount", 0),
                      spec_version=d.get("specVersion"),
                      created_at=str(d.get("createdAt", "")))

    def get_by_id(self, domain_id):
        results = self._col.where("id", "==", domain_id).limit(1).stream()
        for doc in results:
            d = doc.to_dict()
            return Domain(id=d.get("id"), path=d["path"],
                          parent_path=d.get("parentPath"),
                          document_count=d.get("documentCount", 0),
                          spec_version=d.get("specVersion"))
        return None

    def list(self, min_doc_count=0):
        # Fetch all, filter + sort client-side to avoid composite index requirement
        domains = []
        for doc in self._col.stream():
            d = doc.to_dict()
            doc_count = d.get("documentCount", 0)
            if doc_count >= min_doc_count:
                domains.append(Domain(
                    id=d.get("id", doc.id), path=d["path"],
                    parent_path=d.get("parentPath"),
                    document_count=doc_count,
                    spec_version=d.get("specVersion"),
                    created_at=str(d.get("createdAt", "")),
                ))
        domains.sort(key=lambda d: d.path)
        return domains

    def get_all_paths(self):
        return [_decode_path(doc.id) for doc in self._col.stream()]

    def increment_doc_count(self, path):
        self._col.document(_encode_path(path)).update({
            "documentCount": firestore.Increment(1)
        })

    def update_spec_version(self, path, version):
        self._col.document(_encode_path(path)).update({"specVersion": version})

    def get_merge_target(self, label):
        merge_col = self._db.collection("workspaces").document(self._ws).collection("domainMergeMap")
        doc = merge_col.document(label.lower().strip()).get()
        if doc.exists:
            return doc.to_dict().get("toPath")
        return None

    def assign_document(self, doc_id, domain_path, is_primary, confidence):
        dd_col = self._db.collection("workspaces").document(self._ws).collection("documentDomains")
        dd_col.document(f"{doc_id}__{_encode_path(domain_path)}").set({
            "documentId": doc_id,
            "domainPath": domain_path,
            "isPrimary": is_primary,
            "confidence": confidence,
        })

    def get_domains_for_document(self, doc_id):
        dd_col = self._db.collection("workspaces").document(self._ws).collection("documentDomains")
        results = dd_col.where("documentId", "==", doc_id).stream()
        return [DomainAssignment(
            document_id=doc_id, domain_path=d.to_dict()["domainPath"],
            is_primary=d.to_dict().get("isPrimary", False),
            confidence=d.to_dict().get("confidence", 0)
        ) for d in results]

    def get_entity_domain_weights(self, entity_id):
        # This requires joining entity_sources with document_domains
        # Complex query — will need denormalization or multiple reads
        # For now, read entity sources, then look up their domains
        es_col = self._db.collection("workspaces").document(self._ws).collection("entitySources")
        dd_col = self._db.collection("workspaces").document(self._ws).collection("documentDomains")

        sources = es_col.where("entityId", "==", entity_id).stream()
        domain_counts = {}
        for s in sources:
            doc_id = s.to_dict()["documentId"]
            domains = dd_col.where("documentId", "==", doc_id).stream()
            for d in domains:
                path = d.to_dict()["domainPath"]
                domain_counts[path] = domain_counts.get(path, 0) + 1

        total = sum(domain_counts.values())
        if total == 0:
            return {}
        return {path: round(count / total, 3) for path, count in domain_counts.items()}


class FirestoreEntityRepository(EntityRepository):
    def __init__(self, db, workspace_id):
        self._db = db
        self._ws = workspace_id
        self._col = db.collection("workspaces").document(workspace_id).collection("entities")

    def count(self):
        results = self._col.count().get()
        return int(results[0][0].value) if results else 0

    def create(self, id, name, type):
        self._col.document(id).set({
            "canonicalName": name,
            "type": type,
            "sourceCount": 0,
            "createdAt": firestore.SERVER_TIMESTAMP,
        })
        return id

    def get(self, entity_id):
        doc = self._col.document(entity_id).get()
        if not doc.exists:
            return None
        d = doc.to_dict()
        return Entity(id=doc.id, canonical_name=d["canonicalName"], type=d["type"],
                      source_count=d.get("sourceCount", 0),
                      created_at=str(d.get("createdAt", "")))

    def get_by_name(self, name, type):
        results = self._col.where("canonicalName", "==", name).where("type", "==", type).limit(1).stream()
        for doc in results:
            d = doc.to_dict()
            return Entity(id=doc.id, canonical_name=d["canonicalName"], type=d["type"])
        return None

    def list(self, limit=50, offset=0, type_filter=None, domain_filter=None, job_id=None):
        query = self._col.order_by("sourceCount", direction=firestore.Query.DESCENDING)
        if type_filter:
            query = query.where("type", "==", type_filter)
        query = query.limit(limit).offset(offset)
        return [Entity(id=doc.id, canonical_name=doc.to_dict()["canonicalName"],
                        type=doc.to_dict()["type"],
                        source_count=doc.to_dict().get("sourceCount", 0))
                for doc in query.stream()]

    def delete(self, entity_id):
        self._col.document(entity_id).delete()

    def update_embedding(self, entity_id, embedding):
        self._col.document(entity_id).update({"embedding": embedding})

    def get_all_for_normalization(self):
        results = self._col.order_by("canonicalName").stream()
        return [Entity(id=doc.id, canonical_name=doc.to_dict()["canonicalName"],
                        type=doc.to_dict()["type"]) for doc in results]

    def get_for_document(self, doc_id):
        es_col = self._db.collection("workspaces").document(self._ws).collection("entitySources")
        sources = es_col.where("documentId", "==", doc_id).stream()
        entity_ids = list(set(s.to_dict()["entityId"] for s in sources))
        entities = []
        for eid in entity_ids[:50]:  # cap for performance
            e = self.get(eid)
            if e:
                entities.append(e)
        entities.sort(key=lambda e: e.source_count, reverse=True)
        return entities

    def get_for_domain(self, domain_path, limit=12):
        # Complex query — would need denormalization
        # For now, return empty
        return []


class FirestoreEntitySourceRepository(EntitySourceRepository):
    def __init__(self, db, workspace_id):
        self._db = db
        self._ws = workspace_id
        self._col = db.collection("workspaces").document(workspace_id).collection("entitySources")

    def create(self, entity_id, document_id, chunk_id=None, extraction_pass=None,
               spec_version=None, job_id=None):
        self._col.add({
            "entityId": entity_id,
            "documentId": document_id,
            "chunkId": chunk_id,
            "extractionPass": extraction_pass,
            "specVersion": spec_version,
            "jobId": job_id,
        })
        # Increment source count on entity
        ent_col = self._db.collection("workspaces").document(self._ws).collection("entities")
        ent_col.document(entity_id).update({"sourceCount": firestore.Increment(1)})

    def get_for_entity(self, entity_id):
        results = self._col.where("entityId", "==", entity_id).stream()
        return [EntitySource(
            entity_id=entity_id, document_id=d.to_dict()["documentId"],
            chunk_id=d.to_dict().get("chunkId"),
            extraction_pass=d.to_dict().get("extractionPass"),
            spec_version=d.to_dict().get("specVersion"),
            job_id=d.to_dict().get("jobId")
        ) for d in results]

    def get_source_count(self, entity_id):
        ent = self._db.collection("workspaces").document(self._ws).collection("entities").document(entity_id).get()
        if ent.exists:
            return ent.to_dict().get("sourceCount", 0)
        return 0

    def update_entity_id(self, from_id, to_id):
        results = self._col.where("entityId", "==", from_id).stream()
        batch = self._db.batch()
        for doc in results:
            batch.update(doc.reference, {"entityId": to_id})
        batch.commit()

    def get_shared_documents(self, entity_id, doc_ids):
        if not doc_ids:
            return {}
        results = self._col.where("entityId", "==", entity_id).stream()
        doc_id_set = set(doc_ids)
        shared = {}
        for s in results:
            did = s.to_dict()["documentId"]
            if did in doc_id_set:
                shared.setdefault(entity_id, []).append(did)
        return shared

    def get_documents_for_entity(self, entity_id):
        results = self._col.where("entityId", "==", entity_id).stream()
        doc_ids = list(set(s.to_dict()["documentId"] for s in results))
        doc_col = self._db.collection("workspaces").document(self._ws).collection("documents")
        docs = []
        for did in doc_ids:
            doc = doc_col.document(did).get()
            if doc.exists:
                docs.append({"id": doc.id, "title": doc.to_dict().get("title", "")})
        return docs


class FirestoreJobRepository(JobRepository):
    def __init__(self, db, workspace_id):
        self._col = db.collection("workspaces").document(workspace_id).collection("jobs")

    def count_active(self):
        count = 0
        for status in ["queued", "running"]:
            results = self._col.where("status", "==", status).stream()
            count += sum(1 for _ in results)
        return count

    def create(self, id, type, target, config=None):
        self._col.document(id).set({
            "type": type, "target": target, "status": "queued",
            "config": config, "result": None,
            "createdAt": firestore.SERVER_TIMESTAMP,
            "startedAt": None, "completedAt": None,
        })

    def get(self, job_id):
        doc = self._col.document(job_id).get()
        if not doc.exists:
            return None
        d = doc.to_dict()
        return Job(id=doc.id, type=d["type"], target=d["target"], status=d["status"],
                   config=d.get("config"), result=d.get("result"),
                   created_at=str(d.get("createdAt", "")),
                   started_at=str(d.get("startedAt", "")) if d.get("startedAt") else None,
                   completed_at=str(d.get("completedAt", "")) if d.get("completedAt") else None)

    def list(self, status_filter=None):
        # Avoid composite index — filter + sort client-side
        query = self._col
        if status_filter:
            query = query.where("status", "==", status_filter)
        jobs = []
        for doc in query.stream():
            d = doc.to_dict()
            jobs.append(Job(
                id=doc.id, type=d["type"], target=d["target"], status=d["status"],
                config=d.get("config"), result=d.get("result"),
                created_at=str(d.get("createdAt", "")),
                started_at=str(d.get("startedAt", "")) if d.get("startedAt") else None,
                completed_at=str(d.get("completedAt", "")) if d.get("completedAt") else None,
            ))
        jobs.sort(key=lambda j: j.created_at or "", reverse=True)
        return jobs

    def get_existing(self, type, target, statuses):
        for status in statuses:
            results = self._col.where("type", "==", type).where("target", "==", target).where("status", "==", status).limit(1).stream()
            for doc in results:
                return Job(id=doc.id, type=type, target=target, status=status)
        return None

    def pick_next(self):
        results = list(self._col.where("status", "==", "queued").stream())
        if not results:
            return None
        # Sort by createdAt client-side
        results.sort(key=lambda d: str(d.to_dict().get("createdAt", "")))
        doc = results[0]
        d = doc.to_dict()
        return Job(id=doc.id, type=d["type"], target=d["target"], status="queued",
                   config=d.get("config"))

    def mark_running(self, job_id):
        self._col.document(job_id).update({
            "status": "running", "startedAt": firestore.SERVER_TIMESTAMP
        })

    def mark_completed(self, job_id, result=None):
        self._col.document(job_id).update({
            "status": "completed", "completedAt": firestore.SERVER_TIMESTAMP,
            "result": result,
        })

    def mark_failed(self, job_id, error):
        self._col.document(job_id).update({
            "status": "failed", "completedAt": firestore.SERVER_TIMESTAMP,
            "result": {"error": error},
        })


# Placeholder implementations for less-used repos
class FirestoreRelationshipRepository(RelationshipRepository):
    def __init__(self, db, workspace_id):
        self._db = db
        self._ws = workspace_id
        self._col = db.collection("workspaces").document(workspace_id).collection("relationships")

    def upsert_cooccurrence(self, id, from_entity, to_entity, weight, source_chunk=None):
        self._col.document(id).set({
            "fromEntity": from_entity, "toEntity": to_entity,
            "type": "co_occurs", "weight": weight, "sourceChunk": source_chunk,
        })

    def get_cooccurrences(self, entity_id, limit=10):
        # Query both directions — supports both old (fromEntity/toEntity) and new (entityA/entityB) schemas
        results = []
        for field, other_field in [("entityA", "entityB"), ("entityB", "entityA"),
                                    ("fromEntity", "toEntity"), ("toEntity", "fromEntity")]:
            try:
                for doc in self._col.where(field, "==", entity_id).stream():
                    d = doc.to_dict()
                    other_id = d.get(other_field)
                    if not other_id:
                        continue
                    ent = self._db.collection("workspaces").document(self._ws).collection("entities").document(other_id).get()
                    if ent.exists:
                        ed = ent.to_dict()
                        results.append(CoEntity(id=other_id, canonical_name=ed["canonicalName"],
                                                 type=ed["type"], weight=d.get("weight", 1)))
            except Exception:
                continue
        # Dedupe and sort
        seen = set()
        deduped = []
        for r in sorted(results, key=lambda x: x.weight, reverse=True):
            if r.id not in seen:
                seen.add(r.id)
                deduped.append(r)
        return deduped[:limit]

    def get_trade_routes(self):
        # Compute trade routes by finding domains that share entities
        # This is expensive in Firestore — iterate all relationships
        domain_pairs = {}
        dd_col = self._db.collection("workspaces").document(self._ws).collection("documentDomains")
        es_col = self._db.collection("workspaces").document(self._ws).collection("entitySources")

        # Group entity sources by entity
        entity_docs = {}
        for s in es_col.stream():
            d = s.to_dict()
            entity_docs.setdefault(d["entityId"], set()).add(d["documentId"])

        # For each entity that appears in multiple docs, find domain pairs
        doc_domains_cache = {}
        for entity_id, doc_ids in entity_docs.items():
            if len(doc_ids) < 2:
                continue
            # Get domains for each doc
            for did in doc_ids:
                if did not in doc_domains_cache:
                    domains = dd_col.where("documentId", "==", did).stream()
                    doc_domains_cache[did] = [d.to_dict()["domainPath"] for d in domains]

            # Count pairs
            doc_list = list(doc_ids)
            for i in range(len(doc_list)):
                for j in range(i + 1, len(doc_list)):
                    for d1 in doc_domains_cache.get(doc_list[i], []):
                        for d2 in doc_domains_cache.get(doc_list[j], []):
                            if d1 != d2:
                                key = tuple(sorted([d1, d2]))
                                domain_pairs[key] = domain_pairs.get(key, 0) + 1

        return [{"source": k[0], "target": k[1], "weight": v} for k, v in domain_pairs.items()]

    def get_star_graph(self, entity_id, co_limit=30):
        # Complex query — simplified version
        ent_col = self._db.collection("workspaces").document(self._ws).collection("entities")
        entity = ent_col.document(entity_id).get()
        if not entity.exists:
            return None
        ed = entity.to_dict()

        # Get documents
        es_col = self._db.collection("workspaces").document(self._ws).collection("entitySources")
        sources = es_col.where("entityId", "==", entity_id).stream()
        doc_ids = list(set(s.to_dict()["documentId"] for s in sources))
        doc_col = self._db.collection("workspaces").document(self._ws).collection("documents")
        documents = []
        for did in doc_ids:
            doc = doc_col.document(did).get()
            if doc.exists:
                documents.append({"id": doc.id, "title": doc.to_dict().get("title", "")})

        # Get co-entities
        co_entities_raw = self.get_cooccurrences(entity_id, limit=co_limit)
        co_entities = []
        for co in co_entities_raw:
            # Find shared docs
            co_sources = es_col.where("entityId", "==", co.id).stream()
            co_doc_ids = set(s.to_dict()["documentId"] for s in co_sources)
            shared = list(co_doc_ids & set(doc_ids))
            co_entities.append({
                "id": co.id, "canonical_name": co.canonical_name,
                "type": co.type, "weight": co.weight,
                "shared_doc_ids": shared,
            })

        return {
            "entity": {"id": entity_id, "canonical_name": ed["canonicalName"],
                        "type": ed["type"], "source_count": len(doc_ids)},
            "documents": documents,
            "co_entities": co_entities,
        }

    def update_entity_references(self, from_id, to_id):
        for field in ["fromEntity", "toEntity"]:
            for doc in self._col.where(field, "==", from_id).stream():
                doc.reference.update({field: to_id})


class FirestoreSpecRepository(SpecRepository):
    def __init__(self, db, workspace_id):
        self._col = db.collection("workspaces").document(workspace_id).collection("specs")

    def create(self, id, domain_path, version, content, golden_set=None, score=None):
        self._col.document(id).set({
            "domainPath": domain_path, "version": version,
            "specContent": content, "goldenSet": golden_set, "score": score,
            "createdAt": firestore.SERVER_TIMESTAMP,
        })

    def get_general(self, media_type="text"):
        # Client-side sort and filter to avoid composite index
        results = list(self._col.where("domainPath", "==", None).stream())
        if not results:
            return None
        # Filter by media type
        filtered = [r for r in results if r.to_dict().get("mediaType", "text") == media_type]
        if not filtered:
            # Fall back to any general spec (backwards compat)
            filtered = [r for r in results if not r.to_dict().get("mediaType")]
        if not filtered:
            return None
        filtered.sort(key=lambda d: d.to_dict().get("version", 0), reverse=True)
        d = filtered[0].to_dict()
        return Spec(id=filtered[0].id, domain_path=None, version=d["version"],
                    spec_content=d["specContent"], golden_set=d.get("goldenSet"), score=d.get("score"))

    def get_for_domain(self, domain_path):
        results = list(self._col.where("domainPath", "==", domain_path).stream())
        if not results:
            return None
        results.sort(key=lambda d: d.to_dict().get("version", 0), reverse=True)
        d = results[0].to_dict()
        return Spec(id=results[0].id, domain_path=domain_path, version=d["version"],
                    spec_content=d["specContent"], golden_set=d.get("goldenSet"), score=d.get("score"))

    def get_latest_version(self, domain_path):
        results = list(self._col.where("domainPath", "==", domain_path).stream())
        if not results:
            return 0
        return max(d.to_dict().get("version", 0) for d in results)


class FirestoreNormalizationRepository(NormalizationRepository):
    def __init__(self, db, workspace_id):
        self._db = db
        self._ws = workspace_id
        self._review_col = db.collection("workspaces").document(workspace_id).collection("normalizationQueue")
        self._log_col = db.collection("workspaces").document(workspace_id).collection("normalizationLog")
        self._merge_col = db.collection("workspaces").document(workspace_id).collection("mergeMap")

    def get_review_by_id(self, review_id):
        doc = self._review_col.document(review_id).get()
        if not doc.exists:
            return None
        d = doc.to_dict()
        return NormalizationReview(
            id=doc.id, entity_a_id=d["entityAId"], entity_a_name=d["entityAName"],
            entity_b_id=d["entityBId"], entity_b_name=d["entityBName"],
            similarity=d["similarity"], status=d.get("status", "pending"),
            resolution=d.get("resolution"),
        )

    def get_existing_review(self, entity_a_id, entity_b_id):
        for doc in self._review_col.where("entityAId", "==", entity_a_id).where("entityBId", "==", entity_b_id).stream():
            d = doc.to_dict()
            return NormalizationReview(id=doc.id, entity_a_id=d["entityAId"], entity_a_name=d["entityAName"],
                                       entity_b_id=d["entityBId"], entity_b_name=d["entityBName"],
                                       similarity=d["similarity"], status=d.get("status", "pending"))
        # Check reverse
        for doc in self._review_col.where("entityAId", "==", entity_b_id).where("entityBId", "==", entity_a_id).stream():
            d = doc.to_dict()
            return NormalizationReview(id=doc.id, entity_a_id=d["entityAId"], entity_a_name=d["entityAName"],
                                       entity_b_id=d["entityBId"], entity_b_name=d["entityBName"],
                                       similarity=d["similarity"], status=d.get("status", "pending"))
        return None

    def create_review(self, id, entity_a_id, entity_a_name, entity_b_id, entity_b_name, similarity):
        self._review_col.document(id).set({
            "entityAId": entity_a_id, "entityAName": entity_a_name,
            "entityBId": entity_b_id, "entityBName": entity_b_name,
            "similarity": similarity, "status": "pending", "resolution": None,
        })

    def get_review_queue(self):
        results = self._review_col.where("status", "==", "pending").stream()
        reviews = [NormalizationReview(id=doc.id, entity_a_id=doc.to_dict()["entityAId"],
                                        entity_a_name=doc.to_dict()["entityAName"],
                                        entity_b_id=doc.to_dict()["entityBId"],
                                        entity_b_name=doc.to_dict()["entityBName"],
                                        similarity=doc.to_dict()["similarity"],
                                        status="pending") for doc in results]
        reviews.sort(key=lambda r: r.similarity, reverse=True)
        return reviews

    def resolve_review(self, review_id, action):
        self._review_col.document(review_id).update({"status": "resolved", "resolution": action})

    def create_merge_log(self, id, from_id, from_name, to_id, to_name, method, similarity):
        self._log_col.document(id).set({
            "fromEntityId": from_id, "fromName": from_name,
            "toEntityId": to_id, "toName": to_name,
            "method": method, "similarity": similarity,
            "createdAt": firestore.SERVER_TIMESTAMP,
        })

    def get_merge_summary(self):
        logs = list(self._log_col.stream())
        by_method = {}
        for doc in logs:
            m = doc.to_dict().get("method", "unknown")
            by_method[m] = by_method.get(m, 0) + 1
        pending = sum(1 for _ in self._review_col.where("status", "==", "pending").stream())
        recent = sorted(logs, key=lambda d: str(d.to_dict().get("createdAt", "")), reverse=True)[:10]
        return {
            "merges_by_method": by_method,
            "total_merges": len(logs),
            "pending_reviews": pending,
            "recent_merges": [{"from": d.to_dict()["fromName"], "to": d.to_dict()["toName"],
                                "method": d.to_dict()["method"], "similarity": d.to_dict()["similarity"],
                                "date": str(d.to_dict().get("createdAt", ""))} for d in recent],
        }

    def get_merge_map_entry(self, name):
        doc = self._merge_col.document(_safe_doc_id(name)).get()
        if doc.exists:
            return doc.to_dict().get("toEntityId")
        return None

    def create_merge_map_entry(self, from_name, to_entity_id):
        self._merge_col.document(_safe_doc_id(from_name)).set({"toEntityId": to_entity_id})

    def get_merge_history(self, entity_id):
        results = self._merge_col.where("toEntityId", "==", entity_id).stream()
        return [doc.id for doc in results]


class FirestoreLayoutRepository(LayoutRepository):
    def __init__(self, db, workspace_id):
        self._col = db.collection("workspaces").document(workspace_id).collection("domainLayout")
        self._model_doc = db.collection("workspaces").document(workspace_id).collection("layoutModel").document("umap")

    def get_stored_positions(self):
        positions = {}
        for doc in self._col.stream():
            d = doc.to_dict()
            positions[_decode_path(doc.id)] = {"x": d["x"], "y": d["y"]}
        return positions

    def store_position(self, domain_path, x, y, embedding=None):
        data = {"x": x, "y": y}
        if embedding:
            data["embedding"] = embedding
        self._col.document(_encode_path(domain_path)).set(data)

    def delete_position(self, domain_path):
        self._col.document(_encode_path(domain_path)).delete()

    def store_model(self, model_blob, domain_count):
        self._model_doc.set({"modelBlob": model_blob, "domainCount": domain_count,
                              "createdAt": firestore.SERVER_TIMESTAMP})

    def get_model(self):
        doc = self._model_doc.get()
        if not doc.exists:
            return None
        d = doc.to_dict()
        return {"model_blob": d.get("modelBlob"), "domain_count": d.get("domainCount")}


class FirestoreSimmerIterationRepository(SimmerIterationRepository):
    def __init__(self, db, workspace_id):
        self._db = db
        self._ws = workspace_id
        self._col = db.collection("workspaces").document(workspace_id).collection("simmerIterations")
        self._details_col = db.collection("workspaces").document(workspace_id).collection("simmerCriterionDetails")

    def create_iteration(self, id, job_id, phase, iteration, scores, composite,
                          key_change=None, asi=None, judge_mode=None, regressed=False,
                          candidate_preview=None):
        self._col.document(id).set({
            "jobId": job_id, "phase": phase, "iteration": iteration,
            "scores": scores, "composite": composite,
            "keyChange": key_change, "asi": asi, "judgeMode": judge_mode,
            "regressed": regressed, "candidatePreview": candidate_preview,
            "createdAt": firestore.SERVER_TIMESTAMP,
        })

    def create_criterion_detail(self, id, iteration_id, criterion, score, seed_score=None,
                                 evidence=None, improve=None):
        self._details_col.document(id).set({
            "iterationId": iteration_id, "criterion": criterion,
            "score": score, "seedScore": seed_score,
            "evidence": evidence, "improve": improve,
        })

    def get_for_job(self, job_id):
        job_col = self._db.collection("workspaces").document(self._ws).collection("jobs")
        job = job_col.document(job_id).get()
        if not job.exists:
            return None

        jd = job.to_dict()
        iters = self._col.where("jobId", "==", job_id).order_by("phase").order_by("iteration").stream()

        phases = {}
        for it in iters:
            d = it.to_dict()
            phase = d["phase"]
            details = self._details_col.where("iterationId", "==", it.id).stream()
            criteria = [{"criterion": dd.to_dict()["criterion"], "score": dd.to_dict()["score"],
                          "seed_score": dd.to_dict().get("seedScore"),
                          "evidence": dd.to_dict().get("evidence"),
                          "improve": dd.to_dict().get("improve")} for dd in details]

            if phase not in phases:
                phases[phase] = []
            phases[phase].append({
                "id": it.id, "iteration": d["iteration"],
                "scores": d.get("scores", {}), "composite": d.get("composite"),
                "key_change": d.get("keyChange"), "asi": d.get("asi"),
                "judge_mode": d.get("judgeMode"), "regressed": d.get("regressed", False),
                "candidate_preview": d.get("candidatePreview"),
                "criterion_details": criteria,
            })

        return {
            "job": {"id": job_id, "type": jd["type"], "target": jd["target"],
                     "status": jd["status"], "created_at": str(jd.get("createdAt", "")),
                     "started_at": str(jd.get("startedAt", "")) if jd.get("startedAt") else None,
                     "completed_at": str(jd.get("completedAt", "")) if jd.get("completedAt") else None},
            "phases": phases,
        }


# ── Composite DataStore ──────────────────────────────────

class FirestoreDataStore(DataStore):
    def __init__(self, project_id: str = None, workspace_id: str = "default"):
        import firebase_admin
        from firebase_admin import credentials

        # Initialize Firebase if not already done
        if not firebase_admin._apps:
            if project_id:
                cred = credentials.ApplicationDefault()
                firebase_admin.initialize_app(cred, {"projectId": project_id})
            else:
                firebase_admin.initialize_app()

        self._db = firestore.Client()
        self._workspace_id = workspace_id

        # Ensure workspace doc exists
        self._db.collection("workspaces").document(workspace_id).set(
            {"createdAt": firestore.SERVER_TIMESTAMP}, merge=True
        )

        self._documents = FirestoreDocumentRepository(self._db, workspace_id)
        self._chunks = FirestoreChunkRepository(self._db, workspace_id)
        self._domains = FirestoreDomainRepository(self._db, workspace_id)
        self._entities = FirestoreEntityRepository(self._db, workspace_id)
        self._entity_sources = FirestoreEntitySourceRepository(self._db, workspace_id)
        self._relationships = FirestoreRelationshipRepository(self._db, workspace_id)
        self._jobs = FirestoreJobRepository(self._db, workspace_id)
        self._specs = FirestoreSpecRepository(self._db, workspace_id)
        self._normalization = FirestoreNormalizationRepository(self._db, workspace_id)
        self._layout = FirestoreLayoutRepository(self._db, workspace_id)
        self._simmer_iterations = FirestoreSimmerIterationRepository(self._db, workspace_id)

    @property
    def documents(self): return self._documents
    @property
    def chunks(self): return self._chunks
    @property
    def domains(self): return self._domains
    @property
    def entities(self): return self._entities
    @property
    def entity_sources(self): return self._entity_sources
    @property
    def relationships(self): return self._relationships
    @property
    def jobs(self): return self._jobs
    @property
    def specs(self): return self._specs
    @property
    def normalization(self): return self._normalization
    @property
    def layout(self): return self._layout
    @property
    def simmer_iterations(self): return self._simmer_iterations

    @property
    def conn(self):
        """Not available for Firestore — returns None so hasattr checks work."""
        return None

    def close(self):
        pass  # Firestore client doesn't need explicit closing
