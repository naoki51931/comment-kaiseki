from datetime import datetime, timezone
import csv
import io
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_admin
from app.config import settings
from app.database import get_db
from app.models import (
    AuditLog,
    BankAccount,
    Payout,
    PayoutStatus,
    RewardLedger,
    RewardStatus,
    User,
)
from app.schemas import RewardSummary
from app.services.rewards import encrypt_bank_payload
from app.services.security import decrypt_secret


router = APIRouter()


class BankAccountRequest(BaseModel):
    bank_code: str = Field(min_length=4, max_length=4, pattern=r"^\d+$")
    branch_code: str = Field(min_length=3, max_length=3, pattern=r"^\d+$")
    account_type: str = Field(pattern=r"^(ORDINARY|CURRENT)$")
    account_number: str = Field(min_length=7, max_length=7, pattern=r"^\d+$")
    account_holder: str = Field(min_length=1, max_length=100)


def require_rewards_enabled() -> None:
    if settings.reward_per_game_yen <= 0:
        raise HTTPException(status_code=404, detail="報酬・振込機能は現在利用できません。")


class PaymentRecordRequest(BaseModel):
    payment_reference: str = Field(min_length=1, max_length=255)


@router.get("/summary", response_model=RewardSummary)
def reward_summary(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> RewardSummary:
    fixed = db.scalar(
        select(func.coalesce(func.sum(RewardLedger.amount_yen), 0)).where(
            RewardLedger.user_id == user.id,
            RewardLedger.status == RewardStatus.FIXED.value,
            RewardLedger.payout_id.is_(None),
        )
    ) or 0
    pending = db.scalar(
        select(func.coalesce(func.sum(RewardLedger.amount_yen), 0)).where(
            RewardLedger.user_id == user.id,
            RewardLedger.status == RewardStatus.HELD.value,
        )
    ) or 0
    approved = db.scalar(
        select(func.count(RewardLedger.id)).where(
            RewardLedger.user_id == user.id,
            RewardLedger.status == RewardStatus.FIXED.value,
        )
    ) or 0
    return RewardSummary(
        rewards_enabled=settings.reward_per_game_yen > 0,
        reward_per_game_yen=settings.reward_per_game_yen,
        pending_yen=pending,
        fixed_yen=fixed,
        payout_available_yen=fixed if fixed >= settings.minimum_payout_yen else 0,
        approved_games=approved,
        minimum_payout_yen=settings.minimum_payout_yen,
    )


@router.put("/bank-account", status_code=204)
def save_bank_account(
    payload: BankAccountRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> None:
    require_rewards_enabled()
    encrypted, fingerprint = encrypt_bank_payload(payload.model_dump())
    account = db.scalar(select(BankAccount).where(BankAccount.user_id == user.id))
    if account is None:
        account = BankAccount(user_id=user.id, encrypted_payload=encrypted, fingerprint=fingerprint)
        db.add(account)
    else:
        account.encrypted_payload = encrypted
        account.fingerprint = fingerprint
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="bank_account.update",
            target_type="user",
            target_id=str(user.id),
            details={"fingerprint": fingerprint},
        )
    )
    db.commit()


@router.post("/payouts", status_code=201)
def request_payout(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, object]:
    require_rewards_enabled()
    if db.scalar(select(BankAccount.id).where(BankAccount.user_id == user.id)) is None:
        raise HTTPException(status_code=409, detail="振込口座を登録してください。")
    rewards = list(
        db.scalars(
            select(RewardLedger).where(
                RewardLedger.user_id == user.id,
                RewardLedger.status == RewardStatus.FIXED.value,
                RewardLedger.payout_id.is_(None),
            )
        )
    )
    amount = sum(item.amount_yen for item in rewards)
    if amount < settings.minimum_payout_yen:
        raise HTTPException(status_code=409, detail=f"振込可能額が最低金額の{settings.minimum_payout_yen:,}円に達していません。")
    payout = Payout(user_id=user.id, amount_yen=amount)
    db.add(payout)
    db.flush()
    for reward in rewards:
        reward.payout_id = payout.id
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="payout.request",
            target_type="payout",
            target_id=str(payout.id),
            details={"amount_yen": amount},
        )
    )
    db.commit()
    return {"id": payout.id, "amount_yen": amount, "status": payout.status}


@router.get("/payouts.csv")
def payout_csv(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
) -> Response:
    rows = list(db.scalars(select(Payout).where(Payout.status == PayoutStatus.REQUESTED.value)))
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["payout_id", "user_id", "amount_yen", "bank_code", "branch_code", "account_type", "account_number", "account_holder", "requested_at"])
    for item in rows:
        account = db.scalar(select(BankAccount).where(BankAccount.user_id == item.user_id))
        if account is None:
            continue
        bank = json.loads(decrypt_secret(account.encrypted_payload))
        writer.writerow([
            item.id, item.user_id, item.amount_yen, bank["bank_code"], bank["branch_code"],
            bank["account_type"], bank["account_number"], bank["account_holder"], item.requested_at.isoformat(),
        ])
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=payouts.csv"},
    )


@router.post("/payouts/{payout_id}/paid")
def mark_paid(
    payout_id: int,
    payload: PaymentRecordRequest,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(require_admin)],
) -> dict[str, object]:
    payout = db.get(Payout, payout_id)
    if payout is None:
        raise HTTPException(status_code=404, detail="振込申請が見つかりません。")
    if payout.status != PayoutStatus.REQUESTED.value:
        raise HTTPException(status_code=409, detail="申請中の振込だけを支払済みにできます。")
    payout.status = PayoutStatus.PAID.value
    payout.paid_at = datetime.now(timezone.utc)
    payout.payment_reference = payload.payment_reference
    db.add(
        AuditLog(
            actor_user_id=admin.id,
            action="payout.paid",
            target_type="payout",
            target_id=str(payout.id),
            details={"payment_reference": payload.payment_reference},
        )
    )
    db.commit()
    return {"id": payout.id, "status": payout.status}



class CancelRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=4000)


@router.post("/{reward_id}/cancel")
def cancel_reward(
    reward_id: int,
    payload: CancelRequest,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(require_admin)],
) -> dict[str, object]:
    reward = db.get(RewardLedger, reward_id)
    if reward is None:
        raise HTTPException(status_code=404, detail="報酬が見つかりません。")
    if reward.payout_id is not None or reward.status == RewardStatus.CANCELED.value:
        raise HTTPException(status_code=409, detail="この報酬は取消できません。")
    previous = reward.status
    reward.status = RewardStatus.CANCELED.value
    reward.reason = payload.reason
    db.add(AuditLog(
        actor_user_id=admin.id,
        action="reward.cancel",
        target_type="reward_ledger",
        target_id=str(reward.id),
        details={"from": previous, "reason": payload.reason},
    ))
    db.commit()
    return {"id": reward.id, "status": reward.status}


@router.post("/{reward_id}/release")
def release_reward(
    reward_id: int,
    payload: CancelRequest,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(require_admin)],
) -> dict[str, object]:
    reward = db.get(RewardLedger, reward_id)
    if reward is None:
        raise HTTPException(status_code=404, detail="報酬が見つかりません。")
    if reward.status != RewardStatus.HELD.value:
        raise HTTPException(status_code=409, detail="保留中の報酬だけを確定できます。")
    reward.status = RewardStatus.FIXED.value
    reward.reason = payload.reason
    db.add(AuditLog(
        actor_user_id=admin.id,
        action="reward.release",
        target_type="reward_ledger",
        target_id=str(reward.id),
        details={"reason": payload.reason},
    ))
    db.commit()
    return {"id": reward.id, "status": reward.status}
