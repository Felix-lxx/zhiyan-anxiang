from sqlalchemy import create_engine, inspect, select, text

from app.api.routes import operations
from app.core.migrations import run_schema_migrations
from app.core.security import hash_password
from app.models.domain import Role, RoleCode, User, UserRole
from app.services.access import ensure_role_catalog


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
    assert response.json()["role_code"] == "system_admin"
    assert client.cookies.get("zhiyan_refresh_token")


def test_login_rejects_incorrect_credentials(client) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "incorrect"},
    )

    assert response.status_code == 401


def test_refresh_rotates_session_and_logout_revokes_access(client) -> None:
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Zhiyan@2026"})
    assert login.status_code == 200, login.text
    first_access = login.json()["access_token"]
    first_refresh = client.cookies.get("zhiyan_refresh_token")
    refreshed = client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["access_token"] != first_access
    assert client.cookies.get("zhiyan_refresh_token") != first_refresh
    headers = {"Authorization": "Bearer " + refreshed.json()["access_token"]}
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_user_can_review_and_revoke_another_login_session(client) -> None:
    first = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Zhiyan@2026"})
    assert first.status_code == 200, first.text
    first_headers = {"Authorization": "Bearer " + first.json()["access_token"]}
    second = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Zhiyan@2026"})
    assert second.status_code == 200, second.text
    second_headers = {"Authorization": "Bearer " + second.json()["access_token"]}

    sessions = client.get("/api/v1/auth/sessions", headers=second_headers)
    assert sessions.status_code == 200, sessions.text
    records = sessions.json()
    assert len(records) == 2
    assert sum(record["current"] for record in records) == 1
    first_session_id = next(record["id"] for record in records if not record["current"])

    revoked = client.delete(f"/api/v1/auth/sessions/{first_session_id}", headers=second_headers)
    assert revoked.status_code == 204, revoked.text
    assert client.get("/api/v1/auth/me", headers=first_headers).status_code == 401
    assert client.get("/api/v1/auth/me", headers=second_headers).status_code == 200


def test_participant_role_cannot_enter_management_workspace(client) -> None:
    with operations.SessionLocal() as session:
        ensure_role_catalog(session)
        role = session.scalar(select(Role).where(Role.code == RoleCode.PROPERTY_STAFF))
        assert role is not None
        user = User(
            username="property01",
            display_name="物业值守员",
            password_hash=hash_password("Property@2026"),
            is_active=True,
        )
        session.add(user)
        session.flush()
        session.add(UserRole(user_id=user.id, role_id=role.id))
        session.commit()

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "property01", "password": "Property@2026"},
    )
    assert response.status_code == 403
    assert "手机参演入口" in response.json()["detail"]


def test_repeated_login_failures_are_temporarily_locked(client) -> None:
    for _ in range(5):
        assert client.post("/api/v1/auth/login", json={"username": "admin", "password": "incorrect"}).status_code == 401
    locked = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Zhiyan@2026"})
    assert locked.status_code == 429


def test_schema_migration_upgrades_existing_user_table_idempotently() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY, username VARCHAR(64) NOT NULL, display_name VARCHAR(64) NOT NULL)"))
    run_schema_migrations(engine)
    run_schema_migrations(engine)
    columns = {column["name"] for column in inspect(engine).get_columns("users")}
    assert {"password_hash", "is_active"}.issubset(columns)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM schema_migrations")) == 1
