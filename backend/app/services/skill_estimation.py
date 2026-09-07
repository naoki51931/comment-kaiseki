from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any, Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import AnalysisResult, Game, GameSkillAnalysis
from app.services.skill_config import (
    BLUNDER_THRESHOLD, CONFIDENCE_LEVELS, ENDGAME_WEIGHTS, EVAL_LOSS_CAP,
    MAJOR_BLUNDER_THRESHOLD, OVERALL_WEIGHTS, PHASE_BOUNDARIES, RATING_RANKS,
    RATING_BASE, RATING_POINTS_PER_SCORE, SITUATIONAL_PRIOR_OPPORTUNITIES,
    SUPPORTED_GAME_WINDOWS, WINNING_EVALUATION,
)


@dataclass(frozen=True)
class EvalLoss:
    loss: int
    is_mate_loss: bool = False


def calculate_eval_loss(
    best_evaluation: int | None,
    actual_evaluation: int | None,
    *,
    best_mate_in: int | None = None,
    actual_mate_in: int | None = None,
    cap: int = EVAL_LOSS_CAP,
) -> EvalLoss:
    """投稿者視点の最善評価と実着手後評価から、上限付き損失を返す。"""
    if best_mate_in is not None:
        maintained = actual_mate_in is not None and actual_mate_in > 0
        return EvalLoss(0 if maintained else cap, not maintained)
    if best_evaluation is None or actual_evaluation is None:
        return EvalLoss(0)
    return EvalLoss(min(cap, max(0, best_evaluation - actual_evaluation)))


def rating_to_rank(rating: int) -> str:
    for upper, rank in RATING_RANKS:
        if rating < upper:
            return rank
    return "五段"


def confidence_for_games(game_count: int) -> tuple[str, int]:
    if game_count <= 0:
        return "データなし", 0
    for upper, label, percent in CONFIDENCE_LEVELS:
        if game_count <= upper:
            return label, percent
    return "信頼度非常に高い", 95


def phase_for_move(move_number: int, total_moves: int) -> str:
    if move_number <= PHASE_BOUNDARIES["opening_last_move"]:
        return "opening"
    endgame_start = min(PHASE_BOUNDARIES["endgame_first_move"], max(41, round(total_moves * .67)))
    return "endgame" if move_number >= endgame_start else "middlegame"


def accuracy_score(losses: Iterable[int]) -> int:
    values = list(losses)
    return round(max(0, 100 - mean(values) / 5)) if values else 0


def smoothed_success_rate(successes: int, opportunities: int) -> float:
    """少数・対象なしの局面を100%と誤認しない、50%事前分布付き成功率。"""
    if opportunities < 0 or successes < 0 or successes > opportunities:
        raise ValueError("成功数と対象局面数が不正です。")
    prior = SITUATIONAL_PRIOR_OPPORTUNITIES
    return (successes + prior * .5) / (opportunities + prior) * 100


def _weighted_average(items: Iterable[GameSkillAnalysis], name: str) -> float:
    values = list(items)
    total_moves = sum(max(1, item.analyzed_move_count) for item in values)
    return sum(getattr(item, name) * max(1, item.analyzed_move_count) for item in values) / total_moves


def score_to_rating(score: float) -> int:
    return round(RATING_BASE + max(0, min(100, score)) * RATING_POINTS_PER_SCORE)


def estimate_rating(*, average_loss: float, best_rate: float, top3_rate: float,
                    phase_scores: Iterable[int], conversion_rate: float, recovery_rate: float) -> tuple[int, int]:
    eval_accuracy = max(0, 100 - average_loss / 5)
    phases = list(phase_scores)
    overall = (
        eval_accuracy * OVERALL_WEIGHTS["eval_accuracy"]
        + best_rate * OVERALL_WEIGHTS["best_move"]
        + top3_rate * OVERALL_WEIGHTS["top3"]
        + (mean(phases) if phases else 0) * OVERALL_WEIGHTS["phase_balance"]
        + conversion_rate * OVERALL_WEIGHTS["conversion"]
        + recovery_rate * OVERALL_WEIGHTS["recovery"]
    )
    # 暫定ヒューリスティック。教師データによる較正へ差し替え可能。
    return score_to_rating(overall), round(overall)


def _is_user_move(move_number: int, user_side: str) -> bool:
    return (move_number % 2 == 1) == (user_side == "SENTE")


def analyze_game_skill(db: Session, game: Game) -> GameSkillAnalysis:
    results = list(db.scalars(
        select(AnalysisResult).where(AnalysisResult.game_id == game.id).order_by(AnalysisResult.move_number)
    ))
    user_results = [item for item in results if _is_user_move(item.move_number, game.user_side)]
    if not user_results:
        raise ValueError("投稿者本人の解析対象着手がありません。")
    if not any(item.pre_move_variations for item in user_results):
        raise ValueError("棋力推定用の着手前解析がありません。")

    losses: list[int] = []
    phase_losses: dict[str, list[int]] = {"opening": [], "middlegame": [], "endgame": []}
    best_matches = top3_matches = blunders = major_blunders = 0
    winning_positions = winning_converted = recoveries = winning_drops = 0
    mate_opportunities = mate_found = mate_missed = 0
    mate_events: list[dict[str, Any]] = []

    for item in user_results:
        candidates = item.pre_move_variations or []
        candidate_moves = [pv.get("principal_variation", [None])[0] for pv in candidates if pv.get("principal_variation")]
        actual_move = game.usi_moves[item.move_number - 1]
        best_mate = item.best_mate_in_user
        actual_mate = item.mate_in_user
        eval_loss = calculate_eval_loss(
            item.best_evaluation_user, item.evaluation_user,
            best_mate_in=best_mate if best_mate is not None and best_mate > 0 else None,
            actual_mate_in=actual_mate,
        )
        # 最善と第2候補がほぼ同価値なら、次善手の損失を難易度に応じて緩和する。
        if len(candidates) > 1 and actual_move == candidate_moves[1]:
            first = candidates[0].get("evaluation")
            second = candidates[1].get("evaluation")
            if first is not None and second is not None and abs(first - second) <= 80:
                eval_loss = EvalLoss(min(eval_loss.loss, abs(first - second)), eval_loss.is_mate_loss)
        losses.append(eval_loss.loss)
        phase_losses[phase_for_move(item.move_number, game.move_count)].append(eval_loss.loss)
        best_matches += int(bool(candidate_moves) and actual_move == candidate_moves[0])
        top3_matches += int(actual_move in candidate_moves[:3])
        blunders += int(BLUNDER_THRESHOLD <= eval_loss.loss < MAJOR_BLUNDER_THRESHOLD)
        major_blunders += int(eval_loss.loss >= MAJOR_BLUNDER_THRESHOLD)
        if (item.best_evaluation_user or 0) >= WINNING_EVALUATION:
            winning_positions += 1
            converted = (item.evaluation_user or -100000) >= WINNING_EVALUATION // 2
            winning_converted += int(converted)
            winning_drops += int(not converted)
        if (item.best_evaluation_user or 0) < -500 and (item.evaluation_user or -100000) > -200:
            recoveries += 1
        if best_mate is not None and best_mate > 0:
            mate_opportunities += 1
            maintained = actual_mate is not None and actual_mate > 0
            mate_found += int(maintained)
            mate_missed += int(not maintained)
            mate_events.append({
                "opportunity_move": item.move_number,
                "found_move": item.move_number if maintained else None,
                "moves_to_find": 0 if maintained else None,
                "shortest_mate": best_mate,
                "actual_mate": actual_mate if maintained else None,
                "status": "最短詰み" if maintained and actual_move == (candidate_moves[0] if candidate_moves else None)
                          else "詰みを維持" if maintained else "詰み逃し",
            })

    count = len(user_results)
    average_loss = mean(losses)
    opening_score = accuracy_score(phase_losses["opening"])
    middlegame_score = accuracy_score(phase_losses["middlegame"])
    endgame_accuracy = accuracy_score(phase_losses["endgame"])
    best_rate = best_matches / count * 100
    top3_rate = top3_matches / count * 100
    conversion_rate = smoothed_success_rate(winning_converted, winning_positions)
    recovery_rate = min(100, recoveries / count * 300)
    mate_rate = smoothed_success_rate(mate_found, mate_opportunities)
    endgame_score = round(
        endgame_accuracy * ENDGAME_WEIGHTS["eval_accuracy"]
        + mate_rate * ENDGAME_WEIGHTS["mate_detection"]
        + conversion_rate * ENDGAME_WEIGHTS["winning_conversion"]
        + top3_rate * ENDGAME_WEIGHTS["engine_match"]
    )
    rating, overall = estimate_rating(
        average_loss=average_loss, best_rate=best_rate, top3_rate=top3_rate,
        phase_scores=(opening_score, middlegame_score, endgame_score),
        conversion_rate=conversion_rate, recovery_rate=recovery_rate,
    )
    values = dict(
        user_id=game.user_id, game_id=game.id, played_at=game.played_at,
        estimated_rating=rating, estimated_rank=rating_to_rank(rating),
        average_eval_loss=round(average_loss), best_move_match_rate=round(best_rate),
        top3_match_rate=round(top3_rate), opening_score=opening_score,
        middlegame_score=middlegame_score, endgame_score=endgame_score,
        blunder_count=blunders, major_blunder_count=major_blunders,
        winning_positions=winning_positions, winning_positions_converted=winning_converted,
        winning_position_drops=winning_drops, recovery_count=recoveries,
        mate_opportunities=mate_opportunities, mate_found=mate_found, mate_missed=mate_missed,
        mate_events=mate_events, overall_score=overall, analyzed_move_count=count,
    )
    existing = db.scalar(select(GameSkillAnalysis).where(GameSkillAnalysis.game_id == game.id))
    if existing is None:
        existing = GameSkillAnalysis(**values)
        db.add(existing)
    else:
        for key, value in values.items():
            setattr(existing, key, value)
    db.commit()
    db.refresh(existing)
    return existing


def build_summary(analyses: list[GameSkillAnalysis], requested_games: int) -> dict[str, Any]:
    selected = analyses[:requested_games]
    count = len(selected)
    if not selected:
        raise ValueError("棋力推定済みの棋譜がありません。")
    # 短手数の一局と長手数の一局を同じ重さにせず、実際に解析した着手数で集計する。
    avg = lambda name: round(_weighted_average(selected, name))
    average_loss = _weighted_average(selected, "average_eval_loss")
    winning_positions = sum(i.winning_positions for i in selected)
    winning_converted = sum(i.winning_positions_converted for i in selected)
    rating, overall = estimate_rating(
        average_loss=average_loss, best_rate=avg("best_move_match_rate"), top3_rate=avg("top3_match_rate"),
        phase_scores=(avg("opening_score"), avg("middlegame_score"), avg("endgame_score")),
        conversion_rate=smoothed_success_rate(winning_converted, winning_positions),
        recovery_rate=min(100, sum(i.recovery_count for i in selected) / max(1, sum(i.analyzed_move_count for i in selected)) * 300),
    )
    confidence_label, confidence = confidence_for_games(count)
    return {
        "requested_games": requested_games, "game_count": count, "estimated_rating": rating,
        "estimated_rank": rating_to_rank(rating), "confidence_label": confidence_label,
        "confidence_percent": confidence, "is_reference": count == 1,
        "average_eval_loss": round(average_loss), "best_move_match_rate": avg("best_move_match_rate"),
        "top3_match_rate": avg("top3_match_rate"), "opening_score": avg("opening_score"),
        "middlegame_score": avg("middlegame_score"), "endgame_score": avg("endgame_score"),
        "blunder_count": sum(i.blunder_count for i in selected),
        "major_blunder_count": sum(i.major_blunder_count for i in selected),
        "mate_opportunities": sum(i.mate_opportunities for i in selected),
        "mate_found": sum(i.mate_found for i in selected), "mate_missed": sum(i.mate_missed for i in selected),
        "winning_positions": winning_positions,
        "winning_positions_converted": winning_converted,
        "overall_score": overall,
        "methodology": "解析着手数による加重集計と少数局面補正を用いた本アプリ独自の推定",
    }


def validate_game_window(games: int) -> int:
    if games not in SUPPORTED_GAME_WINDOWS:
        raise ValueError("gamesは10、30、100のいずれかを指定してください。")
    return games
