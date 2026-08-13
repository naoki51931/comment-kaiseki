from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


def test_register_verify_login_and_access_token() -> None:
    from app.config import settings
    settings.expose_verification_token = True
    settings.email_delivery_enabled = False
    settings.email_resend_cooldown_seconds = 0
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)

    def override_db() -> Generator[Session, None, None]:
        with sessions() as session:
            yield session

    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        registered = client.post(
            "/api/auth/register",
            json={"email": "new@example.com", "password": "very-secure-password"},
        )
        assert registered.status_code == 201
        token = registered.json()["verification_token"]
        unverified_login = client.post(
            "/api/auth/login",
            json={"email": "new@example.com", "password": "very-secure-password"},
        )
        assert unverified_login.status_code == 403
        assert unverified_login.json()["detail"] == "メール認証を完了してください。"
        resent = client.post("/api/auth/resend-verification", json={"email": "new@example.com"})
        assert resent.status_code == 200
        new_token = resent.json()["verification_token"]
        assert new_token != token
        assert client.post("/api/auth/verify-email", json={"token": token}).status_code == 422
        assert client.post("/api/auth/verify-email", json={"token": new_token}).status_code == 204
        logged_in = client.post(
            "/api/auth/login",
            json={"email": "new@example.com", "password": "very-secure-password"},
        )
        assert logged_in.status_code == 200
        tokens = logged_in.json()
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
        assert me.status_code == 200
        assert me.json()["email"] == "new@example.com"
        refreshed = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert refreshed.status_code == 200
        assert refreshed.json()["refresh_token"] != tokens["refresh_token"]
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
