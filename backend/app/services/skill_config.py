"""棋力推定の暫定基準。実棋力データで補正する値を一か所に集約する。"""

EVAL_LOSS_CAP = 2000
BLUNDER_THRESHOLD = 300
MAJOR_BLUNDER_THRESHOLD = 700
WINNING_EVALUATION = 1200
PHASE_BOUNDARIES = {"opening_last_move": 30, "endgame_first_move": 81}

CONFIDENCE_LEVELS = (
    (1, "参考値", 35),
    (9, "信頼度低", 50),
    (29, "信頼度中", 72),
    (99, "信頼度高", 88),
    (10**9, "信頼度非常に高い", 95),
)

RATING_RANKS = (
    (700, "初心者"), (800, "10級"), (900, "9級"), (1000, "8級"),
    (1100, "7級"), (1200, "6級"), (1300, "5級"), (1400, "4級"),
    (1500, "3級"), (1600, "2級"), (1700, "1級"), (1800, "初段"),
    (1900, "二段"), (2000, "三段"), (2100, "四段"), (10**9, "五段"),
)

OVERALL_WEIGHTS = {
    "eval_accuracy": 0.38,
    "best_move": 0.12,
    "top3": 0.15,
    "phase_balance": 0.20,
    "conversion": 0.10,
    "recovery": 0.05,
}

ENDGAME_WEIGHTS = {
    "eval_accuracy": 0.35,
    "mate_detection": 0.30,
    "winning_conversion": 0.20,
    "engine_match": 0.15,
}

SUPPORTED_GAME_WINDOWS = (10, 30, 100)
