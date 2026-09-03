from difflib import SequenceMatcher

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AiComment, AiCommentFeedback, AnalysisResult, CommentAnswer, CommentSubmission, CriticalPosition, GameSkillAnalysis, ReviewStatus
from app.services.skill_estimation import confidence_for_games

MODEL_VERSION = "comment-retrieval-v4-board-context-skill-weighted"
HISTORICAL_ANSWER_LIMIT = 6


def contributor_weight(estimated_rating: int | None, confidence_percent: int) -> float:
    """高い推定段位を強く、少数局による不確かな判定を控えめに重み付けする。"""
    rating_factor = .5 if estimated_rating is None else max(.5, min(2.5, estimated_rating / 1000))
    confidence_factor = .5 + max(0, min(100, confidence_percent)) / 200
    return round(rating_factor * confidence_factor, 3)

def text_diff(before: str, after: str) -> list[dict[str, object]]:
    return [{"operation": tag, "before": before[i1:i2], "after": after[j1:j2], "before_start": i1, "after_start": j1} for tag, i1, i2, j1, j2 in SequenceMatcher(None, before, after).get_opcodes() if tag != "equal"]


def approved_training_examples(db: Session) -> list[dict[str, object]]:
    """匿名化した棋譜・局面図・コメントを一組の学習例として返す。"""
    examples: list[dict[str, object]] = []
    submissions = db.scalars(
        select(CommentSubmission).where(CommentSubmission.review_status == ReviewStatus.APPROVED.value)
    )
    for submission in submissions:
        snapshot = submission.submitted_snapshot or {}
        context = snapshot.get("learning_context") or {}
        if (
            not snapshot.get("learning_consent")
            or snapshot.get("contributor") != "anonymous"
            or not context.get("initial_sfen")
            or not isinstance(context.get("usi_moves"), list)
        ):
            continue
        skill = db.scalar(select(GameSkillAnalysis).where(GameSkillAnalysis.game_id == submission.game_id))
        analyzed_games = db.scalar(
            select(func.count(GameSkillAnalysis.id)).where(GameSkillAnalysis.user_id == submission.user_id)
        ) or 0
        confidence_label, confidence_percent = confidence_for_games(analyzed_games)
        positions = {
            item.get("critical_position_id"): item
            for item in context.get("positions", [])
            if isinstance(item, dict) and item.get("sfen_before")
        }
        answers = list(db.scalars(select(CommentAnswer).where(CommentAnswer.submission_id == submission.id)))
        for position_id, position in positions.items():
            comments = [
                {"answer_id": answer.id, "question_number": answer.question_number, "text": answer.answer_text}
                for answer in answers
                if answer.critical_position_id == position_id and answer.answer_text.strip()
            ]
            if comments:
                examples.append({
                    "kifu": {"initial_sfen": context["initial_sfen"], "usi_moves": context["usi_moves"]},
                    "position": position,
                    "comments": comments,
                    "contributor_skill": {
                        "estimated_rating": skill.estimated_rating if skill else None,
                        "estimated_rank": skill.estimated_rank if skill else "未判定",
                        "confidence_label": confidence_label,
                        "confidence_percent": confidence_percent,
                        "weight": contributor_weight(skill.estimated_rating if skill else None, confidence_percent),
                    },
                })
    return examples

def _historical_answers(db: Session, position: CriticalPosition) -> list[CommentAnswer]:
    """棋譜・局面図付きの承認済み匿名学習例から回答を参照する。"""
    current_analysis = db.scalar(select(AnalysisResult).where(
        AnalysisResult.game_id == position.game_id,
        AnalysisResult.move_number == position.move_number,
    ))
    examples = approved_training_examples(db)
    matching_ids: list[int] = []
    weights: dict[int, float] = {}
    for example in examples:
        example_position = example["position"]
        if not isinstance(example_position, dict) or example_position.get("move_number") != position.move_number:
            continue
        if current_analysis is not None and example_position.get("sfen_before") != current_analysis.sfen_before:
            continue
        weight = float(example.get("contributor_skill", {}).get("weight", .25))
        for comment in example["comments"]:
            if isinstance(comment, dict) and comment.get("answer_id") is not None:
                answer_id = int(comment["answer_id"])
                matching_ids.append(answer_id)
                weights[answer_id] = weight
    if not matching_ids:
        return []
    candidates = list(db.scalars(
        select(CommentAnswer)
        .join(CriticalPosition, CriticalPosition.id == CommentAnswer.critical_position_id)
        .join(CommentSubmission, CommentSubmission.id == CommentAnswer.submission_id)
        .outerjoin(GameSkillAnalysis, GameSkillAnalysis.game_id == CommentSubmission.game_id)
        .where(
            CriticalPosition.move_number == position.move_number,
            CriticalPosition.id != position.id,
            CommentAnswer.id.in_(matching_ids),
        )
        .order_by(CommentAnswer.updated_at.desc(), CommentAnswer.id.desc())
    ))
    candidates.sort(key=lambda answer: (weights.get(answer.id, .25), answer.updated_at), reverse=True)
    return candidates[:HISTORICAL_ANSWER_LIMIT]

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
