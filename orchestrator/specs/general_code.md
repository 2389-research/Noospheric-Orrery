# General Code Entity Extraction Spec

**Purpose:** the default extractor for any file / module / repo entering the git-org knowledge graph.
Reads an intent summary (and code, when present) and emits a flat `{name, type}` list describing the
unit at the level a teammate would — what it does, how, what it is built on, what it talks to. General
across software engineering, not tuned to any one stack.

**Design principle:** extract generously, type conservatively, **err toward recall**. Capture the
entity rather than agonize over whether it is worth keeping — dedup, normalization, and pruning happen
downstream.

**Input contract:** the unit's **intent summary** (source of record for *what / how*) and, when
present, its **code** (source of record for concrete *names*: imports, symbols, routes, tables).
Prefer the summary for what/how; trust the code for names.

---

## Entity Types

Seven general types span software engineering. Each entity is `{name, type}`. **The example lists are
SEEDS, not a closed set** — extract any concept that fits a type's definition even if unlisted, coining
the name in the same canonical, lowercase style; prefer a listed name when one applies. Keep to these
seven TYPES so entities stay comparable; finer types come only from domain-specific simmered specs.

### `capability` — *what the unit lets you do*
The functional outcome a teammate would say it delivers (phrase as the thing you can accomplish, not
the code that does it).
Seed examples:
- *auth / security:* user authentication, session management, authorization / rbac, oauth login, input
  sanitization, secrets management, encryption, csrf protection, audit logging
- *data / search:* full-text search, vector similarity search, data validation, serialization,
  deduplication, pagination, caching, embedding generation
- *web / api:* request routing, file upload, rate limiting, api versioning, webhook handling, form validation
- *infra / ops:* background job scheduling, health checks, observability / telemetry, feature flagging,
  service discovery, load balancing, autoscaling, ci/cd
- *data engineering:* etl, stream processing, batch processing, change data capture, data ingestion
- *ml:* model training, inference serving, structured output extraction, prompt orchestration
- *messaging / io:* real-time messaging, push notifications, email delivery, image resizing, pdf
  generation, web crawling, html scraping
- *frontend / mobile:* state management, client-side routing, server-side rendering, offline sync

### `technique` — *a named, reusable method or role for how it is built*
A design or architecture pattern, an algorithm, **or the architectural role / component type a unit
plays** — transferable across projects; use its canonical SWE name.
Seed examples:
- *design patterns:* factory, builder, singleton, adapter, decorator, facade, proxy, observer, strategy,
  state machine, command, iterator, visitor
- *architecture:* dependency injection, repository pattern, mvc, mvvm, layered architecture, hexagonal
  architecture, clean architecture, microservices, event-driven architecture, cqrs, event sourcing,
  pub/sub, api gateway, circuit breaker, bulkhead, sidecar, saga, backpressure
- *architectural roles / components:* orchestrator, worker, sink, source, handler, controller, service,
  client, server, daemon, scheduler, queue, router, registry, middleware, load balancer, reverse proxy
- *resilience / concurrency:* retry-with-backoff, exponential backoff, token bucket, debounce,
  throttling, producer-consumer, worker pool, connection pooling, actor model, mutex, semaphore
- *data / algorithms:* map-reduce, memoization, lru cache, bloom filter, consistent hashing, sharding,
  replication, write-ahead log, cosine similarity, tf-idf, bm25, reciprocal rank fusion, binary search,
  dynamic programming, a-star
- *deployment:* blue-green deployment, canary release, feature toggle, rolling update

### `technology` — *a language, framework, runtime, platform, or library it is built with*
A named tool in an ecosystem the code uses or imports **in-process**. Distinct from `integration` (an
external running system): `boto3` is a `technology`; `aws s3` is the `integration`.
Seed examples:
- *languages:* python, typescript, javascript, rust, go, java, c#, c++, c, ruby, php, swift, kotlin,
  scala, elixir, sql, bash
- *frontend:* react, vue, svelte, angular, next.js, nuxt, tailwind, vite, webpack, react native, flutter
- *backend / web:* node.js, express, fastapi, django, flask, spring, rails, .net, laravel, gin, actix
- *infra / runtime:* docker, kubernetes, helm, terraform, ansible, tokio, asyncio, grpc, graphql, nginx,
  prometheus, grafana
- *data / ml:* pytorch, tensorflow, jax, pandas, numpy, scikit-learn, spark, airflow, dbt, huggingface
  transformers, langchain, faiss, duckdb
- *libraries:* requests, axios, pydantic, zod, serde, sqlalchemy, prisma, redux, lodash

### `integration` — *an external system, service, device, or protocol it talks to*
Something running outside the process, communicated with over a network, bus, or hardware — as opposed
to a library it imports.
Seed examples:
- *cloud:* aws, gcp, azure, aws s3, aws lambda, sqs, sns, dynamodb, bigquery, cloudflare, vercel
- *data stores / brokers:* postgres, mysql, redis, mongodb, elasticsearch, sqlite, cassandra, snowflake,
  kafka, rabbitmq
- *services / apis:* stripe, twilio, sendgrid, github api, slack api, openai api, anthropic api,
  datadog, sentry
- *auth / identity:* auth0, okta, oauth, ldap, saml
- *devices / protocols:* bluetooth le, mqtt, gpio, serial, usb, i2c, spi, can bus, websocket, webrtc, smtp

### `interface` — *a specific public surface it exposes*
A named handle others call or hit: an http route, CLI command, exported API symbol
(function / class / method / trait), or emitted event / webhook. Keep the recognizable form.
Seed examples: post /login, get /users/{id}, graphql schema, grpc service; git commit, docker build,
`<tool> <subcommand>`; Logger.info, HttpClient, PaymentService.charge; onMessage event,
payment.succeeded webhook, kafka topic, plugin hook.

### `data_model` — *a named schema, table, structured type, or data format it defines or uses*
Seed examples: User model, Order schema, protobuf message, graphql type, DTO, value object, orm entity,
event payload; users table, orders table, migration; json, jsonl, yaml, toml, csv, xml, protobuf, avro,
parquet, arrow, openapi spec, json schema.

### `domain_concept` — *a problem-space idea or term that fits none of the above*
The vocabulary of the domain the software serves — not a technical construct.
Seed examples: shopping cart, invoice, double-entry ledger (commerce / fintech); patient record,
icd-10 code (health); leaderboard, matchmaking, hitbox (games); order book, slippage (trading);
embedding, token, attention (ml); geofence, waypoint (mapping); ticket, sprint, backlog (project mgmt).

### Choosing a type (first match wins)
1. A specific named handle you call/hit (route, command, exported symbol)? → `interface`
2. An external running system / service / device / protocol? → `integration`
3. A named language / framework / runtime / library it is built with? → `technology`
4. A named schema / table / structured type / format? → `data_model`
5. A named, transferable design / algorithm method or architectural role (the *how*)? → `technique`
6. An outcome the unit delivers (the *what*)? → `capability`
7. Otherwise a problem-space term → `domain_concept`

### Common confusions (resolve these explicitly)
- **capability vs technique:** a `capability` is an *outcome the unit delivers* — `schema validation`,
  `request/response serialization`, `deterministic scoring`, `structured output extraction`. A
  `technique` is a *named, transferable method or role* — `weighted scoring`, `retry-with-backoff`,
  `map-reduce`, `adapter`, `worker`. An "-ing" activity that is not itself a named algorithm/pattern is
  a `capability`.
- **capability vs technology:** a `technology` is a *named tool you could import or install* (`react`,
  `tokio`, `pandas`, `playwright`). A described activity is never a technology — `tool execution`,
  `html parsing`, `anthropic api client` are `capability`, not `technology`.
- **data_model vs domain_concept:** a `data_model` is a *named schema / table / type / format in the
  code* (`analysis`, `users table`, `json schema`). A domain standard or field term is a
  `domain_concept` (`usms`, `icd-10`, `freestyle stroke`).
- **technique vs domain_concept:** architecture / dataflow shapes are techniques — `pipeline`,
  `event-driven`, `pub/sub` are `technique`, not `domain_concept`.

---

## Extraction Rules

### Extract when any of these is true
1. **The summary names it as intent** — "does X" / "handles Y" / "implements the Z technique".
2. **It is a language, framework, or library used or imported** → `technology`.
3. **It is a public surface defined here** (route, command, exported symbol) → `interface`.
4. **It is a named structure or format** it defines or relies on → `data_model`.
5. **It names an external system it talks to** → `integration`.
6. **It names a domain term** central to what the unit is about → `domain_concept`.

### Do NOT extract
1. **Implementation mechanics** — loop bodies, local variables, control flow, private helpers.
2. **Language builtins / stdlib plumbing** as capabilities (`list`, `for`, `open`).
3. **Generated / boilerplate names** — scaffolding, auto-named migrations, fixtures.
4. **The unit's own name or path** — file names (`traverse.py`), module names, the repo name. (A
   deterministic post-filter also strips literal file paths, so don't worry about catching them all.)
5. **Secrets** — never extract API keys, tokens, or `.env` values.

## Naming & Boundary
- Extract the **most specific named unit** as ONE entity; don't split compounds ("aws s3" = one
  `integration`; "retry-with-backoff" = one `technique`).
- **Canonical, lowercase, singularize.** Resolve clear abbreviations ("rrf" → "reciprocal rank
  fusion"); keep standard ones ("api", "sql", "ble"). **Dedup** before output.

## Worked Example
**Intent summary:**
> `list_fetcher.py` implements a browser-fallback fetcher for army lists. When the auth refresh is
> rejected, it drives a real Chrome session via Playwright to scrape the gated list pages, using a
> retry-with-backoff loop against rate limits, and writes results to a local SQLite cache.

**Output:**
```json
{ "entities": [
  {"name": "web scraping", "type": "capability"},
  {"name": "retry-with-backoff", "type": "technique"},
  {"name": "playwright", "type": "technology"},
  {"name": "listfetcher.fetch_list", "type": "interface"},
  {"name": "sqlite", "type": "integration"},
  {"name": "army list", "type": "domain_concept"}
] }
```

## Output Schema
```json
{ "entities": [ {"name": "entity name lowercase", "type": "one of the 7 types"} ] }
```
No relationships, no properties. Downstream handles normalization, dedup, co-occurrence, and pruning.

## Execution Notes
- Runs on every ingested unit; fast + cheap; use the smallest model that gives acceptable quality.
- **Err toward recall** — extras are expected and pruned downstream.
- **Domain-specific simmered specs supersede this** with granular types once a domain has one.
- Trust the summary for what/how; trust the code for names — never invent a capability the summary
  doesn't support, nor a dependency/interface/table name the code doesn't contain.
