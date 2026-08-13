from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.database import get_db
from app.models import AnalysisStatus, Game, GameSkillAnalysis, User
from app.services.skill_estimation import analyze_game_skill, build_summary, rating_to_rank, validate_game_window
from app.services.training_recommendations import TrainingRecommendationService

router = APIRouter()

def _analysis_payload(item: GameSkillAnalysis) -> dict[str, Any]:
    return {column.name: getattr(item, column.name) for column in item.__table__.columns}



def _owned_game(db: Session, user: User, game_id: int) -> Game:
    game = db.get(Game, game_id)
    if game is None or game.user_id != user.id:
        raise HTTPException(status_code=404, detail="棋譜が見つかりません。")
    return game


def _analyses(db: Session, user_id: int) -> list[GameSkillAnalysis]:
    return list(db.scalars(
        select(GameSkillAnalysis).where(GameSkillAnalysis.user_id == user_id)
        .order_by(GameSkillAnalysis.played_at.desc(), GameSkillAnalysis.game_id.desc())
    ))


@router.post("/{game_id}", status_code=status.HTTP_201_CREATED)
def create_skill_estimation(
    game_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> Any:
    game = _owned_game(db, user, game_id)
    if game.analysis_status != AnalysisStatus.COMMENT_REQUIRED.value:
        raise HTTPException(status_code=409, detail="棋譜解析完了後に棋力推定できます。")
    try:
        return _analysis_payload(analyze_game_skill(db, game))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="棋力推定用の着手前解析がありません。棋譜を再解析してください。") from exc


@router.get("/game/{game_id}")
def get_skill_estimation(
    game_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> Any:
    _owned_game(db, user, game_id)
    result = db.scalar(select(GameSkillAnalysis).where(GameSkillAnalysis.game_id == game_id))
    if result is None:
        raise HTTPException(status_code=404, detail="保存済みの棋力推定がありません。")
    return _analysis_payload(result)


def _summary(db: Session, user_id: int, games: int) -> dict[str, Any]:
    try:
        validate_game_window(games)
        return build_summary(_analyses(db, user_id), games)
    except ValueError as exc:
        raise HTTPException(status_code=404 if "ありません" in str(exc) else 422, detail=str(exc)) from exc


@router.get("/summary")
def summary(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    games: int = Query(10),
) -> dict[str, Any]:
    return _summary(db, user.id, games)


@router.get("/history")
def history(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    games: int = Query(100),
) -> dict[str, Any]:
    validate_game_window(games)
    items = list(reversed(_analyses(db, user.id)[:games]))
    points = [{"game_id": item.game_id, "played_at": item.played_at, "estimated_rating": item.estimated_rating,
               "estimated_rank": item.estimated_rank} for item in items]
    current = points[-1] if points else None
    previous = points[-31] if len(points) > 30 else (points[0] if points else None)
    return {"points": points, "current_rank": current["estimated_rank"] if current else None,
            "previous_rank": previous["estimated_rank"] if previous else None,
            "change": current["estimated_rating"] - previous["estimated_rating"] if current and previous else 0}


@router.get("/recommendations")
def recommendations(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    games: int = Query(10),
) -> dict[str, Any]:
    summary_data = _summary(db, user.id, games)
    return {"items": TrainingRecommendationService().recommend(summary_data)}


@router.get("/endgame")
def endgame(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    games: int = Query(10),
) -> dict[str, Any]:
    summary_data = _summary(db, user.id, games)
    opportunities = summary_data["mate_opportunities"]
    wins = summary_data["winning_positions"]
    return {
        "score": summary_data["endgame_score"],
        "estimated_rank": rating_to_rank(500 + summary_data["endgame_score"] * 16),
        "mate_detection_rate": round(summary_data["mate_found"] / opportunities * 100) if opportunities else None,
        "mate_opportunities": opportunities, "mate_found": summary_data["mate_found"],
        "mate_missed": summary_data["mate_missed"],
        "winning_conversion_rate": round(summary_data["winning_positions_converted"] / wins * 100) if wins else None,
        "threat_detection_rate": None, "hisshi_detection_rate": None,
        "mate_events": [event for item in _analyses(db, user.id)[:games] for event in item.mate_events],
    }
