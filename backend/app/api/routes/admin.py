from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin
from app.database import get_db
from app.models import AnalysisResult, AuditLog, CommentSubmission, CriticalPosition, Game, Review, ReviewStatus, User
from app.services.rewards import grant_reward


router = APIRouter()
ALLOWED_TRANSITIONS = {
    ReviewStatus.UNDER_REVIEW.value: {
        ReviewStatus.APPROVED.value,
        ReviewStatus.CHANGES_REQUESTED.value,
        ReviewStatus.REJECTED.value,
    },
    ReviewStatus.CHANGES_REQUESTED.value: {ReviewStatus.UNDER_REVIEW.value},
}


class ReviewRequest(BaseModel):
    status: ReviewStatus
    reason: str = Field(min_length=1, max_length=4000)
    quality_tags: list[str] = Field(default_factory=list, max_length=20)


@router.get("/reviews")
def list_reviews(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
) -> list[dict[str, object]]:
    submissions = list(
        db.scalars(
            select(CommentSubmission)
            .where(CommentSubmission.submitted_at.is_not(None))
            .order_by(CommentSubmission.submitted_at)
        )
    )
    return [
        {
            "id": item.id,
            "game_id": item.game_id,
            "user_id": item.user_id,
            "status": item.review_status,
            "submitted_at": item.submitted_at,
            "snapshot": item.submitted_snapshot,
        }
        for item in submissions
    ]


@router.get("/reviews/{submission_id}")
def review_detail(
    submission_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
) -> dict[str, object]:
    submission = db.get(CommentSubmission, submission_id)
    if submission is None or submission.submitted_at is None:
        raise HTTPException(status_code=404, detail="審査対象が見つかりません。")
    game = db.get(Game, submission.game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="棋譜が見つかりません。")
    analyses = {
        item.move_number: item
        for item in db.scalars(select(AnalysisResult).where(AnalysisResult.game_id == game.id))
    }
    positions = list(db.scalars(
        select(CriticalPosition)
        .where(CriticalPosition.game_id == game.id)
        .order_by(CriticalPosition.move_number)
    ))
    return {
        "id": submission.id,
        "status": submission.review_status,
        "submitted_at": submission.submitted_at,
        "snapshot": submission.submitted_snapshot,
        "game": {
            "id": game.id,
            "filename": game.original_filename,
            "played_at": game.played_at,
            "user_side": game.user_side,
        },
        "positions": [
            {
                "id": position.id,
                "move_number": position.move_number,
                "move": position.japanese_move,
                "evaluation_before": position.evaluation_before,
                "evaluation_after": position.evaluation_after,
                "selection_reason": position.selection_reason,
                "principal_variation": analyses[position.move_number].principal_variation
                if position.move_number in analyses else [],
            }
            for position in positions
        ],
    }


@router.post("/reviews/{submission_id}")
def review_submission(
    submission_id: int,
    payload: ReviewRequest,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(require_admin)],
) -> dict[str, object]:
    submission = db.get(CommentSubmission, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="審査対象が見つかりません。")
    destination = payload.status.value
    if destination not in ALLOWED_TRANSITIONS.get(submission.review_status, set()):
        raise HTTPException(status_code=409, detail="許可されていない審査状態遷移です。")

    previous = submission.review_status
    submission.review_status = destination
    review = Review(
        submission_id=submission.id,
        reviewer_id=admin.id,
        from_status=previous,
        to_status=destination,
        reason=payload.reason,
        quality_tags=payload.quality_tags,
    )
    db.add(review)
    db.flush()
    if destination == ReviewStatus.APPROVED.value:
        grant_reward(db, submission, review)
    db.add(
        AuditLog(
            actor_user_id=admin.id,
            action="review.transition",
            target_type="comment_submission",
            target_id=str(submission.id),
            details={"from": previous, "to": destination, "review_id": review.id},
        )
    )
    db.commit()
    return {"submission_id": submission.id, "status": destination, "review_id": review.id}
