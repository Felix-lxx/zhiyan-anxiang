from fastapi.testclient import TestClient


def login_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "Zhiyan@2026"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_community(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post("/api/v1/communities", headers=headers, json={"name": "安巷社区"})
    assert response.status_code == 201
    return response.json()["id"]


def test_map_object_crud_for_current_community_version(client: TestClient) -> None:
    headers = login_headers(client)
    community_id = create_community(client, headers)
    base_url = f"/api/v1/communities/{community_id}/map-objects"

    create_response = client.post(
        base_url,
        headers=headers,
        json={
            "object_type": "building",
            "name": "1 号楼",
            "geometry": {"x": 40, "y": 50},
            "properties": {"note": "六层住宅"},
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["geometry"] == {"x": 40.0, "y": 50.0}

    list_response = client.get(base_url, headers=headers)
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [created["id"]]

    patch_response = client.patch(
        f"{base_url}/{created['id']}",
        headers=headers,
        json={"name": "1 号住宅楼", "geometry": {"x": 45, "y": 55}},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["name"] == "1 号住宅楼"
    assert patch_response.json()["geometry"] == {"x": 45.0, "y": 55.0}

    delete_response = client.delete(f"{base_url}/{created['id']}", headers=headers)
    assert delete_response.status_code == 204
    assert client.get(base_url, headers=headers).json() == []


def test_map_object_requires_identity_and_valid_coordinates(client: TestClient) -> None:
    assert client.get("/api/v1/communities/missing/map-objects").status_code == 401

    headers = login_headers(client)
    community_id = create_community(client, headers)
    response = client.post(
        f"/api/v1/communities/{community_id}/map-objects",
        headers=headers,
        json={"object_type": "exit", "name": "北门", "geometry": {"x": 101, "y": 10}},
    )
    assert response.status_code == 422
