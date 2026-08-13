from collections.abc import Generator
from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user, require_admin
from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models import (
    AiAccessSubscription,
    AiComment,
    AiCommentFeedback,
    AnalysisResult,
    CommentSubmission,
    CriticalPosition,
    Game,
    RewardLedger,
    ReviewStatus,
    User,
)


def test_comment_privacy_submission_review_and_reward() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with sessions() as db:
        owner = User(email="owner@example.com", email_verified=True)
        admin = User(email="admin@example.com", email_verified=True, is_admin=True, mfa_enabled=True)
        db.add_all([owner, admin])
        db.flush()
        game = Game(
            user_id=owner.id,
            original_filename="workflow.kif",
            storage_path="/tmp/workflow.kif",
            content_type="application/x-kif",
            file_size_bytes=100,
            source_encoding="utf-8-sig",
            played_at=date(2026, 7, 13),
            user_side="SENTE",
            initial_sfen="lnsgkgsnl/1r5b1/ppppppppp/9/9/9/PPPPPPPPP/1B5R1/LNSGKGSNL b - 1",
            usi_moves=["7g7f"],
            move_count=1,
            normalized_hash="a" * 64,
            analysis_status="COMMENT_REQUIRED",
            critical_position_count=1,
        )
        db.add(game)
        db.flush()
        position = CriticalPosition(
            game_id=game.id,
            move_number=1,
            japanese_move="7g7f",
            evaluation_before=0,
            evaluation_after=-500,
            evaluation_delta=-500,
            selection_reason="評価値が500点変化",
            extraction_metadata={},
            required=True,
        )
        db.add(position)
        db.add(AnalysisResult(
            game_id=game.id,
            move_number=1,
            sfen_before=game.initial_sfen,
            sfen_after=game.initial_sfen,
            evaluation_raw=-500,
            evaluation_user=-500,
            win_rate_user=30,
            principal_variation=["3c3d", "2g2f"],
            is_mate=False,
            engine_name="test",
            engine_version="1",
            search_conditions={"nodes": 100},
        ))
        db.commit()
        for item in (owner, admin, game, position):
            db.refresh(item)
            db.expunge(item)

    def override_db() -> Generator[Session, None, None]:
        with sessions() as db:
            yield db

    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: owner
    with TestClient(app) as client:
        hidden = client.get(f"/api/games/{game.id}/critical-positions").json()[0]
        assert hidden["evaluation_after"] is None
        assert hidden["engine_explanation_visible"] is False
        hidden_playback = client.get(f"/api/games/{game.id}/playback").json()
        assert hidden_playback["frames"][1]["evaluation"] is None
        assert hidden_playback["frames"][1]["principal_variation"] is None
        previous_test_email = settings.ai_access_test_user_email
        settings.ai_access_test_user_email = owner.email
        test_playback = client.get(f"/api/games/{game.id}/playback").json()
        assert test_playback["test_evaluation_toggle_available"] is True
        assert test_playback["frames"][1]["evaluation"] == -500
        assert test_playback["frames"][1]["principal_variation"] is None
        settings.ai_access_test_user_email = previous_test_email

        draft = client.get(f"/api/games/{game.id}/comments").json()
        assert draft["review_status"] == "NOT_SUBMITTED"
        incomplete = {
            "answers": [
                {"critical_position_id": position.id, "question_number": 1, "answer_text": "回答"}
            ]
        }
        empty = {"answers": [{"critical_position_id": position.id, "question_number": 1, "answer_text": ""}]}
        assert client.put(f"/api/games/{game.id}/comments/draft", json=empty).status_code == 200
        empty_submit = client.post(f"/api/games/{game.id}/comments/submit")
        assert empty_submit.status_code == 422
        assert empty_submit.json()["detail"] == "コメントを1つ以上入力してください。"

        assert client.put(f"/api/games/{game.id}/comments/draft", json=incomplete).status_code == 200
        submitted = client.post(f"/api/games/{game.id}/comments/submit")
        assert submitted.status_code == 200
        paywalled = client.get(f"/api/games/{game.id}/critical-positions").json()[0]
        assert paywalled["evaluation_after"] == -500
        assert paywalled["selection_reason"] is None
        assert paywalled["engine_explanation_visible"] is True
        assert paywalled["principal_variation"] is None
        paywalled_playback = client.get(f"/api/games/{game.id}/playback").json()
        assert paywalled_playback["frames"][1]["evaluation"] == -500
        assert paywalled_playback["frames"][1]["principal_variation"] is None
        assert paywalled_playback["frames"][1]["comments"][0]["answer"] == "回答"
        with sessions() as payment_db:
            payment_db.add(AiAccessSubscription(
                user_id=owner.id,
                stripe_subscription_id="sub_test",
                status="active",
                current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
            ))
            payment_db.commit()
        ai_comments = client.get(f"/api/games/{game.id}/ai-comments")
        assert ai_comments.status_code == 200
        ai_comment = ai_comments.json()[0]
        assert ai_comment["move_number"] == position.move_number
        assert "回答" in ai_comment["current_text"]
        corrected_text = "修正済みのAIコメント"
        corrected = client.put(f"/api/games/{game.id}/ai-comments/{ai_comment['id']}", json={"text": corrected_text})
        assert corrected.status_code == 200
        assert corrected.json()["current_text"] == corrected_text
        with sessions() as feedback_db:
            assert feedback_db.scalar(select(AiCommentFeedback)).after_text == corrected_text
            assert feedback_db.scalar(select(AiComment)).current_text == corrected_text

        previous_weaviate_enabled = settings.weaviate_enabled
        settings.weaviate_enabled = False
        searched = client.get("/api/search", params={"q": "回答"})
        settings.weaviate_enabled = previous_weaviate_enabled
        assert searched.status_code == 200
        assert searched.json()["results"][0]["game_id"] == game.id
        assert searched.json()["results"][0]["backend"] == "database"

        visible = client.get(f"/api/games/{game.id}/critical-positions").json()[0]
        assert visible["evaluation_after"] == -500
        assert visible["engine_explanation_visible"] is True
        assert visible["principal_variation"] == ["３四歩(33)", "２六歩(27)"]
        visible_playback = client.get(f"/api/games/{game.id}/playback").json()
        assert visible_playback["frames"][1]["principal_variation"] == ["３四歩(33)", "２六歩(27)"]

        app.dependency_overrides[require_admin] = lambda: admin
        reviews = client.get("/api/admin/reviews").json()
        assert reviews[0]["snapshot"]["positions"][0]["move"] == "７六歩(77)"
        assert len(reviews[0]["snapshot"]["answers"]) == 3
        with sessions() as snapshot_db:
            saved_snapshot = snapshot_db.scalar(select(CommentSubmission)).submitted_snapshot
            assert len(saved_snapshot["answers"]) == 1
        detail = client.get(f"/api/admin/reviews/{reviews[0]['id']}")
        assert detail.status_code == 200
        assert detail.json()["game"]["filename"] == "workflow.kif"
        assert detail.json()["snapshot"]["answers"][0]["answer_text"] == "回答"
        assert detail.json()["positions"][0]["principal_variation"] == ["３四歩(33)", "２六歩(27)"]
        review_response = client.post(
            f"/api/admin/reviews/{reviews[0]['id']}",
            json={"status": "APPROVED", "reason": "内容を確認", "quality_tags": ["complete"]},
        )
        assert review_response.status_code == 200

    with sessions() as db:
        submission = db.scalar(select(CommentSubmission))
        reward = db.scalar(select(RewardLedger))
        assert submission.review_status == ReviewStatus.APPROVED.value
        assert reward.amount_yen == 300
        assert reward.status == "FIXED"
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
