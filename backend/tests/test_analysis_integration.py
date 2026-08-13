from datetime import date
import pytest
import shogi

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app import tasks
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import AnalysisJobOutbox, AnalysisResult, AnalysisStatus, CriticalPosition, Game, User
from app.services.analysis import analyze_game
from app.services.engine import EngineEvaluation


class SequenceEngine:
    name = "test-usi"
    version = "1.0"
    nodes = 1234

    def __init__(self, evaluations: list[EngineEvaluation]) -> None:
        self.evaluations = iter(evaluations)

    def analyze(self, sfen: str) -> EngineEvaluation:
        assert sfen
        return next(self.evaluations)


def create_analysis_game(db, *, user_side: str, moves: list[str], hash_character: str) -> Game:
    user = User(email=f"{user_side.lower()}-{hash_character}@example.test", email_verified=True)
    db.add(user)
    db.flush()
    game = Game(
        user_id=user.id,
        original_filename=f"{hash_character}.kif",
        storage_path=f"/tmp/{hash_character}.kif",
        content_type="application/x-kif",
        file_size_bytes=100,
        source_encoding="utf-8",
        played_at=date(2026, 7, 13),
        user_side=user_side,
        initial_sfen=shogi.STARTING_SFEN,
        usi_moves=moves,
        move_count=len(moves),
        normalized_hash=hash_character * 64,
        analysis_status=AnalysisStatus.QUEUED.value,
    )
    db.add(game)
    db.commit()
    db.refresh(game)
    return game


def test_analysis_persists_results_and_critical_positions() -> None:
    database = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    sessions = sessionmaker(bind=database, expire_on_commit=False)
    Base.metadata.create_all(database)
    with sessions() as db:
        game = create_analysis_game(
            db,
            user_side="SENTE",
            moves=["7g7f", "3c3d", "2g2f"],
            hash_character="b",
        )
        engine = SequenceEngine([
            EngineEvaluation(120, None, ["3c3d"]),
            EngineEvaluation(-900, None, ["2g2f", "8c8d"]),
            EngineEvaluation(300, None, ["8c8d"]),
        ])

        analyze_game(db, game, engine)

        db.refresh(game)
        results = list(db.scalars(select(AnalysisResult).order_by(AnalysisResult.move_number)))
        positions = list(db.scalars(select(CriticalPosition).order_by(CriticalPosition.move_number)))
        assert game.analysis_status == AnalysisStatus.COMMENT_REQUIRED.value
        assert game.analysis_error is None
        assert game.analysis_completed_at is not None
        assert game.critical_position_count == 3
        assert len(results) == 3
        assert results[0].sfen_before == shogi.STARTING_SFEN
        assert results[1].evaluation_user == -900
        assert results[1].principal_variation == ["2g2f", "8c8d"]
        assert results[1].engine_name == "test-usi"
        assert results[1].search_conditions == {"nodes": 1234}
        assert len(positions) == 3
        assert positions[0].extraction_metadata["engine"] == "test-usi"
    Base.metadata.drop_all(database)


def test_gote_mate_score_is_saved_from_submitter_perspective() -> None:
    database = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    sessions = sessionmaker(bind=database, expire_on_commit=False)
    Base.metadata.create_all(database)
    with sessions() as db:
        game = create_analysis_game(db, user_side="GOTE", moves=["7g7f"], hash_character="c")
        engine = SequenceEngine([EngineEvaluation(None, 5, ["3c3d"])])

        analyze_game(db, game, engine)

        result = db.scalar(select(AnalysisResult))
        assert result is not None
        assert result.evaluation_user == 100000
        assert result.win_rate_user == 100
        assert result.is_mate is True
    Base.metadata.drop_all(database)


def test_outbox_keeps_failed_dispatch_for_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    database = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    sessions = sessionmaker(bind=database, expire_on_commit=False)
    Base.metadata.create_all(database)
    with sessions() as db:
        game = create_analysis_game(db, user_side="SENTE", moves=["7g7f"], hash_character="d")
        outbox = AnalysisJobOutbox(game_id=game.id)
        db.add(outbox)
        db.commit()
        db.refresh(outbox)

        def fail(_: int) -> None:
            raise ConnectionError("redis unavailable")

        monkeypatch.setattr(tasks, "enqueue_game_analysis", fail)
        assert tasks.dispatch_analysis_outbox(db, outbox.id) is False
        db.refresh(outbox)
        assert outbox.sent_at is None
        assert outbox.attempt_count == 1
        assert "redis unavailable" in (outbox.last_error or "")

        sent: list[int] = []
        monkeypatch.setattr(tasks, "enqueue_game_analysis", sent.append)
        assert tasks.dispatch_analysis_outbox(db, outbox.id) is True
        db.refresh(outbox)
        assert sent == [game.id]
        assert outbox.sent_at is not None
        assert outbox.attempt_count == 2
        assert outbox.last_error is None
    Base.metadata.drop_all(database)
