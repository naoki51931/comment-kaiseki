from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.dependencies import get_current_user
from app.config import settings
from app.models import User


router = APIRouter()


@router.get("/android")
def download_android_apk(
    user: Annotated[User, Depends(get_current_user)],
) -> FileResponse:
    allowed_email = settings.android_apk_allowed_email
    if not allowed_email or user.email.lower() != allowed_email:
        raise HTTPException(status_code=403, detail="このファイルをダウンロードする権限がありません。")
    if not settings.android_apk_path.is_file():
        raise HTTPException(status_code=404, detail="Androidアプリを準備中です。")
    return FileResponse(
        settings.android_apk_path,
        media_type="application/vnd.android.package-archive",
        filename="kifu-comment-lab.apk",
    )
