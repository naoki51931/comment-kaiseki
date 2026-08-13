from __future__ import annotations

from typing import Any, Protocol


class RecommendationProvider(Protocol):
    def recommend(self, summary: dict[str, Any]) -> list[dict[str, str]]: ...


class TrainingRecommendationService:
    """将来LLM実装へ差し替えられるルールベース推薦サービス。"""

    def recommend(self, summary: dict[str, Any]) -> list[dict[str, str]]:
        candidates: list[tuple[float, str, str]] = []
        candidates.append((100 - summary["middlegame_score"], "中盤の受け",
                           "攻め合いで評価値を落とす傾向があります。相手の狙いを確認してから攻める練習がおすすめです。"))
        candidates.append((100 - summary["opening_score"], "序盤定跡",
                           "序盤30手以内の精度に改善余地があります。普段採用する戦型の定跡を重点的に確認してください。"))
        if summary["mate_opportunities"]:
            mate_miss_rate = summary["mate_missed"] / summary["mate_opportunities"] * 100
            candidates.append((mate_miss_rate + 10, "3〜7手詰の詰将棋",
                               "終盤で詰みを逃す割合が高くなっています。短手数の詰将棋から読み切る練習が効果的です。"))
        conversion = (summary["winning_positions_converted"] / summary["winning_positions"] * 100
                      if summary["winning_positions"] else 100)
        candidates.append((100 - conversion + 5, "優勢局面の勝ち切り",
                           "優勢後に評価値を戻される傾向があります。自玉の安全度を確認し、無理に攻めない練習がおすすめです。"))
        candidates.sort(key=lambda item: item[0], reverse=True)
        labels = ("最優先", "優先度：高", "優先度：中")
        return [
            {"title": title, "priority": labels[index], "reason": reason}
            for index, (_, title, reason) in enumerate(candidates[:3])
        ]


# TODO: threat detection - やねうら王から確実な詰めろ信号を取得できる境界を追加する。
# TODO: hisshi detection - 必至専用探索器を接続できる境界を追加する。
