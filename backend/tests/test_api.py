from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.api.dependencies import get_current_user
from app.database import Base, get_db
from app.main import app
from app.models import AnalysisStatus, CommentSubmission, Game, ProfessionalGameFingerprint, User
from app.services.kif import parse_game_file


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


@pytest.fixture()
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    settings.upload_dir = tmp_path / "uploads"
    settings.analysis_queue_enabled = False
    with testing_session() as seed_db:
        test_user = User(email="owner@example.test", email_verified=True)
        seed_db.add(test_user)
        seed_db.commit()
        seed_db.refresh(test_user)
        seed_db.expunge(test_user)

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: test_user
    with TestClient(app) as test_client:
        test_client.app.state.testing_session = testing_session
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def upload(client: TestClient, content: bytes | None = None, filename: str = "sample.kif"):
    return client.post(
        "/api/games",
        data={
            "played_at": "2026-07-13",
            "user_side": "SENTE",
            "ownership_confirmed": "true",
            "posting_terms_agreed": "true",
        },
        files={"game_file": (filename, KIF.encode() if content is None else content, "application/x-kif")},
    )


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_upload_persists_parsed_kif(client: TestClient) -> None:
    response = upload(client)

    assert response.status_code == 202
    assert response.json()["original_filename"] == "sample.kif"
    assert response.json()["move_count"] == 3
    assert response.json()["analysis_status"] == "QUEUED"
    assert response.json()["is_public"] is False
    assert len(list(settings.upload_dir.glob("*.kif"))) == 1

    games = client.get("/api/games").json()
    assert len(games) == 1
    assert games[0]["original_filename"] == "sample.kif"


def test_upload_can_be_registered_as_public(client: TestClient) -> None:
    response = client.post(
        "/api/games",
        data={
            "played_at": "2026-07-13",
            "user_side": "SENTE",
            "is_public": "true",
            "ownership_confirmed": "true",
            "posting_terms_agreed": "true",
        },
        files={"game_file": ("public.kif", KIF.encode(), "application/x-kif")},
    )

    assert response.status_code == 202
    assert response.json()["is_public"] is True
    assert client.get("/api/games").json()[0]["is_public"] is True


def test_owner_can_edit_game_visibility(client: TestClient) -> None:
    game_id = upload(client).json()["id"]

    public_response = client.patch(
        f"/api/games/{game_id}/visibility", json={"is_public": True}
    )
    private_response = client.patch(
        f"/api/games/{game_id}/visibility", json={"is_public": False}
    )

    assert public_response.status_code == 200
    assert public_response.json()["is_public"] is True
    assert private_response.status_code == 200
    assert private_response.json()["is_public"] is False


def test_unknown_game_visibility_cannot_be_edited(client: TestClient) -> None:
    response = client.patch("/api/games/999/visibility", json={"is_public": True})
    assert response.status_code == 404


def test_clipboard_text_persists_detected_game(client: TestClient) -> None:
    response = client.post(
        "/api/games",
        data={
            "played_at": "2026-07-13",
            "user_side": "SENTE",
            "ownership_confirmed": "true",
            "posting_terms_agreed": "true",
            "game_text": KIF,
        },
    )
    assert response.status_code == 202
    assert response.json()["original_filename"] == "clipboard-2026-07-13.kif"
    assert response.json()["move_count"] == 3


def test_playback_returns_board_frames(client: TestClient) -> None:
    game_id = upload(client).json()["id"]

    response = client.get(f"/api/games/{game_id}/playback")

    assert response.status_code == 200
    playback = response.json()
    assert len(playback["frames"]) == 4
    assert playback["frames"][0]["japanese_move"] == "開始局面"
    assert playback["frames"][1]["japanese_move"] == "７六歩(77)"
    assert playback["frames"][1]["board"]["squares"][6][2] is None
    assert playback["frames"][1]["board"]["squares"][5][2]["symbol"] == "歩"
    assert playback["frames"][1]["evaluation"] is None


def test_branch_position_returns_legal_moves_and_applies_capture(client: TestClient) -> None:
    game_id = upload(client).json()["id"]
    start = client.post(f"/api/games/{game_id}/branch-position", json={"move_number": 0, "moves": []})
    assert start.status_code == 200
    assert any(move["usi"] == "7g7f" for move in start.json()["legal_moves"])

    advanced = client.post(
        f"/api/games/{game_id}/branch-position",
        json={"move_number": 0, "moves": ["7g7f", "3c3d", "7f7e", "3d3e", "7e7d", "3e3f", "7d7c+"]},
    )
    assert advanced.status_code == 200
    assert advanced.json()["board"]["squares"][2][2]["symbol"] == "と"
    assert advanced.json()["board"]["hands"]["SENTE"][0]["symbol"] == "歩"


def test_branch_position_rejects_illegal_move(client: TestClient) -> None:
    game_id = upload(client).json()["id"]
    response = client.post(f"/api/games/{game_id}/branch-position", json={"move_number": 0, "moves": ["7g7e"]})
    assert response.status_code == 422


def test_branch_position_can_drop_piece_from_hand(client: TestClient) -> None:
    content = b"sfen 4k4/9/9/9/9/9/9/9/4K4 b P 1\nP*5e\n"
    uploaded = upload(client, content=content, filename="drop.txt")
    assert uploaded.status_code == 202, uploaded.text
    game_id = uploaded.json()["id"]
    position = client.post(f"/api/games/{game_id}/branch-position", json={"move_number": 0, "moves": []})
    assert position.status_code == 200
    drop = next(move for move in position.json()["legal_moves"] if move["usi"] == "P*5e")
    assert drop["drop_piece"] == "P"
    assert drop["from_square"] is None

    dropped = client.post(f"/api/games/{game_id}/branch-position", json={"move_number": 0, "moves": ["P*5e"]})
    assert dropped.status_code == 200
    assert dropped.json()["board"]["squares"][4][4]["symbol"] == "歩"
    assert dropped.json()["board"]["hands"]["SENTE"] == []


def test_branch_can_be_saved_and_listed_as_branch_one(client: TestClient) -> None:
    game_id = upload(client).json()["id"]
    saved = client.post(f"/api/games/{game_id}/branches", json={"move_number": 0, "moves": ["7g7f", "3c3d"]})
    assert saved.status_code == 201
    assert saved.json()["name"] == "分岐1"
    assert saved.json()["japanese_moves"] == ["７六歩(77)", "３四歩(33)"]

    branches = client.get(f"/api/games/{game_id}/branches")
    assert branches.status_code == 200
    assert branches.json()[0]["name"] == "分岐1"
    assert branches.json()[0]["usi_moves"] == ["7g7f", "3c3d"]


def test_empty_branch_cannot_be_saved(client: TestClient) -> None:
    game_id = upload(client).json()["id"]
    assert client.post(f"/api/games/{game_id}/branches", json={"move_number": 0, "moves": []}).status_code == 422


def test_branch_analysis_requires_ai_access(client: TestClient) -> None:
    game_id = upload(client).json()["id"]
    response = client.post(f"/api/games/{game_id}/branch-analysis", json={"move_number": 0, "moves": ["7g7f"]})
    assert response.status_code == 403


def test_owner_can_delete_game_and_stored_file(client: TestClient) -> None:
    created = upload(client)
    game_id = created.json()["id"]
    stored_files = list(settings.upload_dir.glob("*.kif"))

    response = client.delete(f"/api/games/{game_id}")

    assert response.status_code == 204
    assert client.get("/api/games").json() == []
    assert stored_files and not stored_files[0].exists()
    assert client.delete(f"/api/games/{game_id}").status_code == 404


def test_duplicate_move_sequence_is_rejected(client: TestClient) -> None:
    assert upload(client).status_code == 202
    same_moves = KIF.replace("試作先手", "別の先手").replace("試作後手", "別の後手").encode()

    response = upload(client, same_moves, "renamed.kif")

    assert response.status_code == 409
    assert len(list(settings.upload_dir.glob("*.kif"))) == 1


def test_professional_game_is_rejected_before_file_is_saved(client: TestClient) -> None:
    parsed = parse_game_file(KIF.encode(), "professional.kif", settings.max_kif_size_bytes)
    with client.app.state.testing_session() as db:
        db.add(ProfessionalGameFingerprint(
            normalized_hash=parsed.normalized_hash,
            source_name="許諾済みテスト資料",
        ))
        db.commit()

    response = upload(client, filename="professional.kif")

    assert response.status_code == 422
    assert response.json()["detail"].startswith("プロ公式戦と一致する棋譜")
    assert list(settings.upload_dir.glob("*")) == []


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("empty.kif", b""),
        ("wrong.txt", KIF.encode()),
        ("broken.kif", b"not a kif"),
        ("encoding.kif", b"\x81"),
    ],
)
def test_invalid_upload_is_rejected(client: TestClient, filename: str, content: bytes) -> None:
    response = upload(client, content, filename)
    assert response.status_code == 422


def test_ownership_confirmation_is_required(client: TestClient) -> None:
    response = client.post(
        "/api/games",
        data={"played_at": "2026-07-13", "user_side": "SENTE", "ownership_confirmed": "false", "posting_terms_agreed": "true"},
        files={"game_file": ("sample.kif", KIF.encode(), "application/x-kif")},
    )
    assert response.status_code == 422


def test_game_input_requires_exactly_one_source(client: TestClient) -> None:
    common = {"played_at": "2026-07-13", "user_side": "SENTE", "ownership_confirmed": "true", "posting_terms_agreed": "true"}
    missing = client.post("/api/games", data=common)
    both = client.post(
        "/api/games",
        data={**common, "game_text": KIF},
        files={"game_file": ("sample.kif", KIF.encode(), "application/x-kif")},
    )
    assert missing.status_code == 422
    assert both.status_code == 422


def test_posting_terms_agreement_is_required(client: TestClient) -> None:
    response = client.post(
        "/api/games",
        data={
            "played_at": "2026-07-13",
            "user_side": "SENTE",
            "ownership_confirmed": "true",
            "posting_terms_agreed": "false",
        },
        files={"game_file": ("sample.kif", KIF.encode(), "application/x-kif")},
    )
    assert response.status_code == 422
    assert response.json()["detail"].startswith("棋譜投稿規約への同意")


def test_unknown_game_has_no_critical_positions(client: TestClient) -> None:
    response = client.get("/api/games/999/critical-positions")
    assert response.status_code == 404


def test_owner_can_request_game_reanalysis(client: TestClient) -> None:
    game_id = upload(client).json()["id"]
    with client.app.state.testing_session() as db:
        game = db.get(Game, game_id)
        game.analysis_status = AnalysisStatus.COMMENT_REQUIRED.value
        db.commit()

    response = client.post(f"/api/games/{game_id}/reanalyze")

    assert response.status_code == 202
    assert response.json()["analysis_status"] == "QUEUED"
    assert client.post(f"/api/games/{game_id}/reanalyze").status_code == 409


def test_reanalysis_accepts_submitted_comments_without_deleting_them(client: TestClient) -> None:
    game_id = upload(client).json()["id"]
    with client.app.state.testing_session() as db:
        game = db.get(Game, game_id)
        game.analysis_status = AnalysisStatus.COMMENT_REQUIRED.value
        db.add(CommentSubmission(game_id=game_id, user_id=game.user_id, submitted_at=datetime.now(timezone.utc)))
        db.commit()

    response = client.post(f"/api/games/{game_id}/reanalyze")

    assert response.status_code == 202
    with client.app.state.testing_session() as db:
        submission = db.scalar(select(CommentSubmission).where(CommentSubmission.game_id == game_id))
        assert submission is not None
        assert submission.submitted_at is not None


def test_owner_can_add_selected_comment_position(client: TestClient) -> None:
    game_id = upload(client).json()["id"]
    with client.app.state.testing_session() as db:
        game = db.get(Game, game_id)
        game.analysis_status = AnalysisStatus.COMMENT_REQUIRED.value
        db.commit()

    response = client.post(f"/api/games/{game_id}/comment-position/2")
    duplicate = client.post(f"/api/games/{game_id}/comment-position/2")

    assert response.status_code == 201
    assert response.json()["move_number"] == 2
    assert response.json()["japanese_move"] == "３四歩(33)"
    assert response.json()["required"] is False
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == response.json()["id"]


def test_start_position_cannot_be_added_as_comment_position(client: TestClient) -> None:
    game_id = upload(client).json()["id"]
    assert client.post(f"/api/games/{game_id}/comment-position/0").status_code == 422
