from datetime import datetime, timezone
from hashlib import sha256
import hmac
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    AuditLog,
    CommentSubmission,
    Game,
    RewardLedger,
    RewardStatus,
    Review,
)


def grant_reward(db: Session, submission: CommentSubmission, review: Review) -> RewardLedger:
    existing = db.scalar(select(RewardLedger).where(RewardLedger.game_id == submission.game_id))
    if existing is not None:
        return existing

    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = day_start.replace(day=1)
    counted = (RewardStatus.FIXED.value, RewardStatus.HELD.value)
    daily = db.scalar(
        select(func.count(RewardLedger.id)).where(
            RewardLedger.user_id == submission.user_id,
            RewardLedger.status.in_(counted),
            RewardLedger.created_at >= day_start,
        )
    ) or 0
    monthly = db.scalar(
        select(func.count(RewardLedger.id)).where(
            RewardLedger.user_id == submission.user_id,
            RewardLedger.status.in_(counted),
            RewardLedger.created_at >= month_start,
        )
    ) or 0
    within_limit = daily < settings.reward_daily_limit and monthly < settings.reward_monthly_limit
    reward = RewardLedger(
        user_id=submission.user_id,
        game_id=submission.game_id,
        review_id=review.id,
        amount_yen=settings.reward_per_game_yen,
        status=RewardStatus.FIXED.value if within_limit else RewardStatus.HELD.value,
        reason="審査承認" if within_limit else "日次または月次上限超過のため保留",
    )
    db.add(reward)
    db.flush()
    db.add(
        AuditLog(
            actor_user_id=review.reviewer_id,
            action="reward.grant",
            target_type="reward_ledger",
            target_id=str(reward.id),
            details={"amount_yen": reward.amount_yen, "status": reward.status},
        )
    )
    return reward


def encrypt_bank_payload(payload: dict[str, str]) -> tuple[str, str]:
    from app.services.security import encrypt_secret

    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    encrypted = encrypt_secret(normalized)
    fingerprint = hmac.new(
        settings.bank_fingerprint_key.encode(),
        normalized.encode(),
        sha256,
    ).hexdigest()
    return encrypted, fingerprint
