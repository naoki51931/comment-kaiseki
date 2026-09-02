import os
from pathlib import Path


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


class Settings:
    database_url = os.getenv("DATABASE_URL", "sqlite:///./data/app.db")
    upload_dir = Path(os.getenv("UPLOAD_DIR", "./uploads"))
    max_kif_size_bytes = int(os.getenv("MAX_KIF_SIZE_BYTES", str(2 * 1024 * 1024)))
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    analysis_queue_enabled = env_bool("ANALYSIS_QUEUE_ENABLED")
    analysis_eager = env_bool("ANALYSIS_EAGER")
    engine_kind = os.getenv("ENGINE_KIND", "development")
    yaneuraou_path = os.getenv("YANEURAOU_PATH", "/opt/yaneuraou/YaneuraOu")
    engine_nodes = int(os.getenv("ENGINE_NODES", "10000"))
    engine_timeout_seconds = float(os.getenv("ENGINE_TIMEOUT_SECONDS", "30"))
    jwt_secret = os.getenv("JWT_SECRET", "development-only-change-me")
    login_session_hours = int(os.getenv("LOGIN_SESSION_HOURS", "5"))
    # 確認トークンはメールの所有者だけが受け取る。テストで明示的に
    # 有効化した場合を除き、APIレスポンスへは含めない。
    expose_verification_token = env_bool("EXPOSE_VERIFICATION_TOKEN", False)
    email_delivery_enabled = env_bool("EMAIL_DELIVERY_ENABLED")
    email_resend_cooldown_seconds = int(os.getenv("EMAIL_RESEND_COOLDOWN_SECONDS", "60"))
    smtp_host = os.getenv("SMTP_HOST", "mailpit")
    smtp_port = int(os.getenv("SMTP_PORT", "1025"))
    smtp_from = os.getenv("SMTP_FROM", "no-reply@kifu-comment.local")
    smtp_username = os.getenv("SMTP_USERNAME", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    smtp_starttls = env_bool("SMTP_STARTTLS")
    smtp_ssl = env_bool("SMTP_SSL")
    public_base_url = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    google_client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    storage_backend = os.getenv("STORAGE_BACKEND", "local")
    s3_bucket = os.getenv("S3_BUCKET", "")
    s3_prefix = os.getenv("S3_PREFIX", "private/kifu")
    malware_scan_enabled = env_bool("MALWARE_SCAN_ENABLED")
    clamd_host = os.getenv("CLAMD_HOST", "clamav")
    clamd_port = int(os.getenv("CLAMD_PORT", "3310"))
    encryption_key = os.getenv("ENCRYPTION_KEY", "development-encryption-key")
    bank_fingerprint_key = os.getenv("BANK_FINGERPRINT_KEY", "development-fingerprint-key")
    reward_per_game_yen = int(os.getenv("REWARD_PER_GAME_YEN", "300"))
    reward_daily_limit = int(os.getenv("REWARD_DAILY_LIMIT", "2"))
    reward_monthly_limit = int(os.getenv("REWARD_MONTHLY_LIMIT", "20"))
    minimum_payout_yen = int(os.getenv("MINIMUM_PAYOUT_YEN", "10000"))
    stripe_secret_key = os.getenv("STRIPE_SECRET_KEY", "")
    stripe_webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    ai_access_monthly_price_yen = int(os.getenv("AI_ACCESS_MONTHLY_PRICE_YEN", "1000"))
    ai_access_trial_days = int(os.getenv("AI_ACCESS_TRIAL_DAYS", "30"))
    ai_access_test_user_email = os.getenv("AI_ACCESS_TEST_USER_EMAIL", "").lower()
    weaviate_enabled = env_bool("WEAVIATE_ENABLED", True)
    weaviate_url = os.getenv("WEAVIATE_URL", "http://weaviate:8080").rstrip("/")
    weaviate_api_key = os.getenv("WEAVIATE_API_KEY", "")
    weaviate_timeout_seconds = float(os.getenv("WEAVIATE_TIMEOUT_SECONDS", "10"))


settings = Settings()
