import pytest

from app.services.kif import KifValidationError, parse_kif
from tests.test_api import KIF


def test_parser_normalizes_moves_to_usi() -> None:
    parsed = parse_kif(KIF.encode(), 1024 * 1024)
    assert parsed.usi_moves == ["7g7f", "3c3d", "2g2f"]
    assert len(parsed.normalized_hash) == 64


def test_hash_ignores_player_metadata_and_encoding() -> None:
    first = parse_kif(KIF.encode(), 1024 * 1024)
    changed = KIF.replace("試作先手", "別名").replace("試作後手", "別名")
    second = parse_kif(changed.encode("cp932"), 1024 * 1024)
    assert first.normalized_hash == second.normalized_hash


def test_size_limit_is_enforced() -> None:
    with pytest.raises(KifValidationError, match="MB以下"):
        parse_kif(KIF.encode(), 10)
