from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.database import get_db
from app.models import (
    AiComment,
    AiCommentFeedback,
    AuditLog,
    CommentAnswer,
    CommentSubmission,
    CriticalPosition,
    Game,
    ReviewStatus,
    User,
)
from app.services.ai_comments import generate_ai_comments, text_diff
from app.services.subscriptions import has_ai_access
from app.schemas import (
    AiCommentUpdate,
    AiCommentView,
    CommentAnswerView,
    CommentDraftRequest,
    CommentSubmissionView,
    SubmitResponse,
)


router = APIRouter()


def owned_game(db: Session, game_id: int, user_id: int) -> Game:
    game = db.get(Game, game_id)
    if game is None or game.user_id != user_id:
        raise HTTPException(status_code=404, detail="棋譜が見つかりません。")
    return game


def get_or_create_submission(db: Session, game_id: int, user_id: int) -> CommentSubmission:
    submission = db.scalar(select(CommentSubmission).where(CommentSubmission.game_id == game_id))
    if submission is None:
        submission = CommentSubmission(game_id=game_id, user_id=user_id)
        db.add(submission)
        db.flush()
    return submission


def submission_view(db: Session, submission: CommentSubmission) -> CommentSubmissionView:
    answers = list(
        db.scalars(
            select(CommentAnswer)
            .where(CommentAnswer.submission_id == submission.id)
            .order_by(CommentAnswer.critical_position_id, CommentAnswer.question_number)
        )
    )
    return CommentSubmissionView(
        id=submission.id,
        game_id=submission.game_id,
        review_status=submission.review_status,
        submitted_at=submission.submitted_at,
        answers=[CommentAnswerView.model_validate(item) for item in answers],
    )


@router.get("/{game_id}/comments", response_model=CommentSubmissionView)
def get_comments(
    game_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> CommentSubmissionView:
    owned_game(db, game_id, user.id)
    submission = get_or_create_submission(db, game_id, user.id)
    db.commit()
    return submission_view(db, submission)


@router.put("/{game_id}/comments/draft", response_model=CommentSubmissionView)
def save_draft(
    game_id: int,
    payload: CommentDraftRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> CommentSubmissionView:
    owned_game(db, game_id, user.id)
    submission = get_or_create_submission(db, game_id, user.id)
    if submission.submitted_at is not None:
        raise HTTPException(status_code=409, detail="提出済みコメントは変更できません。")

    valid_position_ids = set(
        db.scalars(select(CriticalPosition.id).where(CriticalPosition.game_id == game_id))
    )
    keys: set[tuple[int, int]] = set()
    for answer in payload.answers:
        if answer.critical_position_id not in valid_position_ids:
            raise HTTPException(status_code=422, detail="対象局面がこの棋譜に含まれません。")
        key = (answer.critical_position_id, answer.question_number)
        if key in keys:
            raise HTTPException(status_code=422, detail="同じ質問への回答が重複しています。")
        keys.add(key)

    db.execute(delete(CommentAnswer).where(CommentAnswer.submission_id == submission.id))
    for answer in payload.answers:
        if not answer.answer_text.strip():
            continue
        db.add(
            CommentAnswer(
                submission_id=submission.id,
                critical_position_id=answer.critical_position_id,
                question_number=answer.question_number,
                answer_text=answer.answer_text.strip(),
            )
        )
    db.commit()
    return submission_view(db, submission)


@router.post("/{game_id}/comments/submit", response_model=SubmitResponse)
def submit_comments(
    game_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> SubmitResponse:
    owned_game(db, game_id, user.id)
    submission = get_or_create_submission(db, game_id, user.id)
    if submission.submitted_at is not None:
        raise HTTPException(status_code=409, detail="コメントは提出済みです。")

    required_ids = set(
        db.scalars(
            select(CriticalPosition.id).where(
                CriticalPosition.game_id == game_id,
                CriticalPosition.required.is_(True),
            )
        )
    )
    answers = list(db.scalars(select(CommentAnswer).where(CommentAnswer.submission_id == submission.id)))
    answered = {
        (item.critical_position_id, item.question_number)
        for item in answers
        if item.answer_text.strip()
    }
    if not required_ids:
        raise HTTPException(status_code=409, detail="重要局面の解析が完了していません。")
    if not answered:
        raise HTTPException(status_code=422, detail="コメントを1つ以上入力してください。")

    now = datetime.now(timezone.utc)
    snapshot = {
        "game_id": game_id,
        "positions": [
            {
                "id": position.id,
                "move_number": position.move_number,
                "move": position.japanese_move,
            }
            for position in db.scalars(
                select(CriticalPosition).where(CriticalPosition.game_id == game_id)
            )
        ],
        "answers": [
            {
                "critical_position_id": item.critical_position_id,
                "question_number": item.question_number,
                "answer_text": item.answer_text,
            }
            for item in answers
        ],
        "submitted_at": now.isoformat(),
    }
    submission.submitted_snapshot = snapshot
    submission.submitted_at = now
    submission.review_status = ReviewStatus.UNDER_REVIEW.value
    generate_ai_comments(db, submission)
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="comments.submit",
            target_type="comment_submission",
            target_id=str(submission.id),
            details={"game_id": game_id},
        )
    )
    db.commit()
    return SubmitResponse(id=submission.id, review_status=submission.review_status, submitted_at=now)


@router.get("/{game_id}/ai-comments", response_model=list[AiCommentView])
def get_ai_comments(
    game_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> list[AiComment]:
    owned_game(db, game_id, user.id)
    submission = db.scalar(select(CommentSubmission).where(CommentSubmission.game_id == game_id))
    if submission is None or submission.submitted_at is None:
        raise HTTPException(status_code=409, detail="Comments must be submitted first.")
    if not has_ai_access(db, user.id):
        raise HTTPException(status_code=403, detail="AI plan is required.")
    comments = list(db.scalars(select(AiComment).join(CriticalPosition, CriticalPosition.id == AiComment.critical_position_id).where(CriticalPosition.game_id == game_id).order_by(AiComment.move_number)))
    if not comments:
        comments = generate_ai_comments(db, submission)
        db.commit()
    return comments


@router.put("/{game_id}/ai-comments/{comment_id}", response_model=AiCommentView)
def update_ai_comment(
    game_id: int,
    comment_id: int,
    payload: AiCommentUpdate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> AiComment:
    owned_game(db, game_id, user.id)
    if not has_ai_access(db, user.id):
        raise HTTPException(status_code=403, detail="AI plan is required.")
    comment = db.scalar(select(AiComment).join(CriticalPosition, CriticalPosition.id == AiComment.critical_position_id).where(AiComment.id == comment_id, CriticalPosition.game_id == game_id))
    if comment is None:
        raise HTTPException(status_code=404, detail="AI comment was not found.")
    corrected = payload.text.strip()
    if corrected != comment.current_text:
        before = comment.current_text
        db.add(AiCommentFeedback(ai_comment_id=comment.id, user_id=user.id, move_number=comment.move_number, before_text=before, after_text=corrected, diff=text_diff(before, corrected)))
        comment.current_text = corrected
        db.add(AuditLog(actor_user_id=user.id, action="ai_comment.correct", target_type="ai_comment", target_id=str(comment.id), details={"game_id": game_id, "move_number": comment.move_number}))
        db.commit()
        db.refresh(comment)
    return comment
