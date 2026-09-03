from pathlib import Path

from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user
from app.config import settings
from app.main import app
from app.models import User


def test_android_apk_is_available_only_to_allowed_user(tmp_path: Path) -> None:
    apk = tmp_path / "app.apk"
    apk.write_bytes(b"test-apk")
    previous_email = settings.android_apk_allowed_email
    previous_path = settings.android_apk_path
    settings.android_apk_allowed_email = "allowed@example.test"
    settings.android_apk_path = apk
    try:
        app.dependency_overrides.clear()
        app.dependency_overrides[get_current_user] = lambda: User(
            id=99, email="allowed@example.test", email_verified=True
        )
        with TestClient(app) as client:
            response = client.get("/api/downloads/android")
            assert response.status_code == 200
            assert response.content == b"test-apk"
            assert response.headers["content-type"] == "application/vnd.android.package-archive"

            app.dependency_overrides[get_current_user] = lambda: User(
                id=100, email="other@example.test", email_verified=True
            )
            assert client.get("/api/downloads/android").status_code == 403
    finally:
        app.dependency_overrides.clear()
        settings.android_apk_allowed_email = previous_email
        settings.android_apk_path = previous_path
