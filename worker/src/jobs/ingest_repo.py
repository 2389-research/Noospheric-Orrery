# ABOUTME: Phase 1 ingest job — recursively summarizes a repo into code_intent documents.
# ABOUTME: Assigns them to the repo's classified domain, then enqueues Phase 2 (extract_batch).

import hashlib
import json
import os
import re
import subprocess
import time
import uuid

from orrery_codesum import build_provides_map, make_summarize_fn, repo_import_edges, summarize_repo
from orrery_relay import Relay
from ..classifier import classify_document
from ..config import get_settings
from ..db import get_connection, mark_graph_dirty

MANIFEST_FILENAMES = ("pyproject.toml", "setup.py", "package.json", "go.mod")


def _parent_of(domain_path: str | None) -> str | None:
    if not domain_path or "/" not in domain_path:
        return None
    return domain_path.rsplit("/", 1)[0]


def _normalize_remote(url: str | None) -> str | None:
    """host/org/repo from an https or ssh git remote (drops scheme, credentials, .git)."""
    if not url:
        return None
    url = url.strip()
    if url.endswith(".git"):
        url = url[:-4]
    m = re.match(r"^[a-z]+://(?:[^@/]+@)?(.+)$", url)  # scheme://[user@]host/path
    if m:
        return m.group(1)
    m = re.match(r"^[^@]+@([^:]+):(.+)$", url)          # user@host:org/repo (ssh)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    return url


def _git_coordinates(root_path: str) -> tuple[str | None, str | None]:
    """(normalized remote, commit sha) for the checkout at root_path, or (None, None).

    Best-effort — returns Nones if root_path is not a git checkout, git is
    unavailable, or the working tree is DIRTY (a dirty tree differs from HEAD, so
    no GitHub ref could reproduce the actually-ingested source). Stored so the API
    can hand an agent a resolvable ref; the code itself is never stored (map, not
    territory)."""
    def _run(*args: str) -> str | None:
        try:
            r = subprocess.run(  # noqa: S603 — fixed argv, no shell
                ["git", "-C", root_path, *args],  # noqa: S607
                capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        # returncode-based so a clean `status --porcelain` (empty stdout) is
        # distinguishable from a failed command.
        return r.stdout.strip() if r.returncode == 0 else None

    status = _run("status", "--porcelain")
    if status is None or status:  # not a git repo, or uncommitted changes
        return (None, None)
    remote = _normalize_remote(_run("remote", "get-url", "origin"))
    sha = _run("rev-parse", "HEAD")
    # All-or-nothing: provenance needs BOTH a remote (to identify the repo) and a
    # SHA (to pin the version). Never persist a partial pair — e.g. a checkout
    # with no `origin`, or an empty repo with no HEAD.
    if not remote or not sha:
        return (None, None)
    return (remote, sha)


def _read_manifest_files(root_path: str) -> dict:
    """Read this repo's manifest files (pyproject.toml/setup.py/package.json/go.mod), if present."""
    files = {}
    for filename in MANIFEST_FILENAMES:
        full_path = os.path.join(root_path, filename)
        if os.path.isfile(full_path):
            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    files[filename] = f.read()
            except OSError:
                continue
    return files


def _declared_deps_from_manifests(manifest_files: dict) -> list[str]:
    """Best-effort parse of this repo's own declared dependency names."""
    raw_deps: list[str] = []

    pyproject = manifest_files.get("pyproject.toml")
    if pyproject:
        try:
            import tomllib
            data = tomllib.loads(pyproject)
            raw_deps.extend(data.get("project", {}).get("dependencies", []) or [])
        except Exception:
            pass

    package_json = manifest_files.get("package.json")
    if package_json:
        try:
            data = json.loads(package_json)
            raw_deps.extend((data.get("dependencies") or {}).keys())
            raw_deps.extend((data.get("devDependencies") or {}).keys())
        except Exception:
            pass

    # Strip version specifiers, e.g. "requests>=2.0" -> "requests".
    deps = []
    for dep in raw_deps:
        match = re.match(r"^[\w.\-]+", dep)
        if match:
            deps.append(match.group(0))
    return deps


async def run_ingest_repo(job: dict, db_path: str) -> None:
    settings = get_settings()
    relay = Relay.from_settings(settings)
    model = settings.extraction_model

    config = json.loads(job["config"]) if job["config"] else {}
    root_path = config["root_path"]
    repo_id = config["repo_id"]
    repo_name = config["repo_name"]
    spec_id = config["spec_id"]

    started = time.monotonic()
    print(f"[ingest_repo] {repo_name}: summarizing {root_path} ...", flush=True)
    summarize_fn = make_summarize_fn(relay, model)
    artifacts = summarize_repo(root_path, summarize_fn, repo_name)

    levels: dict = {}
    for a in artifacts:
        levels[a["level"]] = levels.get(a["level"], 0) + 1
    print(f"[ingest_repo] {repo_name}: {len(artifacts)} artifacts {levels}; classifying on repo summary ...", flush=True)

    # Read the existing taxonomy in a short-lived connection — nothing is held
    # open across the classification LLM call.
    conn = get_connection(db_path)
    try:
        taxonomy = [row[0] for row in conn.execute("SELECT path FROM domains").fetchall()]
    finally:
        conn.close()

    # Classify the repo on its GROUNDED repo-level summary (read the code, then
    # decide) rather than a README excerpt — works even for undocumented repos and
    # aligns the domain with the extracted-entity vocabulary.
    repo_summary = next((a["intent"] for a in artifacts if a["level"] == "repo"), "")
    excerpt = f"Repository: {repo_name}\n\n{repo_summary}"
    classification = await classify_document(
        relay=relay, title=repo_name, excerpt=excerpt,
        existing_taxonomy=taxonomy, model=settings.classification_model,
    )
    domain_path = classification["primary_domain"]
    confidence = classification.get("confidence")
    print(f"[ingest_repo] {repo_name} -> {domain_path} "
          f"(secondary={classification.get('secondary_domains')}, confidence={confidence})", flush=True)
    parent_domain = _parent_of(domain_path)
    # Distinct secondary domains (excluding the primary) — persisted per doc with
    # is_primary=0, matching the regular-document path (assign_document_domains) so
    # the taxonomy's secondary facets aren't dropped from the graph.
    secondaries = []
    _seen_dom = {domain_path}
    for _sec in (classification.get("secondary_domains") or []):
        if _sec and _sec not in _seen_dom:
            _seen_dom.add(_sec)
            secondaries.append(_sec)

    # Per-FILE placement: assign each file to the single best-matching subdomain
    # by embedding similarity, so files (and their entities) spread across the
    # repo's internal facets instead of all inheriting one repo-level label.
    # Module/repo artifacts keep the primary; falls back to primary if subdomains
    # or the embedder are unavailable.
    subdomains = [s for s in (classification.get("subdomains") or []) if s and "/" in s]
    file_domain: dict[str, str] = {}
    if subdomains:
        try:
            import numpy as np
            from ..normalizer import embed_entities
            sub_emb = np.asarray(embed_entities([s.replace("/", " ").replace("-", " ") for s in subdomains]))
            file_arts = [a for a in artifacts if a["level"] == "file"]
            if file_arts:
                fe = np.asarray(embed_entities([a["intent"] for a in file_arts]))
                best = (fe @ sub_emb.T).argmax(axis=1)
                for a, bi in zip(file_arts, best):
                    file_domain[a["path"]] = subdomains[int(bi)]
            print(f"[ingest_repo] {repo_name}: {len(subdomains)} subdomains, "
                  f"assigned {len(file_domain)} files", flush=True)
        except Exception as e:
            print(f"[ingest_repo] subdomain assignment skipped ({type(e).__name__}: {e})", flush=True)
            file_domain = {}

    # Git provenance for this checkout — stored so the API can hand agents a
    # resolvable ref (remote + sha + relative path) to fetch the real source.
    remote_url, commit_sha = _git_coordinates(root_path)

    # Persist everything in one transaction; always close the connection, and only
    # commit on success (a mid-write failure rolls back rather than leaving a
    # half-written repo + an open connection that blocks later jobs).
    conn = get_connection(db_path)
    try:
        conn.execute(
            "UPDATE repos SET remote_url = ?, commit_sha = ? WHERE id = ?",
            (remote_url, commit_sha, repo_id),
        )
        for artifact in artifacts:
            content = artifact["intent"]
            doc_id = str(uuid.uuid4())
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            source_path = os.path.join(root_path, artifact["path"])

            conn.execute(
                "INSERT INTO documents (id, title, content, content_hash, source_path, content_type, status) "
                "VALUES (?, ?, ?, ?, ?, 'code_intent', 'classified')",
                (doc_id, artifact["path"], content, content_hash, source_path),
            )
            conn.execute(
                "INSERT INTO chunks (id, document_id, chunk_index, text, offset, length) VALUES (?, ?, 0, ?, 0, ?)",
                (str(uuid.uuid4()), doc_id, content, len(content)),
            )
            conn.execute(
                "INSERT INTO document_repos (document_id, repo_id, level, parent_path) VALUES (?, ?, ?, ?)",
                (doc_id, repo_id, artifact["level"], artifact["parent_path"]),
            )
            conn.execute(
                "UPDATE repos SET document_count = document_count + 1 WHERE id = ?",
                (repo_id,),
            )

            # Primary domain per doc: a FILE goes to its matched subdomain (so
            # files/entities spread across the repo's facets); module/repo docs
            # keep the repo's primary domain + secondaries (aggregate context).
            # A zero-count domain is filtered out of the graph, so increment it.
            if artifact["level"] == "file" and artifact["path"] in file_domain:
                primary_dom = file_domain[artifact["path"]]
                doc_secondaries = []
            else:
                primary_dom = domain_path
                doc_secondaries = secondaries

            conn.execute(
                "INSERT OR IGNORE INTO domains (id, path, parent_path, document_count) VALUES (?, ?, ?, 0)",
                (str(uuid.uuid4()), primary_dom, _parent_of(primary_dom)),
            )
            conn.execute(
                "INSERT INTO document_domains (document_id, domain_path, is_primary, confidence) VALUES (?, ?, 1, ?)",
                (doc_id, primary_dom, confidence if confidence is not None else 1.0),
            )
            conn.execute(
                "UPDATE domains SET document_count = document_count + 1 WHERE path = ?",
                (primary_dom,),
            )

            # Secondary domains (is_primary=0), same doc-count semantics as the
            # primary — mirrors assign_document_domains for regular documents.
            for sec in doc_secondaries:
                conn.execute(
                    "INSERT OR IGNORE INTO domains (id, path, parent_path, document_count) VALUES (?, ?, ?, 0)",
                    (str(uuid.uuid4()), sec, _parent_of(sec)),
                )
                conn.execute(
                    "INSERT INTO document_domains (document_id, domain_path, is_primary, confidence) VALUES (?, ?, 0, ?)",
                    (doc_id, sec, confidence if confidence is not None else 1.0),
                )
                conn.execute(
                    "UPDATE domains SET document_count = document_count + 1 WHERE path = ?",
                    (sec,),
                )

        # Manifest -> repo_edges: find intra-org deps among known repos.
        known_repos = conn.execute("SELECT id, root_path FROM repos").fetchall()
        manifests_by_repo = {}
        for row in known_repos:
            other_repo_id, other_root_path = row[0], row[1]
            if not other_root_path:
                continue
            files = _read_manifest_files(other_root_path)
            if files:
                manifests_by_repo[other_repo_id] = files

        if manifests_by_repo:
            provides = build_provides_map(manifests_by_repo)
            this_manifest_files = manifests_by_repo.get(repo_id) or _read_manifest_files(root_path)
            declared_deps = _declared_deps_from_manifests(this_manifest_files)
            if declared_deps:
                for from_repo, to_repo in repo_import_edges(repo_id, declared_deps, provides):
                    conn.execute(
                        "INSERT OR IGNORE INTO repo_edges (from_repo, to_repo, type, weight) VALUES (?, ?, 'repo_uses', 1.0)",
                        (from_repo, to_repo),
                    )

        # Enqueue Phase 2 (extract_batch over the new code_intent docs), scoped to
        # content_type='code_intent' — NOT "all_classified", which would also sweep
        # up every unrelated classified document (e.g. stuck research papers) still
        # sitting in the workspace.
        conn.execute(
            "INSERT INTO jobs (id, type, target, status, config) VALUES (?, 'extract_batch', ?, 'queued', ?)",
            (str(uuid.uuid4()), repo_id, json.dumps({"spec_id": spec_id, "scope": "code_intent"})),
        )

        # Record the Phase-1 outcome on this job so it's queryable via GET /jobs.
        # (mark_job_completed preserves this — it no longer overwrites job-written results.)
        result = {
            "repo_name": repo_name,
            "primary_domain": domain_path,
            "secondary_domains": classification.get("secondary_domains", []),
            "confidence": confidence,
            "artifacts": len(artifacts),
            "levels": levels,
            "elapsed_s": round(time.monotonic() - started, 1),
        }
        conn.execute("UPDATE jobs SET result = ? WHERE id = ?", (json.dumps(result), job["id"]))
        print(f"[ingest_repo] {repo_name}: done in {result['elapsed_s']}s — enqueued extract_batch", flush=True)

        # New docs/domains/repos changed the graph — flag the snapshot for rebuild.
        mark_graph_dirty(conn)
        conn.commit()
    finally:
        conn.close()
