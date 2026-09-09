from fastapi.testclient import TestClient


def headers(client: TestClient) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Zhiyan@2026"})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_road_network_reachability_and_blocked_edge(client: TestClient) -> None:
    auth = headers(client)
    community = client.post("/api/v1/communities", headers=auth, json={"name": "路网社区"}).json()
    base = f"/api/v1/communities/{community['id']}/road-network"
    exit_node = client.post(base + "/nodes", headers=auth, json={"name": "北门", "x": 10, "y": 10, "is_exit": True})
    inner_node = client.post(base + "/nodes", headers=auth, json={"name": "3号楼路口", "x": 45, "y": 55, "is_exit": False})
    assert exit_node.status_code == 201 and inner_node.status_code == 201
    edge = client.post(base + "/edges", headers=auth, json={"name": "北侧通道", "start_node_id": exit_node.json()["id"], "end_node_id": inner_node.json()["id"], "width_meters": 4.0, "status": "open"})
    assert edge.status_code == 201
    assert client.get(base + "/reachability", headers=auth).json()["status"] == "passed"
    blocked = client.patch(base + f"/edges/{edge.json()['id']}/status", headers=auth, json={"status": "blocked"})
    assert blocked.status_code == 200
    result = client.get(base + "/reachability", headers=auth).json()
    assert result["status"] == "failed"
    assert result["unreachable_node_ids"] == [inner_node.json()["id"]]


def test_road_edge_rejects_foreign_or_same_node(client: TestClient) -> None:
    auth = headers(client)
    community = client.post("/api/v1/communities", headers=auth, json={"name": "校验社区"}).json()
    base = f"/api/v1/communities/{community['id']}/road-network"
    node = client.post(base + "/nodes", headers=auth, json={"name": "西门", "x": 5, "y": 5, "is_exit": True}).json()
    same = client.post(base + "/edges", headers=auth, json={"name": "错误边", "start_node_id": node["id"], "end_node_id": node["id"], "width_meters": 3, "status": "open"})
    assert same.status_code == 422


def test_road_node_can_be_repositioned_and_is_scoped_to_community(client: TestClient) -> None:
    auth = headers(client)
    first = client.post("/api/v1/communities", headers=auth, json={"name": "拖拽社区"}).json()
    second = client.post("/api/v1/communities", headers=auth, json={"name": "其他社区"}).json()
    first_base = f"/api/v1/communities/{first['id']}/road-network"
    node = client.post(first_base + "/nodes", headers=auth, json={"name": "南门路口", "x": 12, "y": 16, "is_exit": False}).json()

    moved = client.patch(first_base + f"/nodes/{node['id']}", headers=auth, json={"x": 38.5, "y": 62, "is_exit": True})
    assert moved.status_code == 200
    assert moved.json()["x"] == 38.5
    assert moved.json()["y"] == 62
    assert moved.json()["is_exit"] is True

    foreign = client.patch(f"/api/v1/communities/{second['id']}/road-network/nodes/{node['id']}", headers=auth, json={"x": 50})
    assert foreign.status_code == 404
