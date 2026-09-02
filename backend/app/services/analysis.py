from datetime import datetime, timezone
import math

import shogi
from shogi.KIF import Exporter as KifExporter
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import AnalysisResult, AnalysisStatus, CommentAnswer, CriticalPosition, Game
from app.services.critical_positions import PositionChange, extract_critical_positions
from app.services.engine import EngineAdapter


def win_rate(score: int | None, mate_in: int | None = None) -> int:
    if mate_in is not None:
        return 100 if mate_in > 0 else 0
    if score is None:
        return 50
    return round(100 / (1 + math.exp(-max(-4000, min(4000, score)) / 600)))


def normalize_evaluation(
    raw_side_to_move: int | None,
    *,
    side_to_move: int,
    user_side: str,
) -> int | None:
    if raw_side_to_move is None:
        return None
    sente_score = raw_side_to_move if side_to_move == shogi.BLACK else -raw_side_to_move
    return sente_score if user_side == "SENTE" else -sente_score


def normalize_mate(
    mate_side_to_move: int | None,
    *,
    side_to_move: int,
    user_side: str,
) -> int | None:
    """USIの詰み手数を手番視点から投稿者視点へ変換する。"""
    if mate_side_to_move is None:
        return None
    sente_mate = mate_side_to_move if side_to_move == shogi.BLACK else -mate_side_to_move
    return sente_mate if user_side == "SENTE" else -sente_mate

def japanese_variation_at(initial_sfen: str, moves: list[str], move_number: int, variation: list[str] | None) -> list[str]:
    """指定局面からのUSI読み筋を、盤面に沿ったKIF日本語表記へ変換する。"""
    board = shogi.Board(initial_sfen)
    for move_text in moves[:move_number]:
        board.push_usi(move_text)
    result: list[str] = []
    for move_text in variation or []:
        try:
            result.append(KifExporter.kif_move_from(move_text, board))
            board.push_usi(move_text)
        except (ValueError, IndexError, AttributeError):
            result.append(move_text)
            break
    return result


def japanese_move_at(initial_sfen: str, moves: list[str], move_number: int) -> str:
    """Format a 1-based USI move as a Japanese KIF move using its board position."""
    if move_number < 1 or move_number > len(moves):
        raise ValueError("指し手番号が棋譜の範囲外です。")
    board = shogi.Board(initial_sfen)
    for index, move_text in enumerate(moves, start=1):
        if index == move_number:
            return KifExporter.kif_move_from(move_text, board)
        board.push_usi(move_text)
    raise ValueError("指し手を変換できませんでした。")


def analyze_game(db: Session, game: Game, engine: EngineAdapter) -> None:
    game.analysis_status = AnalysisStatus.ANALYZING.value
    game.analysis_started_at = datetime.now(timezone.utc)
    game.analysis_error = None
    db.commit()

    existing_positions = {
        item.move_number: item
        for item in db.scalars(select(CriticalPosition).where(CriticalPosition.game_id == game.id))
    }
    referenced_position_ids = set(db.scalars(
        select(CommentAnswer.critical_position_id).where(
            CommentAnswer.critical_position_id.in_([item.id for item in existing_positions.values()])
        )
    )) if existing_positions else set()
    db.execute(delete(AnalysisResult).where(AnalysisResult.game_id == game.id))

    board = shogi.Board(game.initial_sfen)
    previous_evaluation = 0
    previous_win_rate = 50
    changes: list[PositionChange] = []
    japanese_moves: dict[int, str] = {}

    for move_number, move_text in enumerate(game.usi_moves, start=1):
        sfen_before = board.sfen()
        is_user_move = (move_number % 2 == 1) == (game.user_side == "SENTE")
        pre_result = engine.analyze(sfen_before) if is_user_move else None
        pre_turn = board.turn
        pre_variations = [
            {
                "evaluation": normalize_evaluation(item.score_side_to_move, side_to_move=pre_turn, user_side=game.user_side),
                "mate_in": normalize_mate(item.mate_in, side_to_move=pre_turn, user_side=game.user_side),
                "principal_variation": item.principal_variation,
            }
            for item in ((pre_result.variations or [pre_result]) if pre_result else [])[:5]
        ]
        japanese_moves[move_number] = KifExporter.kif_move_from(move_text, board)
        board.push_usi(move_text)
        sfen_after = board.sfen()
        evaluated_turn = board.turn
        result = engine.analyze(sfen_after)
        normalized = normalize_evaluation(
            result.score_side_to_move,
            side_to_move=evaluated_turn,
            user_side=game.user_side,
        )
        normalized_mate = normalize_mate(
            result.mate_in,
            side_to_move=evaluated_turn,
            user_side=game.user_side,
        )
        if normalized is None:
            normalized = 100000 if (normalized_mate or 0) > 0 else -100000
        normalized_win_rate = win_rate(normalized, normalized_mate)
        db.add(
            AnalysisResult(
                game_id=game.id,
                move_number=move_number,
                sfen_before=sfen_before,
                sfen_after=sfen_after,
                evaluation_raw=result.score_side_to_move,
                evaluation_user=normalized,
                win_rate_user=normalized_win_rate,
                principal_variation=result.principal_variation,
                pre_move_variations=pre_variations or None,
                best_evaluation_user=(pre_variations[0].get("evaluation") if pre_variations else None),
                best_mate_in_user=(pre_variations[0].get("mate_in") if pre_variations else None),
                mate_in_user=normalized_mate,
                variations=[
                    {
                        "evaluation": normalize_evaluation(item.score_side_to_move, side_to_move=evaluated_turn, user_side=game.user_side),
                        "mate_in": normalize_mate(item.mate_in, side_to_move=evaluated_turn, user_side=game.user_side),
                        "principal_variation": item.principal_variation,
                    }
                    for item in (result.variations or [])[:5]
                ],
                is_mate=result.mate_in is not None,
                engine_name=engine.name,
                engine_version=engine.version,
                search_conditions={"nodes": getattr(engine, "nodes", None), **({"evaluation_function": engine.evaluation_name} if getattr(engine, "evaluation_name", None) else {})},
            )
        )
        changes.append(
            PositionChange(
                move_number=move_number,
                move=move_text,
                evaluation_before=previous_evaluation,
                evaluation_after=normalized,
                win_rate_before=previous_win_rate,
                win_rate_after=normalized_win_rate,
                is_mate=result.mate_in is not None,
            )
        )
        previous_evaluation = normalized
        previous_win_rate = normalized_win_rate

    selected = extract_critical_positions(changes)
    selected_moves: set[int] = set()
    for position in selected:
        change = position.change
        selected_moves.add(change.move_number)
        critical = existing_positions.get(change.move_number)
        if critical is None:
            critical = CriticalPosition(game_id=game.id, move_number=change.move_number)
            db.add(critical)
        critical.japanese_move = japanese_moves[change.move_number]
        critical.evaluation_before = change.evaluation_before
        critical.evaluation_after = change.evaluation_after
        critical.evaluation_delta = change.delta
        critical.selection_reason = position.reason
        critical.extraction_metadata = {
            "score": position.score,
            "threshold": 350,
            "merge_distance": 3,
            "engine": engine.name,
            "engine_version": engine.version,
            "search_conditions": {"nodes": getattr(engine, "nodes", None), **({"evaluation_function": engine.evaluation_name} if getattr(engine, "evaluation_name", None) else {})},
        }
        critical.required = True

    for move_number, critical in existing_positions.items():
        if move_number in selected_moves:
            continue
        if critical.id in referenced_position_ids:
            critical.required = False
            critical.selection_reason = "保存済みコメントを保護するため再解析後も保持"
        else:
            db.delete(critical)

    game.critical_position_count = len(selected)
    game.analysis_status = AnalysisStatus.COMMENT_REQUIRED.value
    game.analysis_completed_at = datetime.now(timezone.utc)
    db.commit()
