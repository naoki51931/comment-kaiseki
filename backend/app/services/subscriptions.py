from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AccessCodeRedemption, AiAccessSubscription


ACTIVE_STATUSES = {"active", "trialing"}


def has_permanent_access(db: Session, user_id: int) -> bool:
    return db.scalar(
        select(AccessCodeRedemption.id).where(AccessCodeRedemption.user_id == user_id)
    ) is not None


def has_ai_access(db: Session, user_id: int) -> bool:
    if has_permanent_access(db, user_id):
        return True
    subscription = db.scalar(select(AiAccessSubscription).where(AiAccessSubscription.user_id == user_id))
    if subscription is None or subscription.status not in ACTIVE_STATUSES:
        return False
    if subscription.current_period_end is None:
        return False
    period_end = subscription.current_period_end
    if period_end.tzinfo is None:
        period_end = period_end.replace(tzinfo=timezone.utc)
    return period_end > datetime.now(timezone.utc)


def unix_datetime(value: int | None) -> datetime | None:
    return datetime.fromtimestamp(value, tz=timezone.utc) if value else None
