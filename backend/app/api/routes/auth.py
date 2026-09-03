from datetime import datetime, timedelta, timezone
from uuid import uuid4
from typing import Annotated

import pyotp
from google.auth.exceptions import GoogleAuthError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.config import settings
from app.database import get_db
from app.models import EmailVerificationToken, PasswordResetToken, RefreshToken, User
from app.services.email import send_password_reset_email, send_verification_email
from app.services.security import (
    create_access_token,
    decrypt_secret,
    encrypt_secret,
    generate_mfa_secret,
    hash_password,
    new_opaque_token,
    token_hash,
    verify_mfa,
    verify_password,
)


router = APIRouter()
def expired(value: datetime, now: datetime) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value < now


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class RegisterResponse(BaseModel):
    message: str
    verification_token: str | None = None


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(min_length=1)
    password: str = Field(min_length=12, max_length=128)


class VerifyRequest(BaseModel):
    token: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    mfa_code: str | None = None


class GoogleLoginRequest(BaseModel):
    credential: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class MfaCode(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


@router.post("/register", response_model=RegisterResponse, status_code=201)
def register(payload: RegisterRequest, request: Request, db: Annotated[Session, Depends(get_db)]) -> RegisterResponse:
    email = payload.email.lower()
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status_code=409, detail="このメールアドレスは登録済みです。")
    user = User(email=email, password_hash=hash_password(payload.password))
    db.add(user)
    db.flush()
    plain_token = new_opaque_token()
    db.add(
        EmailVerificationToken(
            user_id=user.id,
            token_hash=token_hash(plain_token),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
    )
    db.commit()
    forwarded_host = request.headers.get("x-forwarded-host")
    host = forwarded_host or request.headers.get("host", "localhost")
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    base_url = settings.public_base_url or f"{scheme}://{host}"
    verification_url = f"{base_url}/api/auth/verify-email?token={plain_token}"
    try:
        send_verification_email(email, verification_url)
    except OSError as exc:
        failed_token = db.scalar(select(EmailVerificationToken).where(
            EmailVerificationToken.token_hash == token_hash(plain_token)
        ))
        if failed_token is not None:
            db.delete(failed_token)
            db.commit()
        raise HTTPException(status_code=503, detail="確認メールを送信できませんでした。再送をお試しください。") from exc
    return RegisterResponse(
        message="確認メールを送信しました。リンクの有効期限は24時間です。",
        verification_token=plain_token if settings.expose_verification_token else None,
    )


@router.post("/resend-verification")
def resend_verification(
    payload: ResendVerificationRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    message = "未認証のアドレスであれば確認メールを送信しました。"
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or user.email_verified:
        return {"message": message}
    now = datetime.now(timezone.utc)
    latest = db.scalar(
        select(EmailVerificationToken)
        .where(EmailVerificationToken.user_id == user.id)
        .order_by(EmailVerificationToken.created_at.desc())
    )
    if latest is not None:
        created_at = latest.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        if (now - created_at).total_seconds() < settings.email_resend_cooldown_seconds:
            raise HTTPException(status_code=429, detail="確認メールの再送はしばらく待ってからお試しください。")
    plain_token = new_opaque_token()
    tokens = list(db.scalars(
        select(EmailVerificationToken).where(
            EmailVerificationToken.user_id == user.id,
            EmailVerificationToken.used_at.is_(None),
        )
    ))
    for stored in tokens:
        stored.used_at = now
    db.add(EmailVerificationToken(
        user_id=user.id,
        token_hash=token_hash(plain_token),
        expires_at=now + timedelta(hours=24),
    ))
    forwarded_host = request.headers.get("x-forwarded-host")
    host = forwarded_host or request.headers.get("host", "localhost")
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    base_url = settings.public_base_url or f"{scheme}://{host}"
    try:
        send_verification_email(user.email, f"{base_url}/api/auth/verify-email?token={plain_token}")
    except OSError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="確認メールを送信できませんでした。再送をお試しください。") from exc
    db.commit()
    response: dict[str, object] = {"message": message}
    if settings.expose_verification_token:
        response["verification_token"] = plain_token
    return response


@router.post("/request-password-reset")
def request_password_reset(payload: PasswordResetRequest, request: Request, db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    message = "登録済みのアドレスであれば、パスワード再設定メールを送信しました。"
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not user.email_verified:
        return {"message": message}
    now = datetime.now(timezone.utc)
    latest = db.scalar(select(PasswordResetToken).where(PasswordResetToken.user_id == user.id).order_by(PasswordResetToken.created_at.desc()))
    if latest is not None:
        created_at = latest.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        if (now - created_at).total_seconds() < settings.email_resend_cooldown_seconds:
            raise HTTPException(status_code=429, detail="再設定メールの送信はしばらく待ってからお試しください。")
    plain_token = new_opaque_token()
    for stored in db.scalars(select(PasswordResetToken).where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))):
        stored.used_at = now
    db.add(PasswordResetToken(user_id=user.id, token_hash=token_hash(plain_token), expires_at=now + timedelta(hours=1)))
    forwarded_host = request.headers.get("x-forwarded-host")
    host = forwarded_host or request.headers.get("host", "localhost")
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    base_url = settings.public_base_url or f"{scheme}://{host}"
    try:
        send_password_reset_email(user.email, f"{base_url}/reset-password?token={plain_token}")
    except OSError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="再設定メールを送信できませんでした。時間をおいて再度お試しください。") from exc
    db.commit()
    response: dict[str, object] = {"message": message}
    if settings.expose_verification_token:
        response["reset_token"] = plain_token
    return response


@router.post("/reset-password")
def reset_password(payload: PasswordResetConfirmRequest, db: Annotated[Session, Depends(get_db)]) -> dict[str, str]:
    stored = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash(payload.token)))
    now = datetime.now(timezone.utc)
    if stored is None or stored.used_at is not None or expired(stored.expires_at, now):
        raise HTTPException(status_code=422, detail="再設定リンクが無効または期限切れです。")
    user = db.get(User, stored.user_id)
    if user is None:
        raise HTTPException(status_code=422, detail="再設定リンクが無効または期限切れです。")
    user.password_hash = hash_password(payload.password)
    stored.used_at = now
    for refresh_token in db.scalars(select(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))):
        refresh_token.revoked_at = now
    db.commit()
    return {"message": "パスワードを変更しました。新しいパスワードでログインしてください。"}


def consume_verification(token: str, db: Session) -> None:
    verification = db.scalar(
        select(EmailVerificationToken).where(EmailVerificationToken.token_hash == token_hash(token))
    )
    now = datetime.now(timezone.utc)
    if verification is None or verification.used_at is not None or expired(verification.expires_at, now):
        raise HTTPException(status_code=422, detail="確認トークンが無効または期限切れです。")
    user = db.get(User, verification.user_id)
    if user is None:
        raise HTTPException(status_code=422, detail="ユーザーが見つかりません。")
    user.email_verified = True
    verification.used_at = now
    db.commit()


@router.post("/verify-email", status_code=204)
def verify_email(payload: VerifyRequest, db: Annotated[Session, Depends(get_db)]) -> None:
    consume_verification(payload.token, db)


@router.get("/verify-email")
def verify_email_link(token: str, db: Annotated[Session, Depends(get_db)]) -> RedirectResponse:
    consume_verification(token, db)
    return RedirectResponse(url="/?verified=1", status_code=303)


def issue_tokens(db: Session, user: User, *, admin_authenticated: bool = False) -> TokenResponse:
    refresh = new_opaque_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=token_hash(refresh),
            admin_authenticated=admin_authenticated,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.login_session_hours),
        )
    )
    db.commit()
    return TokenResponse(
        access_token=create_access_token(user.id, admin_authenticated),
        refresh_token=refresh,
    )


@router.post("/anonymous", response_model=TokenResponse, status_code=201)
def anonymous_login(db: Annotated[Session, Depends(get_db)]) -> TokenResponse:
    """個人情報を求めず、通常と同じ所有者制御が使える匿名セッションを作る。"""
    user = User(
        email=f"anonymous-{uuid4().hex}@anonymous.invalid",
        password_hash=None,
        email_verified=True,
    )
    db.add(user)
    db.flush()
    return issue_tokens(db, user)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Annotated[Session, Depends(get_db)]) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not verify_password(user.password_hash, payload.password):
        raise HTTPException(status_code=401, detail="メールアドレスまたはパスワードが違います。")
    if not user.email_verified:
        raise HTTPException(status_code=403, detail="メール認証を完了してください。")
    admin_authenticated = False
    if user.is_admin and payload.mfa_code:
        if not user.mfa_enabled:
            raise HTTPException(status_code=403, detail="管理者はMFAの設定が必要です。")
        if not verify_mfa(decrypt_secret(user.mfa_secret_encrypted or ""), payload.mfa_code):
            raise HTTPException(status_code=401, detail="MFAコードが無効です。")
        admin_authenticated = True
    return issue_tokens(db, user, admin_authenticated=admin_authenticated)


@router.post("/google", response_model=TokenResponse)
def google_login(payload: GoogleLoginRequest, db: Annotated[Session, Depends(get_db)]) -> TokenResponse:
    if not settings.google_client_id:
        raise HTTPException(status_code=503, detail="Googleログインは現在利用できません。")
    try:
        claims = id_token.verify_oauth2_token(payload.credential, google_requests.Request(), settings.google_client_id)
    except (ValueError, GoogleAuthError) as exc:
        raise HTTPException(status_code=401, detail="Googleの認証情報を確認できませんでした。") from exc
    subject = claims.get("sub")
    email = claims.get("email")
    if not subject or not email or claims.get("email_verified") is not True:
        raise HTTPException(status_code=401, detail="確認済みGoogleアカウントが必要です。")
    user = db.scalar(select(User).where(User.google_subject == subject))
    if user is None:
        normalized_email = str(email).lower()
        existing_user = db.scalar(select(User).where(User.email == normalized_email))
        if existing_user is not None:
            if existing_user.google_subject not in (None, str(subject)):
                raise HTTPException(status_code=409, detail="このメールアドレスには別のGoogleアカウントが連携されています。")
            existing_user.google_subject = str(subject)
            user = existing_user
        else:
            user = User(email=normalized_email, password_hash=None, google_subject=str(subject), email_verified=True)
            db.add(user)
            db.flush()
    return issue_tokens(db, user)


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: Annotated[Session, Depends(get_db)]) -> TokenResponse:
    stored = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash(payload.refresh_token)))
    now = datetime.now(timezone.utc)
    if (
        stored is None
        or stored.revoked_at is not None
        or expired(stored.expires_at, now)
        or expired(stored.created_at + timedelta(hours=settings.login_session_hours), now)
    ):
        raise HTTPException(status_code=401, detail="更新トークンが無効です。")
    stored.revoked_at = now
    user = db.get(User, stored.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="ユーザーが見つかりません。")
    return issue_tokens(db, user, admin_authenticated=stored.admin_authenticated and user.is_admin)


@router.get("/me")
def me(user: Annotated[User, Depends(get_current_user)]) -> dict[str, object]:
    anonymous = user.email.endswith("@anonymous.invalid")
    return {
        "id": user.id,
        "email": "匿名ユーザー" if anonymous else user.email,
        "is_admin": user.is_admin and getattr(user, "_admin_authenticated", False),
        "mfa_enabled": user.mfa_enabled,
        "android_apk_download_allowed": bool(settings.android_apk_allowed_email)
        and user.email.lower() == settings.android_apk_allowed_email,
        "global_game_viewer": bool(settings.global_game_viewer_email)
        and user.email.lower() == settings.global_game_viewer_email,
        "is_anonymous": anonymous,
    }


@router.post("/mfa/setup")
def setup_mfa(user: Annotated[User, Depends(get_current_user)], db: Annotated[Session, Depends(get_db)]) -> dict[str, str]:
    secret = generate_mfa_secret()
    user.mfa_secret_encrypted = encrypt_secret(secret)
    user.mfa_enabled = False
    db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="棋譜コメント研究所")
    return {"secret": secret, "provisioning_uri": uri}


@router.post("/mfa/confirm", status_code=204)
def confirm_mfa(
    payload: MfaCode,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    if not user.mfa_secret_encrypted or not verify_mfa(decrypt_secret(user.mfa_secret_encrypted), payload.code):
        raise HTTPException(status_code=422, detail="MFAコードが無効です。")
    user.mfa_enabled = True
    db.commit()
