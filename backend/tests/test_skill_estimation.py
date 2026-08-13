from datetime import date
from types import SimpleNamespace

import pytest

from app.services.analysis import normalize_evaluation
from app.services.skill_estimation import (
    EvalLoss, build_summary, calculate_eval_loss, confidence_for_games,
    estimate_rating, rating_to_rank,
)
from app.services.training_recommendations import TrainingRecommendationService


def analysis(**overrides):
    values = dict(
        game_id=1, played_at=date(2026, 8, 1), estimated_rating=1450,
        estimated_rank="3級", average_eval_loss=80, best_move_match_rate=45,
        top3_match_rate=72, opening_score=80, middlegame_score=65,
        endgame_score=75, blunder_count=2, major_blunder_count=1,
        mate_opportunities=2, mate_found=1, mate_missed=1,
        winning_positions=2, winning_positions_converted=1,
        winning_position_drops=1, recovery_count=1, overall_score=60,
        analyzed_move_count=40, mate_events=[],
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_sente_evaluation_sign() -> None:
    assert normalize_evaluation(300, side_to_move=0, user_side="SENTE") == 300


def test_gote_evaluation_sign() -> None:
    assert normalize_evaluation(300, side_to_move=1, user_side="GOTE") == 300


def test_best_move_has_no_loss() -> None:
    assert calculate_eval_loss(850, 850) == EvalLoss(0)


def test_close_second_choice_has_small_loss() -> None:
    assert calculate_eval_loss(850, 820).loss == 30


def test_major_blunder_loss_is_preserved() -> None:
    assert calculate_eval_loss(900, -200).loss == 1100


def test_eval_loss_is_capped() -> None:
    assert calculate_eval_loss(5000, -5000).loss == 2000


def test_mate_score_is_separate_and_capped() -> None:
    assert calculate_eval_loss(None, None, best_mate_in=7, actual_mate_in=None) == EvalLoss(2000, True)
    assert calculate_eval_loss(None, None, best_mate_in=7, actual_mate_in=9) == EvalLoss(0, False)


@pytest.mark.parametrize(("count", "label"), [(1, "参考値"), (10, "信頼度中"), (30, "信頼度高"), (100, "信頼度非常に高い")])
def test_confidence_boundaries(count: int, label: str) -> None:
    assert confidence_for_games(count)[0] == label


def test_summary_uses_only_existing_games_when_short() -> None:
    result = build_summary([analysis(game_id=i) for i in range(17)], 30)
    assert result["game_count"] == 17
    assert result["requested_games"] == 30


def test_summary_limits_to_requested_ten_games() -> None:
    assert build_summary([analysis(game_id=i) for i in range(30)], 10)["game_count"] == 10


def test_summary_supports_one_hundred_games() -> None:
    assert build_summary([analysis(game_id=i) for i in range(100)], 100)["game_count"] == 100


def test_one_game_is_marked_reference() -> None:
    assert build_summary([analysis()], 10)["is_reference"] is True


def test_rating_increases_with_accuracy() -> None:
    weak, _ = estimate_rating(average_loss=300, best_rate=20, top3_rate=40, phase_scores=(40, 40, 40), conversion_rate=40, recovery_rate=0)
    strong, _ = estimate_rating(average_loss=30, best_rate=70, top3_rate=90, phase_scores=(85, 85, 85), conversion_rate=90, recovery_rate=40)
    assert strong > weak


@pytest.mark.parametrize(("rating", "rank"), [(650, "初心者"), (700, "10級"), (1600, "1級"), (1700, "初段"), (2200, "五段")])
def test_rating_to_rank(rating: int, rank: str) -> None:
    assert rating_to_rank(rating) == rank


def test_endgame_score_reflects_mate_detection() -> None:
    good = build_summary([analysis(endgame_score=90, mate_found=2, mate_missed=0)], 10)
    bad = build_summary([analysis(endgame_score=40, mate_found=0, mate_missed=2)], 10)
    assert good["endgame_score"] > bad["endgame_score"]


def test_training_theme_prioritizes_middlegame_weakness() -> None:
    summary = build_summary([analysis(opening_score=90, middlegame_score=20, endgame_score=80, mate_opportunities=0)], 10)
    items = TrainingRecommendationService().recommend(summary)
    assert items[0]["title"] == "中盤の受け"
    assert len(items) == 3


def test_mate_found_and_missed_counts_are_aggregated() -> None:
    summary = build_summary([analysis(mate_opportunities=3, mate_found=2, mate_missed=1)], 10)
    assert summary["mate_found"] == 2
    assert summary["mate_missed"] == 1
