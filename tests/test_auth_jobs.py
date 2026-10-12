"""Endpoint tests for authentication and role-scoped job access."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, update

import auth
import create_staff
import main
from database import initialize_database, tbl_sessions, tbl_users


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "int_bcrypt_rounds", 4)
    obj_engine = initialize_database(f"sqlite:///{tmp_path / 'test.sqlite'}")
    obj_previous_engine = main.app.state.obj_engine
    main.app.state.obj_engine = obj_engine
    main._jobs.clear()
    main._inquiries.clear()
    with TestClient(main.app) as obj_client:
        yield obj_client
    main._jobs.clear()
    main._inquiries.clear()
    main.app.state.obj_engine = obj_previous_engine
    obj_engine.dispose()


def create_account(obj_client: TestClient, str_email: str, str_password: str = "secure-password-123") -> None:
    obj_response = obj_client.post(
        "/api/auth/register",
        json={"email": str_email, "password": str_password, "first_name": "Casey", "last_name": "Hippo"},
    )
    assert obj_response.status_code == 201, obj_response.text


def submit_inquiry(obj_client: TestClient, str_email: str, str_company: str) -> dict:
    obj_response = obj_client.post(
        "/api/inquiry",
        json={
            "customer_name": "Casey Hippo",
            "email": str_email,
            "company": str_company,
            "service": "Prototyping",
            "project_details": "Build a test fixture for our new assembly.",
        },
    )
    assert obj_response.status_code == 201, obj_response.text
    return obj_response.json()["job"]


def test_inquiry_login_customer_scope_and_logout(client):
    assert client.get("/").status_code == 200
    assert client.get("/api/jobs").status_code == 401

    create_account(client, "casey@example.com")
    own_job = submit_inquiry(client, "casey@example.com", "Casey's Shop")
    submit_inquiry(client, "other@example.com", "Other Shop")

    obj_login = client.post(
        "/api/auth/login", json={"email": "casey@example.com", "password": "secure-password-123"}
    )
    assert obj_login.status_code == 200, obj_login.text
    assert "httponly" in obj_login.headers["set-cookie"].lower()
    obj_jobs = client.get("/api/jobs")
    assert obj_jobs.status_code == 200
    assert [obj_job["id"] for obj_job in obj_jobs.json()["jobs"]] == [own_job["id"]]

    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/jobs").status_code == 401


def test_only_staff_can_list_every_job_or_update(client):
    obj_customer_job = submit_inquiry(client, "customer@example.com", "Customer Shop")
    obj_other_job = submit_inquiry(client, "other@example.com", "Other Shop")
    create_account(client, "customer@example.com")
    assert client.post(
        "/api/auth/login", json={"email": "customer@example.com", "password": "secure-password-123"}
    ).status_code == 200

    obj_update = {"status": "In Production", "estimated_completion_date": "2026-11-20", "estimated_shipping_date": "2026-11-24"}
    assert client.put(f"/api/jobs/{obj_customer_job['id']}", json=obj_update).status_code == 403
    assert len(client.get("/api/jobs").json()["jobs"]) == 1
    client.post("/api/auth/logout")

    with main.app.state.obj_engine.begin() as obj_connection:
        obj_connection.execute(
            insert(tbl_users).values(
                email="staff@example.com",
                first_name="Sam",
                last_name="Staff",
                is_admin=True,
                hashed_password=auth.hash_password("staff-password-123"),
            )
        )
    obj_login = client.post(
        "/api/auth/login", json={"email": "staff@example.com", "password": "staff-password-123"}
    )
    assert obj_login.status_code == 200 and obj_login.json()["is_admin"] is True
    obj_all_jobs = client.get("/api/jobs")
    assert {obj_job["id"] for obj_job in obj_all_jobs.json()["jobs"]} == {
        obj_customer_job["id"], obj_other_job["id"]
    }
    obj_updated = client.put(f"/api/jobs/{obj_customer_job['id']}", json=obj_update)
    assert obj_updated.status_code == 200, obj_updated.text
    assert obj_updated.json()["job"]["status"] == "In Production"
    assert obj_updated.json()["job"]["estimated_shipping_date"] == "2026-11-24"


def test_registration_validation_and_old_role_header_grants_no_access(client):
    obj_short_password = client.post(
        "/api/auth/register",
        json={"email": "new@example.com", "password": "short", "first_name": "New", "last_name": "User"},
    )
    assert obj_short_password.status_code == 400
    assert client.get("/api/jobs", headers={"X-User-Role": "admin"}).status_code == 401
    create_account(client, "new@example.com")
    obj_wrong_password = client.post(
        "/api/auth/login", json={"email": "new@example.com", "password": "wrong-password"}
    )
    assert obj_wrong_password.status_code == 401
    assert client.post(
        "/api/auth/register",
        json={"email": "new@example.com", "password": "secure-password-123", "first_name": "New", "last_name": "User"},
    ).status_code == 400


def test_expired_session_is_rejected(client):
    create_account(client, "expired@example.com")
    assert client.post(
        "/api/auth/login", json={"email": "expired@example.com", "password": "secure-password-123"}
    ).status_code == 200
    str_token = client.cookies.get(auth.str_cookie_name)
    with main.app.state.obj_engine.begin() as obj_connection:
        obj_connection.execute(
            update(tbl_sessions)
            .where(tbl_sessions.c.token_hash == auth.hash_token(str_token))
            .values(expires_at=auth.get_utc_now() - timedelta(minutes=1))
        )
    assert client.get("/api/auth/me").status_code == 401


def test_staff_creation_script_creates_admin_account(client, monkeypatch):
    lst_input = iter(["staff@example.com", "Sam", "Staff"])
    monkeypatch.setattr("builtins.input", lambda _str_prompt: next(lst_input))
    monkeypatch.setattr(create_staff, "getpass", lambda _str_prompt: "staff-password-123")
    monkeypatch.setattr(create_staff, "initialize_database", lambda: main.app.state.obj_engine)

    create_staff.main()

    with main.app.state.obj_engine.connect() as obj_connection:
        obj_user = obj_connection.execute(
            tbl_users.select().where(tbl_users.c.email == "staff@example.com")
        ).mappings().one()
    assert obj_user["is_admin"] is True
    assert auth.check_password("staff-password-123", obj_user["hashed_password"])
