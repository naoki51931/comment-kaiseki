from pathlib import Path

import pytest

from app.services.kif import parse_game_file, parse_game_text


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "formats"


@pytest.mark.parametrize("filename", ["sample.kif", "sample.ki2", "sample.csa", "sample.txt"])
def test_format_fixture_normalizes_to_same_moves(filename: str) -> None:
    parsed = parse_game_file((FIXTURE_DIR / filename).read_bytes(), filename, 2 * 1024 * 1024)
    assert parsed.usi_moves == ["7g7f", "3c3d", "2g2f"]
    assert parsed.sente_name == "テスト先手"
    assert parsed.gote_name == "テスト後手"
    assert parsed.event_name == "テスト棋戦"


def test_all_formats_have_same_hash() -> None:
    parsed = [
        parse_game_file(path.read_bytes(), path.name, 2 * 1024 * 1024)
        for path in sorted(FIXTURE_DIR.glob("sample.*"))
        if path.suffix != ".md"
    ]
    assert len({item.normalized_hash for item in parsed}) == 1


@pytest.mark.parametrize("filename", ["sample.kif", "sample.ki2", "sample.csa", "sample.txt"])
def test_clipboard_text_detects_all_formats(filename: str) -> None:
    text = (FIXTURE_DIR / filename).read_text(encoding="utf-8")
    parsed = parse_game_text(text, 2 * 1024 * 1024)
    assert parsed.usi_moves == ["7g7f", "3c3d", "2g2f"]
