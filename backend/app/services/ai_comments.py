from difflib import SequenceMatcher

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AiComment, AiCommentFeedback, CommentAnswer, CommentSubmission, CriticalPosition, GameSkillAnalysis

MODEL_VERSION = "comment-retrieval-v2-skill-weighted"
HISTORICAL_ANSWER_LIMIT = 6

def text_diff(before: str, after: str) -> list[dict[str, object]]:
    return [{"operation": tag, "before": before[i1:i2], "after": after[j1:j2], "before_start": i1, "after_start": j1} for tag, i1, i2, j1, j2 in SequenceMatcher(None, before, after).get_opcodes() if tag != "equal"]

def _historical_answers(db: Session, position: CriticalPosition) -> list[CommentAnswer]:
    """同じ手数の回答を、推定棋力を主、更新日時を従として並べる。"""
    return list(db.scalars(select(CommentAnswer).join(CriticalPosition, CriticalPosition.id == CommentAnswer.critical_position_id).join(CommentSubmission, CommentSubmission.id == CommentAnswer.submission_id).outerjoin(GameSkillAnalysis, GameSkillAnalysis.game_id == CommentSubmission.game_id).where(CriticalPosition.move_number == position.move_number, CriticalPosition.id != position.id, CommentSubmission.submitted_at.is_not(None)).order_by(func.coalesce(GameSkillAnalysis.estimated_rating, 0).desc(), CommentAnswer.updated_at.desc(), CommentAnswer.id.desc()).limit(HISTORICAL_ANSWER_LIMIT)))

def _preferred_feedback(db: Session, move_number: int) -> AiCommentFeedback | None:
    """修正文も回答者の最高推定棋力を優先し、同棋力なら新しいものを使う。"""
    user_rating = select(func.max(GameSkillAnalysis.estimated_rating)).where(GameSkillAnalysis.user_id == AiCommentFeedback.user_id).correlate(AiCommentFeedback).scalar_subquery()
    return db.scalar(select(AiCommentFeedback).where(AiCommentFeedback.move_number == move_number).order_by(func.coalesce(user_rating, 0).desc(), AiCommentFeedback.created_at.desc(), AiCommentFeedback.id.desc()))


def generate_ai_comments(db: Session, submission: CommentSubmission) -> list[AiComment]:
    positions = list(db.scalars(select(CriticalPosition).where(CriticalPosition.game_id == submission.game_id).order_by(CriticalPosition.move_number)))
    own_answers = list(db.scalars(select(CommentAnswer).where(CommentAnswer.submission_id == submission.id)))
    own_by_position: dict[int, list[CommentAnswer]] = {}
    for answer in own_answers:
        own_by_position.setdefault(answer.critical_position_id, []).append(answer)
    generated: list[AiComment] = []
    for position in positions:
        existing = db.scalar(select(AiComment).where(AiComment.critical_position_id == position.id))
        if existing is not None:
            generated.append(existing)
            continue
        learned = _preferred_feedback(db, position.move_number)
        answers = sorted(own_by_position.get(position.id, []), key=lambda item: item.question_number)
        historical = _historical_answers(db, position)
        sources = answers + historical
        if learned is not None:
            text = learned.after_text
            version = MODEL_VERSION + "+feedback"
        else:
            values: dict[int, str] = {}
            for item in historical:
                if item.answer_text.strip():
                    values.setdefault(item.question_number, item.answer_text.strip())
            values.update({item.question_number: item.answer_text.strip() for item in answers if item.answer_text.strip()})
            text = f"{position.move_number}手目では、{values.get(1, chr(12302)+chr(23616)+chr(38754)+chr(12398)+chr(29366)+chr(12356)+chr(12434)+chr(25972)+chr(29702)+chr(12377)+chr(12427)+chr(23616)+chr(38754)+chr(12303))}。候補手の比較は、{values.get(2, chr(12302)+chr(35079)+chr(25968)+chr(12398)+chr(20505)+chr(35036)+chr(25163)+chr(12434)+chr(27604)+chr(36611)+chr(12377)+chr(12427)+chr(12303))}。振り返りとして、{values.get(3, chr(12302)+chr(21028)+chr(26029)+chr(12398)+chr(21028)+chr(26029)+chr(12434)+chr(27425)+chr(12398)+chr(23550)+chr(23616)+chr(38754)+chr(12395)+chr(27963)+chr(12363)+chr(12377)+chr(12303))}。"
            version = MODEL_VERSION
        comment = AiComment(critical_position_id=position.id, move_number=position.move_number, generated_text=text, current_text=text, source_answer_ids=[item.id for item in sources], model_version=version)
        db.add(comment)
        generated.append(comment)
    db.flush()
    return generated
