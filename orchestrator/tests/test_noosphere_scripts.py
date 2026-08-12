# ABOUTME: Guards on the noosphere export/import scripts — the destructive paths.
# ABOUTME: Lives here because CI runs only orchestrator/tests; scripts/ has no suite.
"""The archive is the untrusted input.

`export_noosphere.py` reads a live corpus and `import_noosphere.py` writes into a data
dir on the strength of a manifest someone else wrote. Both do irreversible things —
delete a file, overwrite a database, append to the registry — so the failures worth
testing are the ones where a bad argument or a crafted archive destroys data that was
fine a moment earlier.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(name: str):
    """Import a script by path: scripts/ is not a package and never will be —
    import_noosphere.py has to run standalone from inside an archive."""
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


export_mod = _load("export_noosphere")
import_mod = _load("import_noosphere")


def _make_db(path: Path, marker: str = "original") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE documents (id TEXT, source_path TEXT)")
        conn.execute("CREATE TABLE entities (id TEXT)")
        conn.execute("CREATE TABLE layout_model (model_blob BLOB)")
        conn.execute("CREATE TABLE graph_snapshot (payload TEXT, dirty INTEGER)")
        conn.execute("INSERT INTO documents VALUES (?, '/data/x')", (marker,))
        conn.commit()
    return path


def _marker(path: Path) -> str:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        return conn.execute("SELECT id FROM documents").fetchone()[0]


# --- export ---------------------------------------------------------------------


def test_exporting_into_the_workspace_dir_does_not_delete_the_corpus(tmp_path):
    """`--out` pointing at the workspace made `staged` the live database.

    The unlink that clears a previous export then deleted the corpus itself, before
    VACUUM INTO ran — so the failure was total and had nothing left to recover from.
    """
    data = tmp_path / "data"
    src = _make_db(data / "workspaces" / "swe" / "orrery.db")

    with pytest.raises(SystemExit):
        export_mod.export("swe", data, src.parent)

    assert src.is_file(), "the source database was deleted"
    assert _marker(src) == "original"


def test_a_normal_export_still_works(tmp_path):
    data = tmp_path / "data"
    _make_db(data / "workspaces" / "swe" / "orrery.db")
    out = export_mod.export("swe", data, tmp_path / "out")

    assert (out / "orrery.db").is_file()
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["counts"]["documents"] == 1
    # Derived state is dropped, not shipped.
    with sqlite3.connect(out / "orrery.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM layout_model").fetchone()[0] == 0


@pytest.mark.parametrize("bad", ["../escape", "../../etc", "a/b", ".", "..", "", "/abs"])
def test_export_refuses_a_workspace_id_that_is_not_one_path_component(tmp_path, bad):
    with pytest.raises(SystemExit):
        export_mod.export(bad, tmp_path / "data", tmp_path / "out")


def test_export_survives_a_registry_that_is_not_a_list(tmp_path):
    """Iterating a dict yields str keys, and `.get` on those raises."""
    data = tmp_path / "data"
    _make_db(data / "workspaces" / "swe" / "orrery.db")
    (data / "workspaces" / "registry.json").write_text('{"id": "swe"}')

    out = export_mod.export("swe", data, tmp_path / "out")
    assert (out / "manifest.json").is_file()


# --- import ---------------------------------------------------------------------


def _archive(tmp_path, ws_id="swe", marker="incoming", db_bytes=None) -> Path:
    arch = tmp_path / "archive"
    arch.mkdir(parents=True, exist_ok=True)
    if db_bytes is None:
        _make_db(arch / "orrery.db", marker)
    else:
        (arch / "orrery.db").write_bytes(db_bytes)
    (arch / "manifest.json").write_text(json.dumps(
        {"workspace": {"id": ws_id, "name": ws_id}, "counts": {"documents": 1}}))
    return arch


def _run_import(monkeypatch, arch: Path, argv, services_up=False):
    monkeypatch.setattr(import_mod, "HERE", arch)
    monkeypatch.setattr(import_mod, "_services_are_up", lambda *a, **k: services_up)
    return import_mod.main(argv)


def test_a_running_orchestrator_stops_the_install_even_with_force(monkeypatch, tmp_path):
    """--force used to bypass this. It must not.

    The stop exists for two hazards, and --force answers only the first: being on
    current code says nothing about replacing a database and deleting its -wal/-shm
    while a live process holds them open.
    """
    arch = _archive(tmp_path)
    data = tmp_path / "data"
    target = _make_db(data / "workspaces" / "swe" / "orrery.db", "existing")

    with pytest.raises(SystemExit):
        _run_import(monkeypatch, arch, ["--data", str(data), "--force"], services_up=True)

    assert _marker(target) == "existing", "a live workspace was overwritten"


def test_the_escape_hatch_is_a_separate_flag(monkeypatch, tmp_path):
    arch = _archive(tmp_path)
    data = tmp_path / "data"
    assert _run_import(monkeypatch, arch,
                       ["--data", str(data), "--skip-service-check"],
                       services_up=True) == 0
    assert _marker(data / "workspaces" / "swe" / "orrery.db") == "incoming"


def test_force_still_overwrites_when_the_services_are_down(monkeypatch, tmp_path):
    arch = _archive(tmp_path)
    data = tmp_path / "data"
    _make_db(data / "workspaces" / "swe" / "orrery.db", "existing")

    assert _run_import(monkeypatch, arch, ["--data", str(data), "--force"]) == 0
    assert _marker(data / "workspaces" / "swe" / "orrery.db") == "incoming"


def test_an_existing_workspace_is_not_touched_without_force(monkeypatch, tmp_path):
    arch = _archive(tmp_path)
    data = tmp_path / "data"
    target = _make_db(data / "workspaces" / "swe" / "orrery.db", "existing")

    with pytest.raises(SystemExit):
        _run_import(monkeypatch, arch, ["--data", str(data)])
    assert _marker(target) == "existing"


def test_a_non_sqlite_archive_is_rejected_before_anything_is_written(monkeypatch, tmp_path):
    """`is_file()` accepts any bytes.

    The database was copied and the registry appended to, and only the final open
    failed — leaving a registered workspace pointing at garbage, which is worse than
    the run simply failing.
    """
    arch = _archive(tmp_path, db_bytes=b"this is not a database")
    data = tmp_path / "data"
    target = _make_db(data / "workspaces" / "swe" / "orrery.db", "existing")
    registry = data / "workspaces" / "registry.json"
    registry.write_text("[]")

    with pytest.raises(SystemExit):
        _run_import(monkeypatch, arch, ["--data", str(data), "--force"])

    assert _marker(target) == "existing", "the target was overwritten with garbage"
    assert json.loads(registry.read_text()) == [], "a bad archive was registered"


def test_a_database_damaged_in_transit_is_rejected(monkeypatch, tmp_path):
    """A schema read is not enough, and this is the archive's most likely damage.

    The file has just crossed a network or a Drive share. Losing pages in the middle
    leaves the header and `sqlite_master` perfectly readable, so the cheap check passes
    and a quietly broken corpus gets installed. `PRAGMA integrity_check` walks every
    page — 2s on the real 865 MB export.
    """
    arch = tmp_path / "archive"
    arch.mkdir()
    db = arch / "orrery.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE documents (id TEXT, source_path TEXT, body TEXT)")
        conn.executemany("INSERT INTO documents VALUES (?, '/data/x', ?)",
                         [(str(i), "padding" * 200) for i in range(4000)])
        conn.commit()

    # Corrupt a page well past the schema, the way a truncated transfer would.
    raw = bytearray(db.read_bytes())
    assert len(raw) > 200 * 4096, "need a multi-page database for this to be meaningful"
    raw[100 * 4096:120 * 4096] = b"\x00" * (20 * 4096)
    db.write_bytes(bytes(raw))

    # The cheap check this replaced still passes on the damaged file — that is the point.
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] > 0

    (arch / "manifest.json").write_text(json.dumps({"workspace": {"id": "swe"}}))
    data = tmp_path / "data"
    with pytest.raises(SystemExit):
        _run_import(monkeypatch, arch, ["--data", str(data)])
    assert not (data / "workspaces" / "swe" / "orrery.db").exists()


@pytest.mark.parametrize("bad", ["../escape", "../../etc/passwd", "a/b", ".", "..", "/abs"])
def test_a_crafted_manifest_id_cannot_escape_the_workspace_root(monkeypatch, tmp_path, bad):
    """The id defaults to one read out of the archive — i.e. attacker-controlled."""
    arch = _archive(tmp_path, ws_id=bad)
    data = tmp_path / "data"

    with pytest.raises(SystemExit):
        _run_import(monkeypatch, arch, ["--data", str(data)])

    escaped = [p for p in tmp_path.rglob("orrery.db")
               if p.parent != arch and "workspaces" not in p.parts]
    assert not escaped, f"wrote outside the workspace root: {escaped}"


def test_a_traversing_id_on_the_command_line_is_refused_too(monkeypatch, tmp_path):
    arch = _archive(tmp_path)
    with pytest.raises(SystemExit):
        _run_import(monkeypatch, arch,
                    ["--data", str(tmp_path / "data"), "--id", "../../pwned"])
    assert not (tmp_path / "pwned").exists()


@pytest.mark.parametrize("body", ["[]", "null", '"a string"', "not json at all"])
def test_a_malformed_manifest_fails_cleanly(monkeypatch, tmp_path, body):
    arch = _archive(tmp_path)
    (arch / "manifest.json").write_text(body)
    data = tmp_path / "data"

    # Either it exits, or it falls back to the default id — never a traceback.
    try:
        rc = _run_import(monkeypatch, arch, ["--data", str(data)])
    except SystemExit:
        return
    assert rc == 0
    assert (data / "workspaces" / "imported" / "orrery.db").is_file()


def test_a_registry_that_is_not_a_list_is_replaced_not_crashed_on(monkeypatch, tmp_path):
    arch = _archive(tmp_path)
    data = tmp_path / "data"
    (data / "workspaces").mkdir(parents=True)
    (data / "workspaces" / "registry.json").write_text('{"id": "swe"}')

    assert _run_import(monkeypatch, arch, ["--data", str(data)]) == 0
    registry = json.loads((data / "workspaces" / "registry.json").read_text())
    assert [w["id"] for w in registry] == ["swe"]


def test_the_round_trip_preserves_the_graph(monkeypatch, tmp_path):
    """Export then import, and the documents survive."""
    data = tmp_path / "data"
    _make_db(data / "workspaces" / "swe" / "orrery.db", "roundtrip")
    out = export_mod.export("swe", data, tmp_path / "out")

    dest = tmp_path / "dest"
    assert _run_import(monkeypatch, out, ["--data", str(dest)]) == 0
    assert _marker(dest / "workspaces" / "swe" / "orrery.db") == "roundtrip"
