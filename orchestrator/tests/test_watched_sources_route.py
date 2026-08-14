def test_create_and_list_watched_source(test_client):
    r = test_client.post("/watched-sources", json={
        "type": "vault", "uri": "/vault", "noosphere": "ns",
        "cadence_hours": 12, "config_json": {"ext": [".md"]}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["type"] == "vault" and body["enabled"] == 1
    assert body["cadence_hours"] == 12 and body["config_json"] == {"ext": [".md"]}
    sid = body["id"]

    listing = test_client.get("/watched-sources").json()
    assert any(x["id"] == sid for x in listing)


def test_patch_toggles_enabled_and_cadence(test_client):
    sid = test_client.post("/watched-sources", json={"type": "repo", "uri": "/repo"}).json()["id"]
    r = test_client.patch(f"/watched-sources/{sid}", json={"enabled": False, "cadence_hours": 6})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] == 0 and body["cadence_hours"] == 6


def test_patch_unknown_source_404(test_client):
    assert test_client.patch("/watched-sources/nope", json={"enabled": False}).status_code == 404
