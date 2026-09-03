from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin
from app.database import get_db
from app.models import (
    AccessCodeRedemption, AiAccessSubscription, AnalysisResult, AuditLog,
    CommentSubmission, CriticalPosition, Game, GameBranch, Review, ReviewStatus, User,
)
from app.schemas import BranchPositionRequest, GameVisibilityUpdate
from app.api.routes.games import branch_position, game_playback
from app.services.analysis import japanese_move_at, japanese_variation_at
from app.services.rewards import grant_reward
from app.services.subscriptions import has_ai_access


router = APIRouter()
PRO_LEVEL_MATCH_RATE = 70
PRO_LEVEL_MIN_MOVES = 20


def professional_level_match(game: Game, analyses: list[AnalysisResult]) -> tuple[int | None, int]:
    matches = 0
    count = 0
    for item in analyses:
        is_user_move = (item.move_number % 2 == 1) == (game.user_side == "SENTE")
        candidates = item.pre_move_variations or []
        if not is_user_move or item.move_number > len(game.usi_moves) or not candidates or not candidates[0].get("principal_variation"):
            continue
        count += 1
        matches += int(game.usi_moves[item.move_number - 1] == candidates[0]["principal_variation"][0])
    return (round(matches / count * 100), count) if count else (None, 0)
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


@router.get("/users")
def list_users(db: Annotated[Session, Depends(get_db)], _: Annotated[User, Depends(require_admin)]) -> list[dict[str, object]]:
    users = list(db.scalars(select(User).order_by(User.created_at.desc(), User.id.desc())))
    subscriptions = {item.user_id: item for item in db.scalars(select(AiAccessSubscription))}
    permanent_user_ids = set(db.scalars(select(AccessCodeRedemption.user_id)))
    game_counts = dict(db.execute(select(Game.user_id, func.count(Game.id)).group_by(Game.user_id)).all())
    return [{"id": user.id, "email": user.email, "email_verified": user.email_verified, "is_admin": user.is_admin, "created_at": user.created_at, "game_count": game_counts.get(user.id, 0), "ai_access_active": has_ai_access(db, user.id), "permanent_access": user.id in permanent_user_ids, "subscription_status": subscriptions[user.id].status if user.id in subscriptions else "NONE", "current_period_end": subscriptions[user.id].current_period_end if user.id in subscriptions else None} for user in users]


@router.get("/games")
def list_games(db: Annotated[Session, Depends(get_db)], _: Annotated[User, Depends(require_admin)]) -> list[dict[str, object]]:
    rows = db.execute(select(Game, User.email).join(User, User.id == Game.user_id).order_by(Game.created_at.desc(), Game.id.desc())).all()
    analyses_by_game: dict[int, list[AnalysisResult]] = {}
    for analysis in db.scalars(select(AnalysisResult).order_by(AnalysisResult.game_id, AnalysisResult.move_number)):
        analyses_by_game.setdefault(analysis.game_id, []).append(analysis)
    result = []
    for game, email in rows:
        match_rate, analyzed_moves = professional_level_match(game, analyses_by_game.get(game.id, []))
        result.append({"id": game.id, "user_id": game.user_id, "user_email": email, "original_filename": game.original_filename, "event_name": game.event_name, "sente_name": game.sente_name, "gote_name": game.gote_name, "played_at": game.played_at, "user_side": game.user_side, "is_public": game.is_public, "move_count": game.move_count, "analysis_status": game.analysis_status, "critical_position_count": game.critical_position_count, "created_at": game.created_at, "best_move_match_rate": match_rate, "match_rate_analyzed_moves": analyzed_moves, "professional_level_deletion_candidate": analyzed_moves >= PRO_LEVEL_MIN_MOVES and match_rate is not None and match_rate >= PRO_LEVEL_MATCH_RATE, "professional_name_suspected": game.professional_name_suspected, "professional_name_matches": game.professional_name_matches})
    return result


@router.get("/games/{game_id}/playback")
def admin_game_playback(game_id: int, db: Annotated[Session, Depends(get_db)], _: Annotated[User, Depends(require_admin)]) -> dict[str, object]:
    game = db.get(Game, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="棋譜が見つかりません。")
    owner = db.get(User, game.user_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="投稿ユーザーが見つかりません。")
    return game_playback(game_id=game_id, db=db, user=owner)


@router.patch("/games/{game_id}/visibility")
def update_game_visibility(
    game_id: int,
    payload: GameVisibilityUpdate,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(require_admin)],
) -> dict[str, object]:
    game = db.get(Game, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="棋譜が見つかりません。")
    previous = game.is_public
    game.is_public = payload.is_public
    db.add(AuditLog(
        actor_user_id=admin.id,
        action="admin.game.visibility.update",
        target_type="game",
        target_id=str(game.id),
        details={"from": previous, "to": game.is_public, "owner_user_id": game.user_id},
    ))
    db.commit()
    return {"id": game.id, "is_public": game.is_public}


@router.get("/games/{game_id}/branches")
def admin_game_branches(game_id: int, db: Annotated[Session, Depends(get_db)], _: Annotated[User, Depends(require_admin)]) -> list[dict[str, object]]:
    game = db.get(Game, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="棋譜が見つかりません。")
    branches = list(db.scalars(select(GameBranch).where(GameBranch.game_id == game_id).order_by(GameBranch.id)))
    return [{"id": branch.id, "name": branch.name, "base_move_number": branch.base_move_number, "usi_moves": branch.usi_moves, "japanese_moves": branch.japanese_moves, "board": branch_position(game, BranchPositionRequest(move_number=branch.base_move_number, moves=branch.usi_moves)).board} for branch in branches]


def review_snapshot_for_display(snapshot: dict | None, game: Game | None) -> dict | None:
    """古い提出スナップショットも日本語指し手・全3回答の形へ整える。"""
    if snapshot is None:
        return None
    positions = [dict(position) for position in snapshot.get("positions", [])]
    for position in positions:
        if game is None:
            continue
        try:
            position["move"] = japanese_move_at(
                game.initial_sfen, game.usi_moves, int(position["move_number"])
            )
        except (KeyError, TypeError, ValueError):
            pass

    existing_answers = {
        (answer.get("critical_position_id"), answer.get("question_number")): answer
        for answer in snapshot.get("answers", [])
    }
    answers = []
    for position in positions:
        for question_number in range(1, 4):
            answer = existing_answers.get((position.get("id"), question_number))
            answers.append({
                "critical_position_id": position.get("id"),
                "question_number": question_number,
                "answer_text": "" if answer is None else answer.get("answer_text", ""),
            })
    return {**snapshot, "positions": positions, "answers": answers}


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
    games = {
        game.id: game
        for game in db.scalars(select(Game).where(Game.id.in_([item.game_id for item in submissions])))
    } if submissions else {}
    return [
        {
            "id": item.id,
            "game_id": item.game_id,
            "user_id": item.user_id,
            "status": item.review_status,
            "submitted_at": item.submitted_at,
            "snapshot": review_snapshot_for_display(item.submitted_snapshot, games.get(item.game_id)),
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
        "snapshot": review_snapshot_for_display(submission.submitted_snapshot, game),
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
                "principal_variation": japanese_variation_at(game.initial_sfen, game.usi_moves, position.move_number, analyses[position.move_number].principal_variation)
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
