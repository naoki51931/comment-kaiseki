from dataclasses import dataclass
import hashlib
from pathlib import Path
import re

import shogi
from shogi.CSA import Parser as CsaParser
from shogi.KIF import Parser as KifParser


class KifValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedKif:
    encoding: str
    initial_sfen: str
    usi_moves: list[str]
    normalized_hash: str
    format: str = "KIF"
    event_name: str | None = None
    sente_name: str | None = None
    gote_name: str | None = None


def decode_kif(content: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "cp932"):
        try:
            return content.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise KifValidationError("文字コードはUTF-8またはShift_JIS（CP932）を使用してください。")


def normalized_result(encoding: str, initial_sfen: str, moves: list[str], format_name: str, event_name: str | None = None, sente_name: str | None = None, gote_name: str | None = None) -> ParsedKif:
    if not moves:
        raise KifValidationError("指し手が1手以上ある棋譜を投稿してください。")
    try:
        board = shogi.Board(initial_sfen)
        normalized_moves: list[str] = []
        for move_text in moves:
            move = shogi.Move.from_usi(move_text)
            if not board.is_legal(move):
                raise KifValidationError("棋譜に不正な指し手が含まれています。")
            normalized_moves.append(move.usi())
            board.push(move)
    except KifValidationError:
        raise
    except (ValueError, TypeError, IndexError) as exc:
        raise KifValidationError("開始局面または指し手を正規化できませんでした。") from exc
    canonical = f"{initial_sfen}\n" + "\n".join(normalized_moves)
    return ParsedKif(
        encoding,
        initial_sfen,
        normalized_moves,
        hashlib.sha256(canonical.encode("ascii")).hexdigest(),
        format_name,
        event_name,
        sente_name,
        gote_name,
    )


def extract_game_metadata(text: str) -> tuple[str | None, str | None, str | None]:
    event_name: str | None = None
    sente_name: str | None = None
    gote_name: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith(("棋戦：", "棋戦:")):
            event_name = line.split(":" if ":" in line else "：", 1)[1].strip() or None
        elif line.startswith(("棋戦名：", "棋戦名:")):
            event_name = line.split(":" if ":" in line else "：", 1)[1].strip() or None
        elif line.startswith(("先手：", "先手:")):
            sente_name = line.split(":" if ":" in line else "：", 1)[1].strip() or None
        elif line.startswith(("後手：", "後手:")):
            gote_name = line.split(":" if ":" in line else "：", 1)[1].strip() or None
        elif line.startswith("$EVENT:"):
            event_name = line[7:].strip() or None
        elif line.startswith("N+"):
            sente_name = line[2:].strip() or None
        elif line.startswith("N-"):
            gote_name = line[2:].strip() or None
    return event_name, sente_name, gote_name


def parse_game_file(content: bytes, filename: str, max_size_bytes: int) -> ParsedKif:
    if not content:
        raise KifValidationError("空のファイルは投稿できません。")
    if len(content) > max_size_bytes:
        raise KifValidationError(f"棋譜ファイルは{max_size_bytes // 1024 // 1024}MB以下にしてください。")
    text, encoding = decode_kif(content)
    event_name, sente_name, gote_name = extract_game_metadata(text)
    suffix = Path(filename).suffix.lower()
    try:
        if suffix == ".kif":
            games = KifParser.parse_str(text)
            format_name = "KIF"
        elif suffix == ".csa":
            games = CsaParser.parse_str(text)
            format_name = "CSA"
        elif suffix == ".ki2":
            return parse_ki2(text, encoding, event_name, sente_name, gote_name)
        elif suffix == ".txt":
            return parse_usi_text(text, encoding, event_name, sente_name, gote_name)
        else:
            raise KifValidationError("対応形式はKIF、KI2、CSA、TXTです。")
    except KifValidationError:
        raise
    except Exception as exc:
        raise KifValidationError(f"{suffix.lstrip('.').upper()}形式を解析できませんでした。") from exc
    if len(games) != 1:
        raise KifValidationError("1ファイルには1対局だけを含めてください。")
    parsed = games[0]
    names = list(parsed.get("names") or [])
    sente_name = sente_name or (names[0] if len(names) > 0 else None)
    gote_name = gote_name or (names[1] if len(names) > 1 else None)
    return normalized_result(
        encoding,
        parsed.get("sfen") or shogi.STARTING_SFEN,
        list(parsed.get("moves") or []),
        format_name,
        event_name,
        sente_name,
        gote_name,
    )


def parse_game_text(content: str, max_size_bytes: int) -> ParsedKif:
    """Detect and parse supported clipboard text without relying on a filename."""
    encoded = content.encode("utf-8")
    for suffix in (".kif", ".ki2", ".csa", ".txt"):
        try:
            return parse_game_file(encoded, f"clipboard{suffix}", max_size_bytes)
        except KifValidationError:
            continue
    raise KifValidationError(
        "棋譜形式を判定できませんでした。KIF、KI2、CSA、USI形式の内容を貼り付けてください。"
    )


def parse_kif(content: bytes, max_size_bytes: int) -> ParsedKif:
    return parse_game_file(content, "game.kif", max_size_bytes)


KI2_MOVE_RE = re.compile(
    r"([▲△])((?:[１２３４５６７８９][一二三四五六七八九])|同)"
    r"([歩香桂銀金角飛玉王と杏圭全馬龍竜])([右左直上引寄]*)?(不成|成)?(打)?"
)
NUMBER_FILES = "１２３４５６７８９"
NUMBER_RANKS = "一二三四五六七八九"
PIECE_NAMES = {
    "歩": shogi.PAWN, "香": shogi.LANCE, "桂": shogi.KNIGHT, "銀": shogi.SILVER,
    "金": shogi.GOLD, "角": shogi.BISHOP, "飛": shogi.ROOK, "玉": shogi.KING,
    "王": shogi.KING, "と": shogi.PROM_PAWN, "杏": shogi.PROM_LANCE,
    "圭": shogi.PROM_KNIGHT, "全": shogi.PROM_SILVER, "馬": shogi.PROM_BISHOP,
    "龍": shogi.PROM_ROOK, "竜": shogi.PROM_ROOK,
}


def parse_ki2(text: str, encoding: str, event_name: str | None = None, sente_name: str | None = None, gote_name: str | None = None) -> ParsedKif:
    board = shogi.Board()
    moves: list[str] = []
    last_to: int | None = None
    for match in KI2_MOVE_RE.finditer(text.replace(" ", "").replace("　", "")):
        marker, destination, piece_name, _, promotion_text, drop_text = match.groups()
        expected_turn = shogi.BLACK if marker == "▲" else shogi.WHITE
        if board.turn != expected_turn:
            raise KifValidationError("KI2の先後記号と手番が一致しません。")
        if destination == "同":
            if last_to is None:
                raise KifValidationError("KI2の「同」に対応する直前局面がありません。")
            to_square = last_to
        else:
            file_number = NUMBER_FILES.index(destination[0]) + 1
            rank_number = NUMBER_RANKS.index(destination[1]) + 1
            to_square = shogi.SQUARE_NAMES.index(f"{file_number}{chr(96 + rank_number)}")
        piece_type = PIECE_NAMES[piece_name]
        candidates: list[shogi.Move] = []
        for move in board.legal_moves:
            if move.to_square != to_square:
                continue
            if bool(move.drop_piece_type) != bool(drop_text):
                continue
            if move.drop_piece_type:
                moving_type = move.drop_piece_type
            else:
                moving_piece = board.piece_at(move.from_square)
                if moving_piece is None:
                    continue
                moving_type = moving_piece.piece_type
                if move.promotion:
                    moving_type = shogi.PIECE_PROMOTED[moving_type]
            if moving_type != piece_type:
                continue
            if promotion_text == "成" and not move.promotion:
                continue
            if promotion_text == "不成" and move.promotion:
                continue
            candidates.append(move)
        if len(candidates) != 1:
            raise KifValidationError("KI2の指し手を一意に特定できません。方向表記を確認してください。")
        move = candidates[0]
        moves.append(move.usi())
        board.push(move)
        last_to = to_square
    return normalized_result(encoding, shogi.STARTING_SFEN, moves, "KI2", event_name, sente_name, gote_name)


USI_LINE_RE = re.compile(r"^\s*(?:\d+[.：:]?\s*)?([1-9][a-i][1-9][a-i]\+?|[PLNSGBR]\*[1-9][a-i])\s*$")


def parse_usi_text(text: str, encoding: str, event_name: str | None = None, sente_name: str | None = None, gote_name: str | None = None) -> ParsedKif:
    moves: list[str] = []
    initial_sfen = shogi.STARTING_SFEN
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("sfen "):
            initial_sfen = stripped[5:].strip()
            continue
        match = USI_LINE_RE.match(stripped)
        if match:
            moves.append(match.group(1))
    return normalized_result(encoding, initial_sfen, moves, "TXT", event_name, sente_name, gote_name)
