from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AnalysisStatus(StrEnum):
    QUEUED = "QUEUED"
    ANALYZING = "ANALYZING"
    COMMENT_REQUIRED = "COMMENT_REQUIRED"
    FAILED = "FAILED"


class RewardStatus(StrEnum):
    HELD = "HELD"
    FIXED = "FIXED"
    CANCELED = "CANCELED"


class PayoutStatus(StrEnum):
    REQUESTED = "REQUESTED"
    PAID = "PAID"
    CANCELED = "CANCELED"


class ReviewStatus(StrEnum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    google_subject: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_secret_encrypted: Mapped[str | None] = mapped_column(Text)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    event_name: Mapped[str | None] = mapped_column(String(255))
    sente_name: Mapped[str | None] = mapped_column(String(255))
    gote_name: Mapped[str | None] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(512), unique=True)
    content_type: Mapped[str | None] = mapped_column(String(100))
    file_size_bytes: Mapped[int] = mapped_column(Integer)
    source_encoding: Mapped[str] = mapped_column(String(20))
    played_at: Mapped[date] = mapped_column(Date)
    user_side: Mapped[str] = mapped_column(String(5))
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    initial_sfen: Mapped[str] = mapped_column(Text)
    usi_moves: Mapped[list[str]] = mapped_column(JSON)
    move_count: Mapped[int] = mapped_column(Integer)
    normalized_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    analysis_status: Mapped[str] = mapped_column(String(30), default=AnalysisStatus.QUEUED.value, index=True)
    analysis_error: Mapped[str | None] = mapped_column(Text)
    analysis_retry_count: Mapped[int] = mapped_column(Integer, default=0)
    analysis_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    analysis_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    critical_position_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship()
    analysis_results: Mapped[list["AnalysisResult"]] = relationship(back_populates="game", cascade="all, delete-orphan")
    critical_positions: Mapped[list["CriticalPosition"]] = relationship(back_populates="game", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_games_user_created_at", "user_id", "created_at"),)


class GameBranch(Base):
    __tablename__ = "game_branches"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(50))
    base_move_number: Mapped[int] = mapped_column(Integer)
    usi_moves: Mapped[list[str]] = mapped_column(JSON)
    japanese_moves: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("game_id", "name", name="uq_game_branch_name"),)


class ProfessionalGameFingerprint(Base):
    """投稿拒否の照合に使うプロ棋譜の最小限の識別情報。"""

    __tablename__ = "professional_game_fingerprints"
    id: Mapped[int] = mapped_column(primary_key=True)
    normalized_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    source_name: Mapped[str] = mapped_column(String(255))
    source_reference: Mapped[str | None] = mapped_column(String(512))
    event_name: Mapped[str | None] = mapped_column(String(255))
    sente_name: Mapped[str | None] = mapped_column(String(255))
    gote_name: Mapped[str | None] = mapped_column(String(255))
    played_at: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AnalysisJobOutbox(Base):
    __tablename__ = "analysis_job_outbox"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), unique=True, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    move_number: Mapped[int] = mapped_column(Integer)
    sfen_before: Mapped[str] = mapped_column(Text)
    sfen_after: Mapped[str] = mapped_column(Text)
    evaluation_raw: Mapped[int | None] = mapped_column(Integer)
    evaluation_user: Mapped[int | None] = mapped_column(Integer)
    win_rate_user: Mapped[int | None] = mapped_column(Integer)
    principal_variation: Mapped[list[str] | None] = mapped_column(JSON)
    variations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    pre_move_variations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    best_evaluation_user: Mapped[int | None] = mapped_column(Integer)
    best_mate_in_user: Mapped[int | None] = mapped_column(Integer)
    mate_in_user: Mapped[int | None] = mapped_column(Integer)
    is_mate: Mapped[bool] = mapped_column(Boolean, default=False)
    engine_name: Mapped[str] = mapped_column(String(100))
    engine_version: Mapped[str] = mapped_column(String(100))
    search_conditions: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    game: Mapped[Game] = relationship(back_populates="analysis_results")
    __table_args__ = (UniqueConstraint("game_id", "move_number", name="uq_analysis_game_move"),)


class GameSkillAnalysis(Base):
    __tablename__ = "game_skill_analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"))
    played_at: Mapped[date] = mapped_column(Date, index=True)
    estimated_rating: Mapped[int] = mapped_column(Integer)
    estimated_rank: Mapped[str] = mapped_column(String(20))
    average_eval_loss: Mapped[int] = mapped_column(Integer)
    best_move_match_rate: Mapped[int] = mapped_column(Integer)
    top3_match_rate: Mapped[int] = mapped_column(Integer)
    opening_score: Mapped[int] = mapped_column(Integer)
    middlegame_score: Mapped[int] = mapped_column(Integer)
    endgame_score: Mapped[int] = mapped_column(Integer)
    blunder_count: Mapped[int] = mapped_column(Integer, default=0)
    major_blunder_count: Mapped[int] = mapped_column(Integer, default=0)
    mate_opportunities: Mapped[int] = mapped_column(Integer, default=0)
    mate_found: Mapped[int] = mapped_column(Integer, default=0)
    mate_missed: Mapped[int] = mapped_column(Integer, default=0)
    mate_events: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    winning_positions: Mapped[int] = mapped_column(Integer, default=0)
    winning_positions_converted: Mapped[int] = mapped_column(Integer, default=0)
    winning_position_drops: Mapped[int] = mapped_column(Integer, default=0)
    recovery_count: Mapped[int] = mapped_column(Integer, default=0)
    overall_score: Mapped[int] = mapped_column(Integer)
    analyzed_move_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("game_id", name="game_skill_analyses_game_id_key"),
        Index("ix_game_skill_analyses_game_id", "game_id", unique=True),
        Index("ix_game_skill_user_played", "user_id", "played_at"),
    )


class CriticalPosition(Base):
    __tablename__ = "critical_positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    move_number: Mapped[int] = mapped_column(Integer)
    japanese_move: Mapped[str] = mapped_column(String(100))
    evaluation_before: Mapped[int] = mapped_column(Integer)
    evaluation_after: Mapped[int] = mapped_column(Integer)
    evaluation_delta: Mapped[int] = mapped_column(Integer)
    selection_reason: Mapped[str] = mapped_column(Text)
    extraction_metadata: Mapped[dict[str, Any]] = mapped_column(JSON)
    required: Mapped[bool] = mapped_column(Boolean, default=True)

    game: Mapped[Game] = relationship(back_populates="critical_positions")
    __table_args__ = (UniqueConstraint("game_id", "move_number", name="uq_critical_game_move"),)


class CommentSubmission(Base):
    __tablename__ = "comment_submissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    review_status: Mapped[str] = mapped_column(String(30), default=ReviewStatus.NOT_SUBMITTED.value, index=True)
    submitted_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    engine_explanation_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CommentAnswer(Base):
    __tablename__ = "comment_answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("comment_submissions.id", ondelete="CASCADE"), index=True)
    critical_position_id: Mapped[int] = mapped_column(ForeignKey("critical_positions.id", ondelete="CASCADE"), index=True)
    question_number: Mapped[int] = mapped_column(Integer)
    answer_text: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("submission_id", "critical_position_id", "question_number", name="uq_comment_answer_question"),)


class AiComment(Base):
    __tablename__ = "ai_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    critical_position_id: Mapped[int] = mapped_column(ForeignKey("critical_positions.id", ondelete="CASCADE"), unique=True, index=True)
    move_number: Mapped[int] = mapped_column(Integer, index=True)
    generated_text: Mapped[str] = mapped_column(Text)
    current_text: Mapped[str] = mapped_column(Text)
    source_answer_ids: Mapped[list[int]] = mapped_column(JSON)
    model_version: Mapped[str] = mapped_column(String(100))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AiCommentFeedback(Base):
    __tablename__ = "ai_comment_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    ai_comment_id: Mapped[int] = mapped_column(ForeignKey("ai_comments.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    move_number: Mapped[int] = mapped_column(Integer, index=True)
    before_text: Mapped[str] = mapped_column(Text)
    after_text: Mapped[str] = mapped_column(Text)
    diff: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("comment_submissions.id", ondelete="CASCADE"), index=True)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    from_status: Mapped[str] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(Text)
    quality_tags: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    target_type: Mapped[str] = mapped_column(String(100))
    target_id: Mapped[str] = mapped_column(String(100))
    details: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EmailVerificationToken(Base):
    __tablename__ = "email_verification_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    admin_authenticated: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AiAccessSubscription(Base):
    __tablename__ = "ai_access_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    checkout_session_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AccessCode(Base):
    __tablename__ = "access_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AccessCodeRedemption(Base):
    __tablename__ = "access_code_redemptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    access_code_id: Mapped[int] = mapped_column(ForeignKey("access_codes.id", ondelete="RESTRICT"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    redeemed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    access_code: Mapped[AccessCode] = relationship()
    user: Mapped[User] = relationship()


class BankAccount(Base):
    __tablename__ = "bank_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    encrypted_payload: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Payout(Base):
    __tablename__ = "payouts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount_yen: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default=PayoutStatus.REQUESTED.value, index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payment_reference: Mapped[str | None] = mapped_column(String(255))


class RewardLedger(Base):
    __tablename__ = "reward_ledgers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), unique=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("reviews.id"), unique=True)
    payout_id: Mapped[int | None] = mapped_column(ForeignKey("payouts.id"), index=True)
    amount_yen: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), index=True)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
