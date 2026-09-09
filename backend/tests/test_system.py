def test_health_check_exposes_service_state(client) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "智演安巷 API"
    assert body["status"] in {"healthy", "degraded"}


def test_development_login_returns_a_token(client) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "Zhiyan@2026"},
    )

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["access_token"]


def test_login_rejects_incorrect_credentials(client) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "incorrect"},
    )

    assert response.status_code == 401
