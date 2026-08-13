from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import ProfessionalGameFingerprint
from app.services.professional_games import import_professional_game_directory

KIF = """#KIF version=2.0 encoding=UTF-8
手合割：平手
先手：試作先手
後手：試作後手
手数----指手---------消費時間--
   1 ７六歩(77)   ( 0:00/00:00:00)
   2 ３四歩(33)   ( 0:00/00:00:00)
   3 ２六歩(27)   ( 0:00/00:00:00)
   4 投了         ( 0:00/00:00:00)
"""


def test_import_stores_fingerprint_without_game_record(tmp_path: Path) -> None:
    source = tmp_path / "licensed"
    source.mkdir()
    (source / "one.kif").write_text(KIF, encoding="utf-8")
    (source / "broken.kif").write_text("invalid", encoding="utf-8")
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        first = import_professional_game_directory(
            db, source, source_name="許諾済み資料", source_reference="contract-1",
            max_size_bytes=1024 * 1024,
        )
        second = import_professional_game_directory(
            db, source, source_name="許諾済み資料", max_size_bytes=1024 * 1024,
        )
        item = db.scalar(select(ProfessionalGameFingerprint))

    assert first.imported == 1
    assert first.invalid == 1
    assert second.already_registered == 1
    assert item is not None
    assert item.sente_name == "試作先手"
    assert item.source_reference == "contract-1"
