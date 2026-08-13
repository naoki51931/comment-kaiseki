from collections.abc import Generator
from hashlib import sha256

import jwt

import pyotp
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import RefreshToken, User
from app.services.security import encrypt_secret, hash_password


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
        access_payload = jwt.decode(tokens["access_token"], options={"verify_signature": False})
        assert 17990 <= access_payload["exp"] - access_payload["iat"] <= 18010
        with sessions() as db:
            stored_refresh = db.query(RefreshToken).filter_by(token_hash=sha256(tokens["refresh_token"].encode()).hexdigest()).one()
            refresh_lifetime = (stored_refresh.expires_at - stored_refresh.created_at).total_seconds()
            assert 17990 <= refresh_lifetime <= 18010
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
        assert me.status_code == 200
        assert me.json()["email"] == "new@example.com"
        refreshed = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert refreshed.status_code == 200
        assert refreshed.json()["refresh_token"] != tokens["refresh_token"]
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def test_admin_privileges_require_mfa_for_each_login_session() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    secret = pyotp.random_base32()
    with sessions() as db:
        db.add_all([
            User(
                email="admin@example.com",
                password_hash=hash_password("very-secure-password"),
                email_verified=True,
                is_admin=True,
                mfa_enabled=True,
                mfa_secret_encrypted=encrypt_secret(secret),
            ),
            User(
                email="member@example.com",
                password_hash=hash_password("very-secure-password"),
                email_verified=True,
            ),
        ])
        db.commit()

    def override_db() -> Generator[Session, None, None]:
        with sessions() as session:
            yield session

    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        normal_admin_login = client.post(
            "/api/auth/login",
            json={"email": "admin@example.com", "password": "very-secure-password"},
        )
        normal_headers = {"Authorization": f"Bearer {normal_admin_login.json()['access_token']}"}
        assert client.get("/api/auth/me", headers=normal_headers).json()["is_admin"] is False
        assert client.get("/api/admin/reviews", headers=normal_headers).status_code == 403

        mfa_login = client.post(
            "/api/auth/login",
            json={
                "email": "admin@example.com",
                "password": "very-secure-password",
                "mfa_code": pyotp.TOTP(secret).now(),
            },
        )
        mfa_headers = {"Authorization": f"Bearer {mfa_login.json()['access_token']}"}
        assert client.get("/api/auth/me", headers=mfa_headers).json()["is_admin"] is True
        assert client.get("/api/admin/reviews", headers=mfa_headers).status_code == 200

        refreshed = client.post(
            "/api/auth/refresh", json={"refresh_token": mfa_login.json()["refresh_token"]}
        )
        refreshed_headers = {"Authorization": f"Bearer {refreshed.json()['access_token']}"}
        assert client.get("/api/auth/me", headers=refreshed_headers).json()["is_admin"] is True

        member_login = client.post(
            "/api/auth/login",
            json={
                "email": "member@example.com",
                "password": "very-secure-password",
                "mfa_code": "123456",
            },
        )
        member_headers = {"Authorization": f"Bearer {member_login.json()['access_token']}"}
        assert client.get("/api/auth/me", headers=member_headers).json()["is_admin"] is False
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
