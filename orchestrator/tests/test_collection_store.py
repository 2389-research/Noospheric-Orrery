def test_create_and_link_repo(tmp_path):
    from src.db import init_db
    from src.repositories.sqlite_store import SQLiteDataStore
    db = str(tmp_path / "t.db"); init_db(db)
    store = SQLiteDataStore(db)
    store.documents.create("d1", "f.py", "does X", "hash1", "/repo/f.py", content_type="code_intent")
    store.collections.create("r1", "myrepo", "myrepo", "/repo")
    store.collections.link_document("d1", "r1", role="leaf", parent_path="myrepo")
    assert isinstance(store.collections.get_collection_routes(), list)
    assert isinstance(store.collections.get_collection_weights(), dict)
