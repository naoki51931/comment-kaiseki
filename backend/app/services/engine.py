from dataclasses import dataclass
import queue
import selectors
import threading
from pathlib import Path
import subprocess
import time
from typing import Protocol

import shogi

from app.config import settings


@dataclass(frozen=True)
class EngineVariation:
    score_side_to_move: int | None
    mate_in: int | None
    principal_variation: list[str]


@dataclass(frozen=True)
class EngineEvaluation:
    score_side_to_move: int | None
    mate_in: int | None
    principal_variation: list[str]
    variations: list[EngineVariation] | None = None


class EngineAdapter(Protocol):
    name: str
    version: str

    def analyze(self, sfen: str) -> EngineEvaluation: ...


PIECE_VALUES = {
    shogi.PAWN: 100,
    shogi.LANCE: 300,
    shogi.KNIGHT: 320,
    shogi.SILVER: 450,
    shogi.GOLD: 550,
    shogi.BISHOP: 800,
    shogi.ROOK: 1000,
    shogi.KING: 0,
    shogi.PROM_PAWN: 550,
    shogi.PROM_LANCE: 550,
    shogi.PROM_KNIGHT: 550,
    shogi.PROM_SILVER: 550,
    shogi.PROM_BISHOP: 1100,
    shogi.PROM_ROOK: 1300,
}


class DevelopmentEngine:
    """外部エンジンがない開発・テスト用の決定的評価器。"""

    name = "development-material"
    version = "1"
    evaluation_name = "development-material"

    def analyze(self, sfen: str) -> EngineEvaluation:
        board = shogi.Board(sfen)
        score_sente = 0
        for square in range(81):
            piece = board.piece_at(square)
            if piece is None:
                continue
            value = PIECE_VALUES[piece.piece_type]
            score_sente += value if piece.color == shogi.BLACK else -value
        for piece_type, value in PIECE_VALUES.items():
            score_sente += board.pieces_in_hand[shogi.BLACK].get(piece_type, 0) * value
            score_sente -= board.pieces_in_hand[shogi.WHITE].get(piece_type, 0) * value
        score_side = score_sente if board.turn == shogi.BLACK else -score_sente
        legal = list(board.legal_moves)
        pv = [legal[0].usi()] if legal else []
        variations = [EngineVariation(score_side, None, [move.usi()]) for move in legal[:5]]
        return EngineEvaluation(score_side, None, pv, variations)


class YaneuraOuEngine:
    name = "YaneuraOu"

    def __init__(self, path: str, nodes: int, timeout_seconds: float) -> None:
        self.path = path
        self.nodes = nodes
        self.timeout_seconds = timeout_seconds
        self.version = "USI"
        self.evaluation_name = "Suisho5"
        self._process: subprocess.Popen[str] | None = None
        self._output_queue: queue.Queue[str] = queue.Queue()

    def _start(self) -> subprocess.Popen[str]:
        process = subprocess.Popen(
            [self.path],
            cwd=Path(self.path).resolve().parent,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._output_queue = queue.Queue()
        threading.Thread(target=self._read_output, args=(process,), daemon=True).start()
        try:
            self._send(process, "usi")
            usi_lines = self._read_until(process, "usiok")
            for line in usi_lines:
                if line.startswith("id name "):
                    self.version = line.removeprefix("id name ")
            self._send(process, "setoption name MultiPV value 5")
            self._send(process, "setoption name USI_Hash value 64")
            self._send(process, "setoption name Threads value 1")
            self._send(process, "setoption name BookFile value no_book")
            self._send(process, "isready")
            self._read_until(process, "readyok")
            self._send(process, "usinewgame")
        except Exception:
            self._stop(process)
            raise
        self._process = process
        return process

    def analyze(self, sfen: str) -> EngineEvaluation:
        process = self._process if self._process is not None and self._process.poll() is None else self._start()
        self._send(process, f"position sfen {sfen}")
        self._send(process, f"go nodes {self.nodes}")
        lines = self._read_until(process, "bestmove")
        return self._parse_info(lines)

    def close(self) -> None:
        if self._process is not None:
            self._stop(self._process)
            self._process = None

    @staticmethod
    def _stop(process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            try:
                YaneuraOuEngine._send(process, "quit")
                process.wait(timeout=2)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                process.kill()

    def __del__(self) -> None:
        self.close()

    @staticmethod
    def _send(process: subprocess.Popen[str], command: str) -> None:
        if process.stdin is None:
            raise RuntimeError("USIエンジンの標準入力を開けません。")
        process.stdin.write(command + "\n")
        process.stdin.flush()

    def _read_output(self, process: subprocess.Popen[str]) -> None:
        if process.stdout is None:
            return
        for line in process.stdout:
            self._output_queue.put(line.strip())

    def _read_until(self, process: subprocess.Popen[str], marker: str) -> list[str]:
        deadline = time.monotonic() + self.timeout_seconds
        lines: list[str] = []
        while time.monotonic() < deadline:
            try:
                line = self._output_queue.get(timeout=min(0.5, deadline - time.monotonic()))
            except queue.Empty:
                if process.poll() is not None:
                    raise RuntimeError("USIエンジンが予期せず終了しました。")
                continue
            lines.append(line)
            if line.startswith(marker) or line == marker:
                return lines
        raise TimeoutError(f"USIエンジンが{marker}を返しませんでした。")

    @staticmethod
    def _parse_info(lines: list[str]) -> EngineEvaluation:
        score: int | None = None
        mate: int | None = None
        pv: list[str] = []
        variations: dict[int, EngineVariation] = {}
        for line in lines:
            tokens = line.split()
            if not tokens or tokens[0] != "info":
                continue
            if "score" in tokens:
                index = tokens.index("score")
                if len(tokens) > index + 2:
                    if tokens[index + 1] == "cp":
                        score = int(tokens[index + 2])
                        mate = None
                    elif tokens[index + 1] == "mate":
                        mate_text = tokens[index + 2]
                        mate = 1 if mate_text == "+" else -1 if mate_text == "-" else int(mate_text)
                        score = None
            if "pv" in tokens:
                pv = tokens[tokens.index("pv") + 1 :]
                multipv = int(tokens[tokens.index("multipv") + 1]) if "multipv" in tokens else 1
                candidate_pv = pv
                previous = variations.get(multipv)
                if previous is not None and len(previous.principal_variation) > len(candidate_pv):
                    candidate_pv = previous.principal_variation
                variations[multipv] = EngineVariation(score, mate, candidate_pv)
        ordered = [variations[key] for key in sorted(variations)[:5]]
        primary = ordered[0] if ordered else EngineVariation(score, mate, pv)
        return EngineEvaluation(primary.score_side_to_move, primary.mate_in, primary.principal_variation, ordered)


def create_engine_adapter() -> EngineAdapter:
    if settings.engine_kind == "yaneuraou":
        return YaneuraOuEngine(settings.yaneuraou_path, settings.engine_nodes, settings.engine_timeout_seconds)
    return DevelopmentEngine()
