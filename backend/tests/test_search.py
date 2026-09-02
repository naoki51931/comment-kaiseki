from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import AiComment, CommentAnswer, CommentSubmission, CriticalPosition, Game, User
from app.services.search import documents_for_user, search_database


def test_japanese_comment_and_ai_comment_are_searchable_after_submission() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        user = User(email="search@example.test", email_verified=True)
        db.add(user); db.flush()
        game = Game(user_id=user.id, original_filename="search.kif", storage_path="/tmp/search.kif", file_size_bytes=1, source_encoding="utf-8", played_at=date(2026, 8, 13), user_side="SENTE", initial_sfen="startpos", usi_moves=["7g7f"], move_count=1, normalized_hash="s" * 64, analysis_status="COMMENT_REQUIRED")
        db.add(game); db.flush()
        position = CriticalPosition(game_id=game.id, move_number=1, japanese_move="７六歩(77)", evaluation_before=0, evaluation_after=0, evaluation_delta=0, selection_reason="終盤の重要局面", extraction_metadata={})
        db.add(position); db.flush()
        submission = CommentSubmission(game_id=game.id, user_id=user.id, submitted_at=datetime.now(timezone.utc))
        db.add(submission); db.flush()
        answer = CommentAnswer(submission_id=submission.id, critical_position_id=position.id, question_number=1, answer_text="上から押せば詰んでたかも")
        db.add(answer)
        db.add(AiComment(critical_position_id=position.id, move_number=1, generated_text="終盤を確認", current_text="詰み筋を確認する", source_answer_ids=[], model_version="test"))
        db.commit()

        assert search_database(db, user.id, "詰んでた", 20)[0]["source_type"] == "comment_answer"
        assert any(item["source_type"] == "ai_comment" for item in search_database(db, user.id, "詰み筋", 20))
        assert any(item.source_type == "comment_answer" for item in documents_for_user(db, user.id))


def test_unsubmitted_comment_is_not_searchable_or_indexed() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        user = User(email="draft@example.test", email_verified=True)
        db.add(user); db.flush()
        game = Game(user_id=user.id, original_filename="draft.kif", storage_path="/tmp/draft.kif", file_size_bytes=1, source_encoding="utf-8", played_at=date(2026, 8, 13), user_side="SENTE", initial_sfen="startpos", usi_moves=["7g7f"], move_count=1, normalized_hash="d" * 64, analysis_status="COMMENT_REQUIRED")
        db.add(game); db.flush()
        position = CriticalPosition(game_id=game.id, move_number=1, japanese_move="７六歩(77)", evaluation_before=0, evaluation_after=0, evaluation_delta=0, selection_reason="非公開の採用理由", extraction_metadata={})
        db.add(position); db.flush()
        submission = CommentSubmission(game_id=game.id, user_id=user.id)
        db.add(submission); db.flush()
        db.add(CommentAnswer(submission_id=submission.id, critical_position_id=position.id, question_number=1, answer_text="未提出の秘密コメント"))
        db.commit()

        assert search_database(db, user.id, "秘密コメント", 20) == []
        assert all(item.source_type not in {"comment_answer", "critical_position"} for item in documents_for_user(db, user.id))
