from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import SearchResponse
from app.services.search import search_weaviate, sync_user_index

router = APIRouter()


@router.get("", response_model=SearchResponse)
def search(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    q: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SearchResponse:
    results = search_weaviate(db, user.id, q.strip(), limit)
    backend = results[0]["backend"] if results else "weaviate"
    return SearchResponse(query=q.strip(), backend=backend, results=results)


@router.post("/reindex")
def reindex(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, object]:
    count = sync_user_index(db, user.id)
    return {"indexed": count, "backend": "weaviate"}
