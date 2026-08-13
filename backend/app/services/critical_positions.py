from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class PositionChange:
    move_number: int
    move: str
    evaluation_before: int
    evaluation_after: int
    win_rate_before: int
    win_rate_after: int
    is_mate: bool = False

    @property
    def delta(self) -> int:
        return self.evaluation_after - self.evaluation_before

    @property
    def score(self) -> int:
        evaluation_change = abs(self.delta)
        win_rate_change = abs(self.win_rate_after - self.win_rate_before) * 12
        reversal = 500 if self.evaluation_before * self.evaluation_after < 0 else 0
        mate = 5000 if self.is_mate else 0
        return evaluation_change + win_rate_change + reversal + mate


@dataclass(frozen=True)
class SelectedPosition:
    change: PositionChange
    reason: str
    score: int


def extract_critical_positions(
    changes: Sequence[PositionChange],
    *,
    threshold: int = 350,
    merge_distance: int = 3,
    minimum: int = 3,
    maximum: int = 5,
) -> list[SelectedPosition]:
    if not changes:
        return []

    ranked = sorted(changes, key=lambda item: (-item.score, item.move_number))
    selected: list[PositionChange] = []
    for candidate in ranked:
        if candidate.score < threshold:
            continue
        if any(abs(candidate.move_number - existing.move_number) <= merge_distance for existing in selected):
            continue
        selected.append(candidate)
        if len(selected) == maximum:
            break

    target_minimum = min(minimum, len(changes))
    for candidate in ranked:
        if len(selected) >= target_minimum:
            break
        if candidate not in selected:
            selected.append(candidate)

    selected = sorted(selected[:maximum], key=lambda item: item.move_number)
    return [
        SelectedPosition(
            change=item,
            score=item.score,
            reason=_reason(item),
        )
        for item in selected
    ]


def _reason(change: PositionChange) -> str:
    if change.is_mate:
        return "詰み評価が検出された局面"
    if change.evaluation_before * change.evaluation_after < 0:
        return f"形勢が逆転（評価値差{change.delta:+d}）"
    if abs(change.win_rate_after - change.win_rate_before) >= 20:
        return f"勝率が{abs(change.win_rate_after - change.win_rate_before)}ポイント変化"
    return f"評価値が{abs(change.delta)}点変化"
