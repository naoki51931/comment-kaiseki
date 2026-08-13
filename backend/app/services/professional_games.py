from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ProfessionalGameFingerprint
from app.services.kif import KifValidationError, parse_game_file

SUPPORTED_SUFFIXES = {".kif", ".ki2", ".csa", ".txt"}


@dataclass(frozen=True)
class ImportResult:
    imported: int
    already_registered: int
    invalid: int


def is_professional_game(db: Session, normalized_hash: str) -> bool:
    return db.scalar(select(ProfessionalGameFingerprint.id).where(
        ProfessionalGameFingerprint.normalized_hash == normalized_hash
    )) is not None


def import_professional_game_directory(
    db: Session, directory: Path, *, source_name: str,
    source_reference: str | None = None, played_at: date | None = None,
    max_size_bytes: int,
) -> ImportResult:
    """許諾済み棋譜群を読み込み、指し手列のフィンガープリントだけを登録する。"""
    if not directory.is_dir():
        raise ValueError(f"ディレクトリが見つかりません: {directory}")
    imported = already_registered = invalid = 0
    files = sorted(path for path in directory.rglob("*") if path.suffix.lower() in SUPPORTED_SUFFIXES)
    for path in files:
        try:
            parsed = parse_game_file(path.read_bytes(), path.name, max_size_bytes)
        except (OSError, KifValidationError):
            invalid += 1
            continue
        if is_professional_game(db, parsed.normalized_hash):
            already_registered += 1
            continue
        db.add(ProfessionalGameFingerprint(
            normalized_hash=parsed.normalized_hash, source_name=source_name,
            source_reference=source_reference, event_name=parsed.event_name,
            sente_name=parsed.sente_name, gote_name=parsed.gote_name, played_at=played_at,
        ))
        db.flush()
        imported += 1
    db.commit()
    return ImportResult(imported, already_registered, invalid)
