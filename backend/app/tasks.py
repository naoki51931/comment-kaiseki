from datetime import datetime, timezone

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models import AnalysisJobOutbox, AnalysisStatus, Game
from app.services.analysis import analyze_game
from app.services.engine import create_engine_adapter

from sqlalchemy import select


@celery_app.task(bind=True, max_retries=3)
def analyze_game_task(self, game_id: int) -> None:
    with SessionLocal() as db:
        game = db.get(Game, game_id)
        if game is None:
            return
        try:
            game.analysis_retry_count = self.request.retries
            engine = create_engine_adapter()
            try:
                analyze_game(db, game, engine)
            finally:
                close = getattr(engine, "close", None)
                if close is not None:
                    close()
        except Exception as exc:
            db.rollback()
            game = db.get(Game, game_id)
            if game is not None:
                game.analysis_retry_count = self.request.retries + 1
                game.analysis_error = str(exc)[:2000]
                game.analysis_status = (
                    AnalysisStatus.QUEUED.value
                    if self.request.retries < self.max_retries
                    else AnalysisStatus.FAILED.value
                )
                db.commit()
            if self.request.retries < self.max_retries:
                raise self.retry(exc=exc, countdown=2 ** self.request.retries)
            raise


def enqueue_game_analysis(game_id: int) -> None:
    analyze_game_task.delay(game_id)


def dispatch_analysis_outbox(db, outbox_id: int) -> bool:
    outbox = db.get(AnalysisJobOutbox, outbox_id)
    if outbox is None or outbox.sent_at is not None:
        return True
    try:
        enqueue_game_analysis(outbox.game_id)
    except Exception as exc:
        outbox.attempt_count += 1
        outbox.last_error = str(exc)[:2000]
        db.commit()
        return False
    outbox.attempt_count += 1
    outbox.last_error = None
    outbox.sent_at = datetime.now(timezone.utc)
    db.commit()
    return True


@celery_app.task
def dispatch_pending_analysis_jobs() -> int:
    dispatched = 0
    with SessionLocal() as db:
        ids = list(db.scalars(
            select(AnalysisJobOutbox.id)
            .where(AnalysisJobOutbox.sent_at.is_(None))
            .order_by(AnalysisJobOutbox.created_at)
            .limit(100)
        ))
        for outbox_id in ids:
            if dispatch_analysis_outbox(db, outbox_id):
                dispatched += 1
    return dispatched
