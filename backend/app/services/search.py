from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AiComment, CommentAnswer, CommentSubmission, CriticalPosition, Game

logger = logging.getLogger(__name__)
COLLECTION = "KifuSearchDocument"


@dataclass(frozen=True)
class SearchDocument:
    source_type: str
    source_id: int
    game_id: int
    move_number: int | None
    title: str
    text: str
    event_name: str
    user_id: int

    @property
    def object_id(self) -> str:
        return str(uuid5(NAMESPACE_URL, f"kifu-comment:{self.source_type}:{self.source_id}"))

    def properties(self) -> dict[str, object]:
        return {
            "sourceType": self.source_type,
            "sourceId": self.source_id,
            "gameId": self.game_id,
            "moveNumber": self.move_number or 0,
            "title": self.title,
            "text": self.text,
            "eventName": self.event_name,
            "userId": self.user_id,
        }


def _client() -> httpx.Client:
    headers = {"Content-Type": "application/json"}
    if settings.weaviate_api_key:
        headers["Authorization"] = f"Bearer {settings.weaviate_api_key}"
    return httpx.Client(base_url=settings.weaviate_url, headers=headers, timeout=settings.weaviate_timeout_seconds)


def ensure_schema(client: httpx.Client) -> None:
    response = client.get(f"/v1/schema/{COLLECTION}")
    if response.status_code == 200:
        return
    if response.status_code != 404:
        response.raise_for_status()
    payload = {
        "class": COLLECTION,
        "description": "棋譜、重要局面、提出コメント、AIコメントの所有者別検索索引",
        "vectorizer": "none",
        "properties": [
            {"name": "sourceType", "dataType": ["text"], "indexFilterable": True},
            {"name": "sourceId", "dataType": ["int"], "indexFilterable": True},
            {"name": "gameId", "dataType": ["int"], "indexFilterable": True},
            {"name": "moveNumber", "dataType": ["int"], "indexFilterable": True},
            {"name": "title", "dataType": ["text"], "tokenization": "gse"},
            {"name": "text", "dataType": ["text"], "tokenization": "gse"},
            {"name": "eventName", "dataType": ["text"], "tokenization": "gse"},
            {"name": "userId", "dataType": ["int"], "indexFilterable": True},
        ],
    }
    created = client.post("/v1/schema", json=payload)
    if created.status_code not in {200, 201, 422}:
        created.raise_for_status()


def documents_for_user(db: Session, user_id: int) -> list[SearchDocument]:
    games = list(db.scalars(select(Game).where(Game.user_id == user_id)))
    documents: list[SearchDocument] = []
    for game in games:
        metadata = " / ".join(filter(None, [game.event_name, game.sente_name, game.gote_name]))
        documents.append(SearchDocument("game", game.id, game.id, None, game.original_filename, metadata or game.original_filename, game.event_name or "", user_id))

    positions = list(db.scalars(select(CriticalPosition).join(Game).where(Game.user_id == user_id)))
    game_by_id = {game.id: game for game in games}
    for position in positions:
        game = game_by_id[position.game_id]
        documents.append(SearchDocument("critical_position", position.id, game.id, position.move_number, f"{position.move_number}手目・{position.japanese_move}", position.selection_reason, game.event_name or "", user_id))

    submitted_answers = list(db.execute(
        select(CommentAnswer, CriticalPosition, Game)
        .join(CommentSubmission, CommentSubmission.id == CommentAnswer.submission_id)
        .join(CriticalPosition, CriticalPosition.id == CommentAnswer.critical_position_id)
        .join(Game, Game.id == CriticalPosition.game_id)
        .where(Game.user_id == user_id, CommentSubmission.submitted_at.is_not(None))
    ))
    for answer, position, game in submitted_answers:
        documents.append(SearchDocument("comment_answer", answer.id, game.id, position.move_number, f"{position.move_number}手目・回答{answer.question_number}", answer.answer_text, game.event_name or "", user_id))

    ai_comments = list(db.execute(
        select(AiComment, CriticalPosition, Game)
        .join(CriticalPosition, CriticalPosition.id == AiComment.critical_position_id)
        .join(Game, Game.id == CriticalPosition.game_id)
        .where(Game.user_id == user_id)
    ))
    for comment, position, game in ai_comments:
        documents.append(SearchDocument("ai_comment", comment.id, game.id, position.move_number, f"{position.move_number}手目・AIコメント", comment.current_text, game.event_name or "", user_id))
    return documents


def sync_user_index(db: Session, user_id: int) -> int:
    if not settings.weaviate_enabled:
        return 0
    documents = documents_for_user(db, user_id)
    with _client() as client:
        ensure_schema(client)
        for document in documents:
            existing = client.get(f"/v1/objects/{document.object_id}", params={"class": COLLECTION})
            payload = {"class": COLLECTION, "id": document.object_id, "properties": document.properties()}
            if existing.status_code == 200:
                response = client.put(f"/v1/objects/{document.object_id}", json=payload)
            elif existing.status_code == 404:
                response = client.post("/v1/objects", json=payload)
            else:
                existing.raise_for_status()
            if response.status_code not in {200, 201}:
                response.raise_for_status()
    return len(documents)


def search_weaviate(db: Session, user_id: int, query: str, limit: int) -> list[dict[str, object]]:
    if not settings.weaviate_enabled:
        return search_database(db, user_id, query, limit)
    try:
        sync_user_index(db, user_id)
        query_literal = json.dumps(query, ensure_ascii=False)
        graphql = f"""{{Get{{{COLLECTION}(
          bm25: {{query: {query_literal}, properties: ["title^2", "text", "eventName"]}}
          where: {{path: [\"userId\"], operator: Equal, valueNumber: {user_id}}}
          limit: {limit}
        ){{sourceType sourceId gameId moveNumber title text eventName _additional{{score}}}}}}}}"""
        with _client() as client:
            response = client.post("/v1/graphql", json={"query": graphql})
            response.raise_for_status()
            body = response.json()
        if body.get("errors"):
            raise RuntimeError(str(body["errors"]))
        owned_game_ids = set(db.scalars(select(Game.id).where(Game.user_id == user_id)))
        rows = body.get("data", {}).get("Get", {}).get(COLLECTION, [])
        return [
            {
                "source_type": row["sourceType"],
                "source_id": row["sourceId"],
                "game_id": row["gameId"],
                "move_number": row["moveNumber"] or None,
                "title": row["title"],
                "text": row["text"],
                "event_name": row.get("eventName") or None,
                "score": float(row.get("_additional", {}).get("score") or 0),
                "backend": "weaviate",
            }
            for row in rows
            if row["gameId"] in owned_game_ids
        ]
    except (httpx.HTTPError, RuntimeError, ValueError, KeyError) as exc:
        logger.warning("Weaviate search failed; using database fallback: %s", exc)
        return search_database(db, user_id, query, limit)


def search_database(db: Session, user_id: int, query: str, limit: int) -> list[dict[str, object]]:
    needle = f"%{query}%"
    results: list[dict[str, object]] = []
    games = list(db.scalars(select(Game).where(Game.user_id == user_id, or_(Game.original_filename.ilike(needle), Game.event_name.ilike(needle), Game.sente_name.ilike(needle), Game.gote_name.ilike(needle))).limit(limit)))
    for game in games:
        results.append({"source_type": "game", "source_id": game.id, "game_id": game.id, "move_number": None, "title": game.original_filename, "text": " / ".join(filter(None, [game.event_name, game.sente_name, game.gote_name])), "event_name": game.event_name, "score": 0.0, "backend": "database"})
    if len(results) < limit:
        answers = list(db.execute(select(CommentAnswer, CriticalPosition, Game).join(CommentSubmission, CommentSubmission.id == CommentAnswer.submission_id).join(CriticalPosition, CriticalPosition.id == CommentAnswer.critical_position_id).join(Game, Game.id == CriticalPosition.game_id).where(Game.user_id == user_id, CommentSubmission.submitted_at.is_not(None), CommentAnswer.answer_text.ilike(needle)).limit(limit - len(results))))
        for answer, position, game in answers:
            results.append({"source_type": "comment_answer", "source_id": answer.id, "game_id": game.id, "move_number": position.move_number, "title": f"{position.move_number}手目・回答{answer.question_number}", "text": answer.answer_text, "event_name": game.event_name, "score": 0.0, "backend": "database"})
    return results[:limit]
