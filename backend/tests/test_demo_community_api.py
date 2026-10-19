from fastapi.testclient import TestClient


def test_create_demo_community_is_idempotent_and_complete(client: TestClient) -> None:
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Zhiyan@2026"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    first = client.post("/api/v1/communities/demo", headers=headers)
    second = client.post("/api/v1/communities/demo", headers=headers)
    assert first.status_code == 201 and second.status_code == 201
    community = first.json()
    assert second.json()["id"] == community["id"]

    objects = client.get(f"/api/v1/communities/{community['id']}/map-objects", headers=headers).json()
    assert len(objects) == 14
    assert {item["object_type"] for item in objects} >= {"building", "charging_shed", "fire_hydrant", "assembly_point"}
    network = client.get(f"/api/v1/communities/{community['id']}/road-network", headers=headers).json()
    # The current validated demo map has a west-side fire turning point and an
    # emergency bypass, so vehicle access does not depend on a diagonal route
    # through building geometry.
    assert len(network["nodes"]) == 9
    assert len(network["edges"]) == 11
    assert client.get(f"/api/v1/communities/{community['id']}/road-network/reachability", headers=headers).json()["status"] == "passed"


def test_demo_ready_creates_a_playable_3d_experience(client: TestClient) -> None:
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Zhiyan@2026"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    first = client.post("/api/v1/communities/demo-ready", headers=headers)
    second = client.post("/api/v1/communities/demo-ready", headers=headers)
    assert first.status_code == 201 and second.status_code == 201
    payload = first.json()
    assert second.json()["scene_id"] == payload["scene_id"]
    assert second.json()["drill_id"] == payload["drill_id"]

    scenes = client.get(f"/api/v1/communities/{payload['community']['id']}/scenes", headers=headers).json()
    assert any(scene["id"] == payload["scene_id"] and scene["status"] == "published" for scene in scenes)
    drills = client.get(f"/api/v1/scenes/{payload['scene_id']}/drills", headers=headers).json()
    assert drills[0]["id"] == payload["drill_id"]
    assert drills[0]["status"] == "ready"
    assert len(drills[0]["tasks"]) == 3
    assert len(drills[0]["simulation"]["residents"]) == 60
    assert drills[0]["engine_version"] == 3
