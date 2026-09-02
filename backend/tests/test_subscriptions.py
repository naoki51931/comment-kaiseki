from types import SimpleNamespace

import pytest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.subscriptions import create_checkout, redeem_access_code, sync_subscription, toggle_test_subscription
from app.config import settings
from app.database import Base
from app.models import AccessCode, AccessCodeRedemption, AiAccessSubscription, User
from app.services.subscriptions import has_ai_access
from app.schemas import AccessCodeRedeemRequest


def test_subscription_access_follows_stripe_status_and_period() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with sessions() as db:
        user = User(email="subscriber@example.test", email_verified=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        assert has_ai_access(db, user.id) is False

        period_end = datetime.now(timezone.utc) + timedelta(days=30)
        sync_subscription(db, {
            "id": "sub_active",
            "customer": "cus_test",
            "status": "active",
            "current_period_end": int(period_end.timestamp()),
            "metadata": {"user_id": str(user.id)},
        })
        db.commit()
        assert has_ai_access(db, user.id) is True

        sync_subscription(db, {
            "id": "sub_active",
            "customer": "cus_test",
            "status": "canceled",
            "current_period_end": int(period_end.timestamp()),
            "metadata": {"user_id": str(user.id)},
        })
        db.commit()
        assert has_ai_access(db, user.id) is False
        stored = db.query(AiAccessSubscription).filter_by(user_id=user.id).one()
        assert stored.stripe_customer_id == "cus_test"
    Base.metadata.drop_all(engine)


def test_expired_subscription_has_no_access() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with sessions() as db:
        user = User(email="expired@example.test", email_verified=True)
        db.add(user)
        db.flush()
        db.add(AiAccessSubscription(
            user_id=user.id,
            stripe_subscription_id="sub_expired",
            status="active",
            current_period_end=datetime.now(timezone.utc) - timedelta(seconds=1),
        ))
        db.commit()
        assert has_ai_access(db, user.id) is False
    Base.metadata.drop_all(engine)


def test_checkout_includes_30_day_free_trial(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    captured: dict[str, object] = {}

    def fake_create(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(id="cs_trial", url="https://checkout.stripe.test/trial")

    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test")
    monkeypatch.setattr(settings, "ai_access_trial_days", 30)
    monkeypatch.setattr("app.api.routes.subscriptions.stripe.checkout.Session.create", fake_create)
    with sessions() as db:
        user = User(email="trial.test", email_verified=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        response = create_checkout(db=db, user=user)
        assert response["checkout_url"] == "https://checkout.stripe.test/trial"
        assert captured["mode"] == "subscription"
        assert captured["subscription_data"]["trial_period_days"] == 30
    Base.metadata.drop_all(engine)


def test_checkout_trial_is_only_available_once(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    captured: dict[str, object] = {}
    def fake_create(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(id="cs_repeat", url="https://checkout.stripe.test/repeat")
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test")
    monkeypatch.setattr("app.api.routes.subscriptions.stripe.checkout.Session.create", fake_create)
    with sessions() as db:
        user = User(email="repeat.test", email_verified=True)
        db.add(user); db.commit(); db.refresh(user)
        db.add(AiAccessSubscription(user_id=user.id, stripe_subscription_id="sub_canceled", status="canceled"))
        db.commit()
        create_checkout(db=db, user=user)
        assert "trial_period_days" not in captured["subscription_data"]
    Base.metadata.drop_all(engine)


def test_manual_toggle_is_limited_to_configured_user(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    target_email = "toggle.test"
    monkeypatch.setattr(settings, "ai_access_test_user_email", target_email)
    with sessions() as db:
        target = User(email=target_email, email_verified=True)
        other = User(email="other.test", email_verified=True)
        db.add_all([target, other])
        db.commit()
        db.refresh(target)
        db.refresh(other)

        enabled = toggle_test_subscription(db=db, user=target)
        assert enabled["active"] is True
        assert has_ai_access(db, target.id) is True
        disabled = toggle_test_subscription(db=db, user=target)
        assert disabled["active"] is False
        assert has_ai_access(db, target.id) is False
        with pytest.raises(HTTPException) as denied:
            toggle_test_subscription(db=db, user=other)
        assert denied.value.status_code == 403
    Base.metadata.drop_all(engine)


def test_access_codes_grant_permanent_ai_access() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with sessions() as db:
        support = AccessCode(code="サポートホーム", description="support", is_active=True)
        hannya = AccessCode(code="般若", description="support", is_active=True)
        first = User(email="first-code@example.test", email_verified=True)
        second = User(email="second-code@example.test", email_verified=True)
        db.add_all([support, hannya, first, second])
        db.commit()
        db.refresh(first)
        db.refresh(second)

        first_result = redeem_access_code(
            payload=AccessCodeRedeemRequest(code=" サポートホーム "), db=db, user=first
        )
        second_result = redeem_access_code(
            payload=AccessCodeRedeemRequest(code="般若"), db=db, user=second
        )

        assert first_result.permanent_access is True
        assert second_result.permanent_access is True
        assert has_ai_access(db, first.id) is True
        assert has_ai_access(db, second.id) is True
        assert db.query(AccessCodeRedemption).count() == 2

        repeated = redeem_access_code(
            payload=AccessCodeRedeemRequest(code="anything"), db=db, user=first
        )
        assert repeated.message == "永久無料プランはすでに有効です。"
    Base.metadata.drop_all(engine)


def test_invalid_or_inactive_access_code_is_rejected() -> None:
    from fastapi import HTTPException

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with sessions() as db:
        user = User(email="invalid-code@example.test", email_verified=True)
        db.add_all([user, AccessCode(code="停止中", is_active=False)])
        db.commit()
        db.refresh(user)
        for code in ("存在しない", "停止中"):
            with pytest.raises(HTTPException) as denied:
                redeem_access_code(payload=AccessCodeRedeemRequest(code=code), db=db, user=user)
            assert denied.value.status_code == 422
        assert has_ai_access(db, user.id) is False
    Base.metadata.drop_all(engine)
