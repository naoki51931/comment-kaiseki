import pytest
import shogi

from app.services.analysis import japanese_move_at, normalize_evaluation, normalize_mate, win_rate
from app.services.critical_positions import PositionChange, extract_critical_positions
from app.services.engine import DevelopmentEngine, YaneuraOuEngine


def test_usi_move_is_formatted_as_japanese_kif() -> None:
    assert japanese_move_at(shogi.STARTING_SFEN, ["7g7f", "3c3d"], 1) == "７六歩(77)"
    assert japanese_move_at(shogi.STARTING_SFEN, ["7g7f", "3c3d"], 2) == "３四歩(33)"


def test_evaluation_is_normalized_for_gote_user() -> None:
    assert normalize_evaluation(300, side_to_move=shogi.BLACK, user_side="SENTE") == 300
    assert normalize_evaluation(300, side_to_move=shogi.WHITE, user_side="SENTE") == -300
    assert normalize_evaluation(300, side_to_move=shogi.BLACK, user_side="GOTE") == -300
    assert normalize_evaluation(300, side_to_move=shogi.WHITE, user_side="GOTE") == 300


def test_mate_is_normalized_for_gote_user() -> None:
    assert normalize_mate(5, side_to_move=shogi.BLACK, user_side="SENTE") == 5
    assert normalize_mate(5, side_to_move=shogi.WHITE, user_side="SENTE") == -5
    assert normalize_mate(5, side_to_move=shogi.BLACK, user_side="GOTE") == -5
    assert normalize_mate(5, side_to_move=shogi.WHITE, user_side="GOTE") == 5


def test_win_rate_uses_normalized_mate() -> None:
    assert win_rate(None, 3) == 100
    assert win_rate(None, -3) == 0


def test_win_rate_is_monotonic() -> None:
    assert win_rate(-1000) < win_rate(0) < win_rate(1000)


def test_critical_positions_merge_nearby_candidates_and_fill_minimum() -> None:
    changes = [
        PositionChange(i, f"move{i}", 0, score, 50, 50 + min(40, abs(score) // 20))
        for i, score in enumerate([100, 900, 800, 50, 40, -1000, 20, 10, 700], start=1)
    ]
    selected = extract_critical_positions(changes)
    assert 3 <= len(selected) <= 5
    assert any(item.change.move_number == 6 for item in selected)


def test_development_engine_returns_legal_pv() -> None:
    board = shogi.Board()
    result = DevelopmentEngine().analyze(board.sfen())
    assert result.score_side_to_move == 0
    assert result.principal_variation
    assert shogi.Move.from_usi(result.principal_variation[0]) in board.legal_moves
    assert len(result.variations or []) == 5


def test_yaneuraou_parser_uses_latest_score_and_pv() -> None:
    result = YaneuraOuEngine._parse_info([
        "info depth 8 score cp 120 pv 7g7f 3c3d",
        "info depth 12 score cp -80 pv 2g2f 8c8d",
        "bestmove 2g2f",
    ])
    assert result.score_side_to_move == -80
    assert result.mate_in is None
    assert result.principal_variation == ["2g2f", "8c8d"]



def test_yaneuraou_parser_reads_five_variations_and_keeps_all_moves() -> None:
    result = YaneuraOuEngine._parse_info([
        f"info depth 12 multipv {index} score cp {100 - index} pv 7g7f 3c3d 2g2f 8c8d 2f2e 8d8e"
        for index in range(1, 6)
    ])
    assert len(result.variations or []) == 5
    assert all(len(item.principal_variation) == 6 for item in result.variations or [])
    assert (result.variations or [])[0].score_side_to_move == 99


def test_yaneuraou_parser_keeps_longest_pv_for_each_candidate() -> None:
    result = YaneuraOuEngine._parse_info([
        "info depth 8 multipv 1 score cp 10 pv 7g7f 3c3d 2g2f 8c8d 2f2e",
        "info depth 9 multipv 1 score cp 20 pv 7g7f 3c3d",
    ])
    assert result.score_side_to_move == 20
    assert result.principal_variation == ["7g7f", "3c3d", "2g2f", "8c8d", "2f2e"]


def test_yaneuraou_parser_handles_mate_score() -> None:
    result = YaneuraOuEngine._parse_info(["info depth 10 score mate -7 pv 5a5b"])
    assert result.score_side_to_move is None
    assert result.mate_in == -7


def test_yaneuraou_parser_rejects_invalid_mate_score() -> None:
    with pytest.raises(ValueError):
        YaneuraOuEngine._parse_info(["info score mate unknown"])


