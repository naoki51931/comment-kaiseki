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
    CriticalPosition as CriticalPositionModel, Game as GameModel, GameBranch, GameSkillAnalysis, Review, RewardLedger, User,
)
from app.schemas import BranchAnalysis, BranchPosition, BranchPositionRequest, BranchSaveRequest, CriticalPosition, Game, GameVisibilityUpdate, SavedBranch
from app.services.analysis import japanese_move_at, japanese_variation_at, normalize_evaluation, normalize_mate, win_rate
from app.services.engine import create_engine_adapter
from shogi.KIF import Exporter as KifExporter
from app.services.kif import KifValidationError, parse_game_file, parse_game_text
from app.services.professional_games import is_professional_game
from app.services.professional_names import matched_professional_names
from app.services.subscriptions import has_ai_access, has_permanent_access
from app.services.storage import MalwareDetectedError, remove_private_file, save_private_file
from app.tasks import dispatch_analysis_outbox


router = APIRouter()
ALLOWED_SUFFIXES = {".kif", ".ki2", ".csa", ".txt"}

QUESTION_LABELS = [
    "この局面で何を考えていましたか？",
    "どの候補手を比較しましたか？",
    "今振り返ると、判断の原因は何だったと思いますか？",
]


def can_view_all_games(user: User) -> bool:
    return bool(settings.global_game_viewer_email) and user.email.lower() == settings.global_game_viewer_email


def can_view_game(user: User, game: GameModel) -> bool:
    return game.user_id == user.id or can_view_all_games(user)


def game_view(game: GameModel, owner_email: str | None = None) -> Game:
    return Game.model_validate(game).model_copy(
        update={"owner_id": game.user_id, "owner_email": owner_email}
    )


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


def branch_position(game: GameModel, request: BranchPositionRequest) -> BranchPosition:
    if request.move_number > game.move_count:
        raise HTTPException(status_code=422, detail="分岐開始局面が棋譜の手数を超えています。")
    board = shogi.Board(game.initial_sfen)
    try:
        for move_text in game.usi_moves[:request.move_number]:
            board.push_usi(move_text)
        japanese_moves: list[str] = []
        for move_text in request.moves:
            move = shogi.Move.from_usi(move_text)
            if move not in board.legal_moves:
                raise ValueError
            japanese_moves.append(KifExporter.kif_move_from(move_text, board))
            board.push(move)
    except (ValueError, IndexError, AttributeError):
        raise HTTPException(status_code=422, detail="分岐手順に現在局面では指せない手が含まれています。") from None

    legal_moves = []
    for move in board.legal_moves:
        usi = move.usi()
        legal_moves.append({
            "usi": usi,
            "from_square": shogi.SQUARE_NAMES[move.from_square] if move.from_square is not None else None,
            "to_square": shogi.SQUARE_NAMES[move.to_square],
            # USIの駒打ちは P*5e のように大文字で表現する。
            "drop_piece": shogi.PIECE_SYMBOLS[move.drop_piece_type].upper() if move.drop_piece_type else None,
            "promote": move.promotion,
            "japanese_move": KifExporter.kif_move_from(usi, board),
        })
    return BranchPosition(
        board=board_snapshot(board), turn="SENTE" if board.turn == shogi.BLACK else "GOTE",
        moves=request.moves, japanese_moves=japanese_moves, legal_moves=legal_moves,
        game_over=board.is_game_over(),
    )


def branch_board(game: GameModel, request: BranchPositionRequest) -> shogi.Board:
    board = shogi.Board(game.initial_sfen)
    try:
        for move_text in game.usi_moves[:request.move_number]:
            board.push_usi(move_text)
        for move_text in request.moves:
            move = shogi.Move.from_usi(move_text)
            if move not in board.legal_moves:
                raise ValueError
            board.push(move)
    except (ValueError, IndexError, AttributeError):
        raise HTTPException(status_code=422, detail="分岐手順に現在局面では指せない手が含まれています。") from None
    return board



@router.get("", response_model=list[Game])
def list_games(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> list[Game]:
    statement = select(GameModel, User.email).join(User, User.id == GameModel.user_id)
    if not can_view_all_games(user):
        statement = statement.where(GameModel.user_id == user.id)
    rows = db.execute(statement.order_by(GameModel.created_at.desc())).all()
    return [game_view(game, owner_email) for game, owner_email in rows]


def public_game(db: Session, game_id: int) -> GameModel:
    game = db.get(GameModel, game_id)
    if game is None or not game.is_public:
        raise HTTPException(status_code=404, detail="公開棋譜が見つかりません。")
    return game


@router.get("/public/{game_id}/playback")
def public_game_playback(game_id: int, db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    game = public_game(db, game_id)
    owner = db.get(User, game.user_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="投稿ユーザーが見つかりません。")
    payload = game_playback(game_id=game_id, db=db, user=owner)
    payload["test_evaluation_toggle_available"] = False
    payload["ai_visible"] = False
    for frame in payload["frames"]:
        frame["evaluation"] = None
        frame["win_rate"] = None
        frame["principal_variation"] = None
        frame["variations"] = None
        frame["selection_reason"] = None
        frame["comments"] = []
    return payload


@router.post("/public/{game_id}/branch-position", response_model=BranchPosition)
def public_branch_position(
    game_id: int,
    request: BranchPositionRequest,
    db: Annotated[Session, Depends(get_db)],
) -> BranchPosition:
    return branch_position(public_game(db, game_id), request)


@router.post("/public/{game_id}/branch-analysis", response_model=BranchAnalysis)
def public_branch_analysis(
    game_id: int,
    request: BranchPositionRequest,
    db: Annotated[Session, Depends(get_db)],
) -> BranchAnalysis:
    game = public_game(db, game_id)
    if request.move_number > game.move_count:
        raise HTTPException(status_code=422, detail="分岐開始局面が棋譜の手数を超えています。")
    board = branch_board(game, request)
    engine = create_engine_adapter()
    try:
        result = engine.analyze(board.sfen())
    except (RuntimeError, TimeoutError, OSError):
        raise HTTPException(status_code=503, detail="解析エンジンが応答しませんでした。時間をおいて再度お試しください。") from None
    finally:
        close = getattr(engine, "close", None)
        if close is not None:
            close()
    evaluation = normalize_evaluation(result.score_side_to_move, side_to_move=board.turn, user_side=game.user_side)
    mate_in = normalize_mate(result.mate_in, side_to_move=board.turn, user_side=game.user_side)
    variations = [{
        "evaluation": normalize_evaluation(item.score_side_to_move, side_to_move=board.turn, user_side=game.user_side),
        "mate_in": normalize_mate(item.mate_in, side_to_move=board.turn, user_side=game.user_side),
        "principal_variation": japanese_variation(board, item.principal_variation),
        "usi_principal_variation": item.principal_variation,
    } for item in (result.variations or [result])[:5]]
    return BranchAnalysis(
        evaluation=evaluation, mate_in=mate_in, win_rate=win_rate(evaluation or 0, mate_in),
        engine_name=engine.name, engine_version=engine.version,
        evaluation_function=getattr(engine, "evaluation_name", None), variations=variations,
    )


@router.post("", response_model=Game, status_code=status.HTTP_202_ACCEPTED)
async def create_game(
    played_at: Annotated[date, Form()],
    user_side: Annotated[str, Form(pattern="^(SENTE|GOTE)$")],
    ownership_confirmed: Annotated[bool, Form()],
    posting_terms_agreed: Annotated[bool, Form()],
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    is_public: Annotated[bool, Form()] = False,
    professional_name_confirmed: Annotated[bool, Form()] = False,
    game_file: Annotated[UploadFile | None, File()] = None,
    game_text: Annotated[str | None, Form()] = None,
) -> GameModel:
    if not ownership_confirmed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="本人対局・未投稿であることへの同意が必要です。",
        )
    if not posting_terms_agreed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="棋譜投稿規約への同意が必要です。プロ公式戦棋譜は投稿できません。",
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

    professional_matches = matched_professional_names(parsed.sente_name, parsed.gote_name)
    if professional_matches and not professional_name_confirmed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "PROFESSIONAL_NAME_CONFIRMATION_REQUIRED",
                "message": "プロ棋士の棋譜の可能性があります。本人対局で、プロ公式戦ではない場合のみ登録を続けられます。登録しますか？",
                "matched_names": professional_matches,
            },
        )

    if is_professional_game(db, parsed.normalized_hash):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="プロ公式戦と一致する棋譜は投稿できません。ご本人が対局した棋譜だけを投稿してください。",
        )
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
            is_public=is_public,
            professional_name_suspected=bool(professional_matches),
            professional_name_matches=professional_matches,
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


@router.post("/{game_id}/reanalyze", response_model=Game, status_code=status.HTTP_202_ACCEPTED)
def reanalyze_game(
    game_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> GameModel:
    game = db.get(GameModel, game_id)
    if game is None or game.user_id != user.id:
        raise HTTPException(status_code=404, detail="棋譜が見つかりません。")
    if game.analysis_status in {AnalysisStatus.QUEUED.value, AnalysisStatus.ANALYZING.value}:
        raise HTTPException(status_code=409, detail="この棋譜はすでに解析待ち、または解析中です。")
    db.execute(delete(GameSkillAnalysis).where(GameSkillAnalysis.game_id == game_id))
    outbox = db.scalar(select(AnalysisJobOutbox).where(AnalysisJobOutbox.game_id == game_id))
    if settings.analysis_queue_enabled:
        if outbox is None:
            outbox = AnalysisJobOutbox(game_id=game.id)
            db.add(outbox)
        else:
            outbox.sent_at = None
            outbox.attempt_count = 0
            outbox.last_error = None
    game.analysis_status = AnalysisStatus.QUEUED.value
    game.analysis_error = None
    game.analysis_retry_count = 0
    game.analysis_started_at = None
    game.analysis_completed_at = None
    db.commit()
    db.refresh(game)
    if outbox is not None:
        db.refresh(outbox)
        dispatch_analysis_outbox(db, outbox.id)
    return game


@router.patch("/{game_id}/visibility", response_model=Game)
def update_game_visibility(
    game_id: int,
    payload: GameVisibilityUpdate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> GameModel:
    game = db.get(GameModel, game_id)
    if game is None or game.user_id != user.id:
        raise HTTPException(status_code=404, detail="棋譜が見つかりません。")
    game.is_public = payload.is_public
    db.commit()
    db.refresh(game)
    return game

@router.get("/{game_id}/playback")
def game_playback(
    game_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, object]:
    game = db.get(GameModel, game_id)
    if game is None or not can_view_game(user, game):
        raise HTTPException(status_code=404, detail="棋譜が見つかりません。")

    submission = db.scalar(select(CommentSubmission).where(CommentSubmission.game_id == game_id))
    submitted = submission is not None and submission.submitted_at is not None
    test_user = bool(settings.ai_access_test_user_email) and user.email.lower() == settings.ai_access_test_user_email
    permanent_access = has_permanent_access(db, user.id)
    evaluation_visible = submitted or test_user or permanent_access
    ai_visible = has_ai_access(db, user.id) and (submitted or test_user or permanent_access)
    analyses = {
        item.move_number: item
        for item in db.scalars(select(AnalysisResult).where(AnalysisResult.game_id == game_id))
    }
    critical = {
        item.move_number: item
        for item in db.scalars(select(CriticalPositionModel).where(CriticalPositionModel.game_id == game_id))
    }
    comments: dict[int, list[dict[str, object]]] = {}
    if submission is not None and (game.user_id == user.id or submitted):
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
        "test_evaluation_toggle_available": test_user or permanent_access,
        "ai_visible": ai_visible,
        "frames": frames,
    }


@router.post("/{game_id}/branch-position", response_model=BranchPosition)
def get_branch_position(
    game_id: int,
    request: BranchPositionRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> BranchPosition:
    game = db.get(GameModel, game_id)
    if game is None or not can_view_game(user, game):
        raise HTTPException(status_code=404, detail="棋譜が見つかりません。")
    return branch_position(game, request)


@router.post("/{game_id}/branch-analysis", response_model=BranchAnalysis)
def analyze_branch_position(
    game_id: int,
    request: BranchPositionRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> BranchAnalysis:
    game = db.get(GameModel, game_id)
    if game is None or not can_view_game(user, game):
        raise HTTPException(status_code=404, detail="棋譜が見つかりません。")
    submission = db.scalar(select(CommentSubmission).where(CommentSubmission.game_id == game_id))
    submitted = submission is not None and submission.submitted_at is not None
    test_user = bool(settings.ai_access_test_user_email) and user.email.lower() == settings.ai_access_test_user_email
    permanent_access = has_permanent_access(db, user.id)
    if not can_view_all_games(user) and (
        not has_ai_access(db, user.id) or not (submitted or test_user or permanent_access)
    ):
        raise HTTPException(status_code=403, detail="分岐解析はコメント提出後、AI解説プランで利用できます。")
    if request.move_number > game.move_count:
        raise HTTPException(status_code=422, detail="分岐開始局面が棋譜の手数を超えています。")
    board = branch_board(game, request)
    engine = create_engine_adapter()
    try:
        result = engine.analyze(board.sfen())
    except (RuntimeError, TimeoutError, OSError):
        raise HTTPException(status_code=503, detail="解析エンジンが応答しませんでした。時間をおいて再度お試しください。") from None
    finally:
        close = getattr(engine, "close", None)
        if close is not None:
            close()
    evaluation = normalize_evaluation(result.score_side_to_move, side_to_move=board.turn, user_side=game.user_side)
    mate_in = normalize_mate(result.mate_in, side_to_move=board.turn, user_side=game.user_side)
    variations = []
    for item in (result.variations or [result])[:5]:
        variations.append({
            "evaluation": normalize_evaluation(item.score_side_to_move, side_to_move=board.turn, user_side=game.user_side),
            "mate_in": normalize_mate(item.mate_in, side_to_move=board.turn, user_side=game.user_side),
            "principal_variation": japanese_variation(board, item.principal_variation),
            # 日本語表記だけでは分岐盤へ候補手を適用できないため、盤面操作用のUSIも返す。
            "usi_principal_variation": item.principal_variation,
        })
    return BranchAnalysis(
        evaluation=evaluation, mate_in=mate_in, win_rate=win_rate(evaluation or 0, mate_in),
        engine_name=engine.name, engine_version=engine.version,
        evaluation_function=getattr(engine, "evaluation_name", None), variations=variations,
    )


@router.get("/{game_id}/branches", response_model=list[SavedBranch])
def list_game_branches(
    game_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> list[GameBranch]:
    game = db.get(GameModel, game_id)
    if game is None or game.user_id != user.id:
        raise HTTPException(status_code=404, detail="棋譜が見つかりません。")
    return list(db.scalars(select(GameBranch).where(GameBranch.game_id == game_id, GameBranch.user_id == user.id).order_by(GameBranch.id)))


@router.post("/{game_id}/branches", response_model=SavedBranch, status_code=status.HTTP_201_CREATED)
def save_game_branch(
    game_id: int,
    request: BranchSaveRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> GameBranch:
    game = db.get(GameModel, game_id)
    if game is None or game.user_id != user.id:
        raise HTTPException(status_code=404, detail="棋譜が見つかりません。")
    if not request.moves:
        raise HTTPException(status_code=422, detail="1手以上指してから分岐を保存してください。")
    if request.move_number > game.move_count:
        raise HTTPException(status_code=422, detail="分岐開始局面が棋譜の手数を超えています。")
    board = branch_board(game, BranchPositionRequest(move_number=request.move_number, moves=[]))
    japanese_moves: list[str] = []
    for move_text in request.moves:
        move = shogi.Move.from_usi(move_text)
        if move not in board.legal_moves:
            raise HTTPException(status_code=422, detail="分岐手順に現在局面では指せない手が含まれています。")
        japanese_moves.append(KifExporter.kif_move_from(move_text, board))
        board.push(move)
    count = len(list(db.scalars(select(GameBranch.id).where(GameBranch.game_id == game_id))))
    branch = GameBranch(game_id=game_id, user_id=user.id, name=f"分岐{count + 1}", base_move_number=request.move_number, usi_moves=request.moves, japanese_moves=japanese_moves)
    db.add(branch)
    db.commit()
    db.refresh(branch)
    return branch


@router.delete("/{game_id}/branches/{branch_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_game_branch(
    game_id: int,
    branch_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> Response:
    game = db.get(GameModel, game_id)
    if game is None or game.user_id != user.id:
        raise HTTPException(status_code=404, detail="棋譜が見つかりません。")
    branch = db.scalar(select(GameBranch).where(
        GameBranch.id == branch_id, GameBranch.game_id == game_id, GameBranch.user_id == user.id,
    ))
    if branch is None:
        raise HTTPException(status_code=404, detail="分岐が見つかりません。")
    db.delete(branch)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{game_id}/comment-position/{move_number}", response_model=CriticalPosition, status_code=status.HTTP_201_CREATED)
def create_comment_position(
    game_id: int,
    move_number: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> CriticalPosition:
    game = db.get(GameModel, game_id)
    if game is None or game.user_id != user.id:
        raise HTTPException(status_code=404, detail="棋譜が見つかりません。")
    if move_number < 1 or move_number > game.move_count:
        raise HTTPException(status_code=422, detail="コメントする局面を1手目以降から選択してください。")
    submission = db.scalar(select(CommentSubmission).where(CommentSubmission.game_id == game_id))
    if submission is not None and submission.submitted_at is not None:
        raise HTTPException(status_code=409, detail="提出済みコメントには局面を追加できません。")
    existing = db.scalar(select(CriticalPositionModel).where(
        CriticalPositionModel.game_id == game_id, CriticalPositionModel.move_number == move_number
    ))
    if existing is None:
        current = db.scalar(select(AnalysisResult).where(
            AnalysisResult.game_id == game_id, AnalysisResult.move_number == move_number
        ))
        previous = db.scalar(select(AnalysisResult).where(
            AnalysisResult.game_id == game_id, AnalysisResult.move_number == move_number - 1
        )) if move_number > 1 else None
        after = current.evaluation_user if current and current.evaluation_user is not None else 0
        before = previous.evaluation_user if previous and previous.evaluation_user is not None else 0
        existing = CriticalPositionModel(
            game_id=game_id, move_number=move_number,
            japanese_move=japanese_move_at(game.initial_sfen, game.usi_moves, move_number),
            evaluation_before=before, evaluation_after=after, evaluation_delta=after - before,
            selection_reason="ユーザーがコメント対象として指定",
            extraction_metadata={"source": "user_selected"}, required=False,
        )
        db.add(existing)
        db.commit()
        db.refresh(existing)
    submitted = submission is not None and submission.submitted_at is not None
    evaluation_visible = submitted or has_permanent_access(db, user.id)
    return CriticalPosition(
        id=existing.id, game_id=existing.game_id, move_number=existing.move_number,
        japanese_move=existing.japanese_move, required=existing.required,
        evaluation_before=existing.evaluation_before if evaluation_visible else None,
        evaluation_after=existing.evaluation_after if evaluation_visible else None,
        evaluation_delta=existing.evaluation_delta if evaluation_visible else None,
        selection_reason=None, principal_variation=None, engine_explanation_visible=evaluation_visible,
    )


@router.get("/{game_id}/critical-positions", response_model=list[CriticalPosition])
def list_critical_positions(
    game_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> list[CriticalPosition]:
    game = db.get(GameModel, game_id)
    if game is None or not can_view_game(user, game):
        raise HTTPException(status_code=404, detail="棋譜が見つかりません。")
    submission = db.scalar(select(CommentSubmission).where(CommentSubmission.game_id == game_id))
    submitted = submission is not None and submission.submitted_at is not None
    evaluation_visible = submitted or has_permanent_access(db, user.id)
    ai_visible = has_ai_access(db, user.id) and (submitted or has_permanent_access(db, user.id))
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
            evaluation_before=item.evaluation_before if evaluation_visible else None,
            evaluation_after=item.evaluation_after if evaluation_visible else None,
            evaluation_delta=item.evaluation_delta if evaluation_visible else None,
            selection_reason=item.selection_reason if ai_visible else None,
            principal_variation=(
                japanese_variation_at(game.initial_sfen, game.usi_moves, item.move_number, analyses[item.move_number].principal_variation)
                if item.move_number in analyses
                else []
            ) if ai_visible else None,
            engine_explanation_visible=evaluation_visible,
        )
        for item in positions
    ]
