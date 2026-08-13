from datetime import date
from pathlib import Path
from typing import Annotated

import shogi
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.config import settings
from app.database import get_db
from app.models import (
    AnalysisJobOutbox, AnalysisResult, AnalysisStatus, CommentAnswer, CommentSubmission,
    CriticalPosition as CriticalPositionModel, Game as GameModel, Review, RewardLedger, User,
)
from app.schemas import CriticalPosition, Game
from app.services.analysis import japanese_move_at
from shogi.KIF import Exporter as KifExporter
from app.services.kif import KifValidationError, parse_game_file, parse_game_text
from app.services.subscriptions import has_ai_access
from app.services.storage import MalwareDetectedError, remove_private_file, save_private_file
from app.tasks import dispatch_analysis_outbox


router = APIRouter()
ALLOWED_SUFFIXES = {".kif", ".ki2", ".csa", ".txt"}

QUESTION_LABELS = [
    "この局面で何を考えていましたか？",
    "どの候補手を比較しましたか？",
    "今振り返ると、判断の原因は何だったと思いますか？",
]


def board_snapshot(board: shogi.Board) -> dict[str, object]:
    squares: list[list[dict[str, str] | None]] = []
    for rank in "abcdefghi":
        row: list[dict[str, str] | None] = []
        for file_number in range(9, 0, -1):
            piece = board.piece_at(shogi.SQUARE_NAMES.index(f"{file_number}{rank}"))
            row.append(None if piece is None else {
                "symbol": piece.japanese_symbol(),
                "owner": "SENTE" if piece.color == shogi.BLACK else "GOTE",
            })
        squares.append(row)

    hands: dict[str, list[dict[str, object]]] = {"SENTE": [], "GOTE": []}
    for color, side in ((shogi.BLACK, "SENTE"), (shogi.WHITE, "GOTE")):
        for piece_type, count in sorted(board.pieces_in_hand[color].items()):
            if count:
                hands[side].append({
                    "symbol": shogi.PIECE_JAPANESE_SYMBOLS[piece_type],
                    "count": count,
                })
    return {"squares": squares, "hands": hands, "turn": "SENTE" if board.turn == shogi.BLACK else "GOTE"}


def japanese_variation(board: shogi.Board, moves: list[str] | None) -> list[str]:
    variation_board = shogi.Board(board.sfen())
    result: list[str] = []
    for move_text in moves or []:
        try:
            result.append(KifExporter.kif_move_from(move_text, variation_board))
            variation_board.push_usi(move_text)
        except (ValueError, IndexError, AttributeError):
            result.append(move_text)
            break
    return result



@router.get("", response_model=list[Game])
def list_games(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> list[GameModel]:
    statement = select(GameModel).where(GameModel.user_id == user.id).order_by(GameModel.created_at.desc())
    return list(db.scalars(statement))


@router.post("", response_model=Game, status_code=status.HTTP_202_ACCEPTED)
async def create_game(
    played_at: Annotated[date, Form()],
    user_side: Annotated[str, Form(pattern="^(SENTE|GOTE)$")],
    ownership_confirmed: Annotated[bool, Form()],
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    game_file: Annotated[UploadFile | None, File()] = None,
    game_text: Annotated[str | None, Form()] = None,
) -> GameModel:
    if not ownership_confirmed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="本人対局・未投稿であることへの同意が必要です。",
        )

    has_file = game_file is not None and bool(game_file.filename)
    pasted_text = (game_text or "").strip()
    if has_file == bool(pasted_text):
        raise HTTPException(status_code=422, detail="棋譜ファイルまたは貼り付け棋譜のどちらか一方を入力してください。")

    try:
        if has_file:
            filename = Path(game_file.filename or "").name
            if Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
                raise HTTPException(status_code=422, detail="KIF、KI2、CSA、TXTファイルを選択してください。")
            content = await game_file.read(settings.max_kif_size_bytes + 1)
            parsed = parse_game_file(content, filename, settings.max_kif_size_bytes)
            content_type = game_file.content_type
        else:
            parsed = parse_game_text(pasted_text, settings.max_kif_size_bytes)
            suffix = {"KIF": ".kif", "KI2": ".ki2", "CSA": ".csa", "TXT": ".txt"}[parsed.format]
            filename = f"clipboard-{played_at.isoformat()}{suffix}"
            content = pasted_text.encode("utf-8")
            content_type = "text/plain; charset=utf-8"
    except KifValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    duplicate = db.scalar(select(GameModel.id).where(GameModel.normalized_hash == parsed.normalized_hash))
    if duplicate is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="同じ指し手列の棋譜は投稿済みです。")

    try:
        stored_path = save_private_file(content, Path(filename).suffix)
    except MalwareDetectedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="棋譜ファイルを保存できませんでした。") from exc
    try:
        game = GameModel(
            user_id=user.id,
            original_filename=filename,
            event_name=parsed.event_name,
            sente_name=parsed.sente_name,
            gote_name=parsed.gote_name,
            storage_path=str(stored_path),
            content_type=content_type,
            file_size_bytes=len(content),
            source_encoding=parsed.encoding,
            played_at=played_at,
            user_side=user_side,
            initial_sfen=parsed.initial_sfen,
            usi_moves=parsed.usi_moves,
            move_count=len(parsed.usi_moves),
            normalized_hash=parsed.normalized_hash,
            analysis_status=AnalysisStatus.QUEUED.value,
        )
        db.add(game)
        db.flush()
        outbox = AnalysisJobOutbox(game_id=game.id) if settings.analysis_queue_enabled else None
        if outbox is not None:
            db.add(outbox)
        db.commit()
        db.refresh(game)
        if outbox is not None:
            db.refresh(outbox)
            dispatch_analysis_outbox(db, outbox.id)
        return game
    except IntegrityError as exc:
        db.rollback()
        remove_private_file(stored_path)
        raise HTTPException(status_code=409, detail="同じ指し手列の棋譜は投稿済みです。") from exc
    except Exception:
        db.rollback()
        remove_private_file(stored_path)
        raise

@router.delete("/{game_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_game(
    game_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> Response:
    game = db.get(GameModel, game_id)
    if game is None or game.user_id != user.id:
        raise HTTPException(status_code=404, detail="棋譜が見つかりません。")
    if db.scalar(select(RewardLedger.id).where(RewardLedger.game_id == game_id)) is not None:
        raise HTTPException(status_code=409, detail="報酬記録がある棋譜は削除できません。")

    try:
        remove_private_file(game.storage_path)
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="保存済み棋譜を削除できませんでした。") from exc

    submission_ids = select(CommentSubmission.id).where(CommentSubmission.game_id == game_id)
    try:
        db.execute(delete(CommentAnswer).where(CommentAnswer.submission_id.in_(submission_ids)))
        db.execute(delete(Review).where(Review.submission_id.in_(submission_ids)))
        db.execute(delete(CommentSubmission).where(CommentSubmission.game_id == game_id))
        db.execute(delete(CriticalPositionModel).where(CriticalPositionModel.game_id == game_id))
        db.execute(delete(AnalysisResult).where(AnalysisResult.game_id == game_id))
        db.execute(delete(AnalysisJobOutbox).where(AnalysisJobOutbox.game_id == game_id))
        db.delete(game)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.get("/{game_id}/playback")
def game_playback(
    game_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, object]:
    game = db.get(GameModel, game_id)
    if game is None or game.user_id != user.id:
        raise HTTPException(status_code=404, detail="棋譜が見つかりません。")

    submission = db.scalar(select(CommentSubmission).where(CommentSubmission.game_id == game_id))
    submitted = submission is not None and submission.submitted_at is not None
    test_user = bool(settings.ai_access_test_user_email) and user.email.lower() == settings.ai_access_test_user_email
    evaluation_visible = submitted or test_user
    ai_visible = has_ai_access(db, user.id) and (submitted or test_user)
    analyses = {
        item.move_number: item
        for item in db.scalars(select(AnalysisResult).where(AnalysisResult.game_id == game_id))
    }
    critical = {
        item.move_number: item
        for item in db.scalars(select(CriticalPositionModel).where(CriticalPositionModel.game_id == game_id))
    }
    comments: dict[int, list[dict[str, object]]] = {}
    if submission is not None:
        for answer in db.scalars(
            select(CommentAnswer)
            .where(CommentAnswer.submission_id == submission.id)
            .order_by(CommentAnswer.question_number)
        ):
            comments.setdefault(answer.critical_position_id, []).append({
                "question_number": answer.question_number,
                "question": QUESTION_LABELS[answer.question_number - 1],
                "answer": answer.answer_text,
            })

    board = shogi.Board(game.initial_sfen)
    frames: list[dict[str, object]] = [{
        "move_number": 0,
        "usi_move": None,
        "japanese_move": "開始局面",
        "board": board_snapshot(board),
        "evaluation": None,
        "win_rate": None,
        "principal_variation": None,
        "variations": None,
        "engine_name": None,
        "engine_version": None,
        "evaluation_function": None,
        "is_critical": False,
        "selection_reason": None,
        "comments": [],
    }]
    for move_number, move_text in enumerate(game.usi_moves, start=1):
        japanese_move = KifExporter.kif_move_from(move_text, board)
        board.push_usi(move_text)
        analysis = analyses.get(move_number)
        position = critical.get(move_number)
        frames.append({
            "move_number": move_number,
            "usi_move": move_text,
            "japanese_move": japanese_move,
            "board": board_snapshot(board),
            "evaluation": analysis.evaluation_user if evaluation_visible and analysis else None,
            "win_rate": analysis.win_rate_user if evaluation_visible and analysis else None,
            "principal_variation": japanese_variation(board, analysis.principal_variation) if ai_visible and analysis else None,
            "engine_name": analysis.engine_name if analysis else None,
            "engine_version": analysis.engine_version if analysis else None,
            "evaluation_function": analysis.search_conditions.get("evaluation_function") if analysis else None,
            "variations": [
                {
                    "evaluation": item.get("evaluation"),
                    "mate_in": item.get("mate_in"),
                    "principal_variation": japanese_variation(board, item.get("principal_variation")),
                }
                for item in (analysis.variations or [])[:5]
            ] if ai_visible and analysis else None,
            "is_critical": position is not None,
            "selection_reason": position.selection_reason if ai_visible and position else None,
            "comments": comments.get(position.id, []) if position else [],
        })

    return {
        "game_id": game.id,
        "filename": game.original_filename,
        "event_name": game.event_name,
        "sente_name": game.sente_name,
        "gote_name": game.gote_name,
        "user_side": game.user_side,
        "submitted": submitted,
        "test_evaluation_toggle_available": test_user,
        "ai_visible": ai_visible,
        "frames": frames,
    }

@router.get("/{game_id}/critical-positions", response_model=list[CriticalPosition])
def list_critical_positions(
    game_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> list[CriticalPosition]:
    game = db.get(GameModel, game_id)
    if game is None or game.user_id != user.id:
        raise HTTPException(status_code=404, detail="棋譜が見つかりません。")
    submission = db.scalar(select(CommentSubmission).where(CommentSubmission.game_id == game_id))
    submitted = submission is not None and submission.submitted_at is not None
    ai_visible = submitted and has_ai_access(db, user.id)
    statement = (
        select(CriticalPositionModel)
        .where(CriticalPositionModel.game_id == game_id)
        .order_by(CriticalPositionModel.move_number)
    )
    positions = list(db.scalars(statement))
    analyses = {
        item.move_number: item
        for item in db.scalars(select(AnalysisResult).where(AnalysisResult.game_id == game_id))
    } if ai_visible else {}
    return [
        CriticalPosition(
            id=item.id,
            game_id=item.game_id,
            move_number=item.move_number,
            japanese_move=japanese_move_at(game.initial_sfen, game.usi_moves, item.move_number),
            required=item.required,
            evaluation_before=item.evaluation_before if submitted else None,
            evaluation_after=item.evaluation_after if submitted else None,
            evaluation_delta=item.evaluation_delta if submitted else None,
            selection_reason=item.selection_reason if ai_visible else None,
            principal_variation=(
                analyses[item.move_number].principal_variation
                if item.move_number in analyses
                else []
            ) if ai_visible else None,
            engine_explanation_visible=submitted,
        )
        for item in positions
    ]
