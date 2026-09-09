from fastapi.testclient import TestClient


def login_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "Zhiyan@2026"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_role_catalog_requires_authenticated_user(client: TestClient) -> None:
    response = client.get("/api/v1/roles")

    assert response.status_code == 401


def test_role_catalog_is_seeded_for_authenticated_user(client: TestClient) -> None:
    response = client.get("/api/v1/roles", headers=login_headers(client))

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 7
    assert {role["code"] for role in body} >= {"system_admin", "exercise_designer", "assessor"}


def test_create_and_read_a_draft_community(client: TestClient) -> None:
    headers = login_headers(client)
    create_response = client.post(
        "/api/v1/communities",
        headers=headers,
        json={
            "name": "安巷社区",
            "address": "示例路 18 号",
            "description": "用于夜间电动自行车充电棚火灾演练的示例社区。",
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["status"] == "draft"
    assert created["owner_username"] == "admin"
    assert created["versions"] == [
        {
            "id": created["versions"][0]["id"],
            "version_number": 1,
            "name": "初始社区版本",
            "status": "draft",
        }
    ]

    list_response = client.get("/api/v1/communities", headers=headers)
    assert list_response.status_code == 200
    assert [community["id"] for community in list_response.json()] == [created["id"]]

    detail_response = client.get(f"/api/v1/communities/{created['id']}", headers=headers)
    assert detail_response.status_code == 200
    assert detail_response.json()["name"] == "安巷社区"
