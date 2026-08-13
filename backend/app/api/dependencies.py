from typing import Annotated

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.services.security import decode_access_token


bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="ログインが必要です。")
    try:
        user_id = decode_access_token(credentials.credentials)
    except (jwt.InvalidTokenError, ValueError):
        raise HTTPException(status_code=401, detail="アクセストークンが無効です。")
    user = db.get(User, user_id)
    if user is None or not user.email_verified:
        raise HTTPException(status_code=401, detail="ユーザーを確認できません。")
    return user


def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="管理者権限が必要です。")
    if not user.mfa_enabled:
        raise HTTPException(status_code=403, detail="管理者はMFAの設定が必要です。")
    return user
