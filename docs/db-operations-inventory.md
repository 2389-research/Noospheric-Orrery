# Database Operations Inventory

87 distinct DB operations across 18 tables. This inventory maps every read/write
in the codebase for the Firebase migration DB abstraction layer.

## Summary

- **55 READ operations** (63%)
- **32 WRITE operations** (37%)
- **Heaviest files**: routes/ingest.py (~15 ops), routes/graph.py (~10 ops), pipeline/embedding_normalizer.py (~10 ops)
- **Most touched tables**: entities (10 ops), entity_sources (6 ops), documents (10 ops), domains (9 ops)

## Repository Interfaces Needed

### DocumentRepository
- createDocument(title, content, contentHash, sourcePath) → docId
- getDocument(docId) → Document
- listDocuments(limit, offset) → Document[]
- getDocumentByHash(hash) → Document | null
- updateDocumentStatus(docId, status)
- getDocumentsForDomain(domainPath, statusFilter?) → Document[]
- getRecentDocuments(limit) → Document[]
- getSampleDocuments(limit, statusFilter) → Document[]

### ChunkRepository
- createChunks(docId, chunks[])
- getChunksForDocument(docId) → Chunk[]
- getAllChunksWithEmbeddings() → Chunk[]
- updateChunkEmbedding(chunkId, embedding)

### DomainRepository
- createDomain(path, parentPath) → domainId
- getDomain(path) → Domain | null
- listDomains(minDocCount?) → Domain[]
- getAllDomainPaths() → string[]
- incrementDocumentCount(path)
- updateSpecVersion(path, version)
- getDomainMergeTarget(label) → string | null

### DocumentDomainRepository
- assignDomain(docId, domainPath, isPrimary, confidence)
- getDomainsForDocument(docId) → DomainAssignment[]
- getDocumentsForDomain(domainPath) → docId[]
- getEntityDomainWeights(entityId) → {domainPath: weight}[]

### EntityRepository
- createEntity(name, type) → entityId
- getEntity(entityId) → Entity
- listEntities(filter?) → Entity[]
- getEntityByName(name, type) → Entity | null
- deleteEntity(entityId)
- updateEntityEmbedding(entityId, embedding)
- getEntitiesForDocument(docId) → Entity[]
- getEntitiesForDomain(domainPath, limit?) → Entity[]
- getAllEntitiesForNormalization() → Entity[]
- getEntitySourceCount(entityId) → number

### EntitySourceRepository
- createSource(entityId, docId, chunkId, extractionPass, specVersion, jobId?)
- getSourcesForEntity(entityId) → Source[]
- getSourceCountForEntity(entityId) → number
- updateEntityIdOnMerge(fromId, toId)
- getSharedDocuments(entityId, docIds) → {entityId: docId[]}

### RelationshipRepository
- upsertCooccurrence(fromEntity, toEntity, weight, sourceChunk)
- getCooccurrences(entityId, limit?) → Cooccurrence[]
- getCooccurrencesWithSharedDocs(entityId, limit?) → CooccurrenceWithDocs[]
- updateEntityReferencesOnMerge(fromId, toId)

### JobRepository
- createJob(type, target, config?) → jobId
- getJob(jobId) → Job
- listJobs(statusFilter?) → Job[]
- getExistingJob(type, target, statuses) → Job | null
- pickNextJob() → Job | null
- markJobRunning(jobId)
- markJobCompleted(jobId, result)
- markJobFailed(jobId, error)

### SimmerIterationRepository
- createIteration(jobId, phase, iteration, scores, composite, keyChange, asi, judgeMode, regressed)
- createCriterionDetails(iterationId, criterion, score, seedScore, evidence, improve)
- getIterationsForJob(jobId) → {phases: {[phase]: Iteration[]}}

### NormalizationRepository
- getExistingReview(entityAId, entityBId) → Review | null
- createReview(entityAId, entityAName, entityBId, entityBName, similarity)
- getReviewQueue() → Review[]
- resolveReview(reviewId, action)
- createMergeLog(fromId, fromName, toId, toName, method, similarity)
- getMergeSummary() → Summary
- getMergeMapEntry(name) → entityId | null
- createMergeMapEntry(fromName, toEntityId)

### SpecRepository
- createSpec(domainPath, version, content, goldenSet, score) → specId
- getGeneralSpec() → Spec | null
- getDomainSpec(domainPath) → Spec | null
- getLatestSpecVersion(domainPath) → number

### LayoutRepository
- getStoredPositions() → {domainPath: {x, y}}
- storePosition(domainPath, x, y, embedding?)
- deletePosition(domainPath)
- storeModel(modelBlob, domainCount)
- getModel() → {modelBlob, domainCount} | null

## Migration Notes

- **Denormalization needed for Firestore**: entity sourceCount, domain documentCount should be maintained as fields (not computed via COUNT queries)
- **Subcollections vs flat**: entity_sources and chunks as subcollections under their parent document/entity
- **Composite queries**: Firestore can't do arbitrary JOINs. The graph endpoint and star-graph endpoint need restructuring — either denormalize or make multiple reads
- **Batch writes**: Firestore has 500-write batch limit. Entity extraction for large docs may need batching
- **Transaction needed**: entity normalization (merge) touches multiple collections atomically
