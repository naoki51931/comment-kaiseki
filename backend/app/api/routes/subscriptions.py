from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
import stripe

from app.api.dependencies import get_current_user
from app.config import settings
from app.database import get_db
from app.models import AccessCode, AccessCodeRedemption, AiAccessSubscription, AuditLog, User
from app.services.subscriptions import ACTIVE_STATUSES, has_ai_access, has_permanent_access, unix_datetime
from app.schemas import AccessCodeRedeemRequest, AccessCodeRedeemResponse


router = APIRouter()


def stripe_ready() -> None:
    if not settings.stripe_secret_key or not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Stripe決済が設定されていません。")
    stripe.api_key = settings.stripe_secret_key


@router.get("/status")
def subscription_status(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, object]:
    subscription = db.scalar(select(AiAccessSubscription).where(AiAccessSubscription.user_id == user.id))
    permanent_access = has_permanent_access(db, user.id)
    return {
        "active": has_ai_access(db, user.id),
        "permanent_access": permanent_access,
        "status": "PERMANENT" if permanent_access else subscription.status if subscription else "NONE",
        "current_period_end": subscription.current_period_end if subscription else None,
        "monthly_price_yen": settings.ai_access_monthly_price_yen,
        "trial_days": settings.ai_access_trial_days,
        "trial_available": subscription is None or subscription.stripe_subscription_id is None,
        "test_toggle_available": bool(settings.ai_access_test_user_email) and user.email.lower() == settings.ai_access_test_user_email,
    }


@router.post("/redeem-code", response_model=AccessCodeRedeemResponse)
def redeem_access_code(
    payload: AccessCodeRedeemRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> AccessCodeRedeemResponse:
    existing = db.scalar(
        select(AccessCodeRedemption).where(AccessCodeRedemption.user_id == user.id)
    )
    if existing is not None:
        return AccessCodeRedeemResponse(
            permanent_access=True, message="永久無料プランはすでに有効です。"
        )
    access_code = db.scalar(
        select(AccessCode).where(
            AccessCode.code == payload.code, AccessCode.is_active.is_(True)
        )
    )
    if access_code is None:
        raise HTTPException(status_code=422, detail="コードが正しくないか、現在利用できません。")
    db.add(AccessCodeRedemption(access_code_id=access_code.id, user_id=user.id))
    db.add(AuditLog(
        actor_user_id=user.id, action="ACCESS_CODE_REDEEMED",
        target_type="access_code", target_id=str(access_code.id),
        details={"permanent_access": True},
    ))
    db.commit()
    return AccessCodeRedeemResponse(
        permanent_access=True, message="永久無料プランが有効になりました。"
    )


@router.post("/test-toggle")
def toggle_test_subscription(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, object]:
    if not settings.ai_access_test_user_email or user.email.lower() != settings.ai_access_test_user_email:
        raise HTTPException(status_code=403, detail="この課金切替はテスト対象ユーザー専用です。")
    subscription = db.scalar(select(AiAccessSubscription).where(AiAccessSubscription.user_id == user.id))
    if subscription is None:
        subscription = AiAccessSubscription(user_id=user.id, stripe_subscription_id=f"manual_{user.id}")
        db.add(subscription)
    next_active = not has_ai_access(db, user.id)
    subscription.status = "active" if next_active else "canceled"
    subscription.current_period_end = (
        datetime.now(timezone.utc) + timedelta(days=30) if next_active else datetime.now(timezone.utc)
    )
    db.commit()
    return {"active": next_active, "status": subscription.status}


@router.post("/checkout", status_code=201)
def create_checkout(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, str]:
    stripe_ready()
    subscription = db.scalar(select(AiAccessSubscription).where(AiAccessSubscription.user_id == user.id))
    trial_available = subscription is None or subscription.stripe_subscription_id is None
    if has_ai_access(db, user.id):
        raise HTTPException(status_code=409, detail="AI解説プランは契約済みです。")
    base_url = settings.public_base_url or "http://localhost"
    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer_email=user.email,
            client_reference_id=str(user.id),
            metadata={"user_id": str(user.id), "product": "ai_comment_access"},
            subscription_data={
                "metadata": {"user_id": str(user.id), "product": "ai_comment_access"},
                **({"trial_period_days": settings.ai_access_trial_days} if trial_available else {}),
            },
            line_items=[{
                "price_data": {
                    "currency": "jpy",
                    "unit_amount": settings.ai_access_monthly_price_yen,
                    "recurring": {"interval": "month"},
                    "product_data": {"name": "棋譜AI解説プラン"},
                },
                "quantity": 1,
            }],
            success_url=f"{base_url}/?subscription=success",
            cancel_url=f"{base_url}/?subscription=cancel",
        )
    except stripe.StripeError as exc:
        raise HTTPException(status_code=502, detail="決済画面を作成できませんでした。") from exc
    if subscription is None:
        subscription = AiAccessSubscription(user_id=user.id)
        db.add(subscription)
    subscription.checkout_session_id = session.id
    subscription.status = "PENDING"
    db.commit()
    return {"checkout_url": session.url}


@router.post("/portal", status_code=201)
def create_billing_portal(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, str]:
    stripe_ready()
    subscription = db.scalar(select(AiAccessSubscription).where(AiAccessSubscription.user_id == user.id))
    if subscription is None or not subscription.stripe_customer_id:
        raise HTTPException(status_code=409, detail="管理できる月額契約がありません。")
    base_url = settings.public_base_url or "http://localhost"
    try:
        session = stripe.billing_portal.Session.create(
            customer=subscription.stripe_customer_id,
            return_url=base_url,
        )
    except stripe.StripeError as exc:
        raise HTTPException(status_code=502, detail="契約管理画面を作成できませんでした。") from exc
    return {"portal_url": session.url}


def sync_subscription(db: Session, stripe_subscription: object, fallback_user_id: str | None = None) -> None:
    subscription_id = str(stripe_subscription.get("id"))
    metadata = stripe_subscription.get("metadata") or {}
    user_id_text = metadata.get("user_id") or fallback_user_id
    if not user_id_text or not str(user_id_text).isdigit():
        return
    user_id = int(user_id_text)
    stored = db.scalar(select(AiAccessSubscription).where(AiAccessSubscription.user_id == user_id))
    if stored is None:
        stored = AiAccessSubscription(user_id=user_id)
        db.add(stored)
    stored.stripe_subscription_id = subscription_id
    stored.stripe_customer_id = str(stripe_subscription.get("customer") or "") or None
    stored.status = str(stripe_subscription.get("status") or "PENDING")
    stored.current_period_end = unix_datetime(stripe_subscription.get("current_period_end"))


@router.post("/webhook", status_code=204)
async def stripe_webhook(request: Request, db: Annotated[Session, Depends(get_db)]) -> None:
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Stripe Webhookが設定されていません。")
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, signature, settings.stripe_webhook_secret)
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise HTTPException(status_code=400, detail="Webhook署名が無効です。") from exc
    event_type = event["type"]
    obj = event["data"]["object"]
    if event_type == "checkout.session.completed":
        if obj.get("payment_status") not in {"paid", "no_payment_required"}:
            return
        if obj.get("amount_total") not in {0, settings.ai_access_monthly_price_yen} or obj.get("currency") != "jpy":
            raise HTTPException(status_code=400, detail="決済金額または通貨が一致しません。")
        subscription_id = obj.get("subscription")
        if subscription_id:
            stripe.api_key = settings.stripe_secret_key
            remote = stripe.Subscription.retrieve(subscription_id)
            sync_subscription(db, remote, (obj.get("metadata") or {}).get("user_id"))
            stored = db.scalar(select(AiAccessSubscription).where(
                AiAccessSubscription.checkout_session_id == obj.get("id")
            ))
            if stored is not None:
                stored.checkout_session_id = obj.get("id")
    elif event_type in {"customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"}:
        sync_subscription(db, obj)
    else:
        return
    db.commit()
