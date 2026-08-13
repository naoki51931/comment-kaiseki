from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import AnalysisStatus, ReviewStatus


class Game(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    original_filename: str
    event_name: str | None = None
    sente_name: str | None = None
    gote_name: str | None = None
    played_at: date
    user_side: str
    move_count: int | None = None
    analysis_status: AnalysisStatus
    analysis_error: str | None = None
    critical_position_count: int = 0


class CriticalPosition(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    game_id: int
    move_number: int
    japanese_move: str
    required: bool = True
    evaluation_before: int | None = None
    evaluation_after: int | None = None
    evaluation_delta: int | None = None
    selection_reason: str | None = None
    principal_variation: list[str] | None = None
    engine_explanation_visible: bool = False


class CommentAnswerInput(BaseModel):
    critical_position_id: int
    question_number: int = Field(ge=1, le=3)
    answer_text: str = Field(max_length=4000)


class CommentDraftRequest(BaseModel):
    answers: list[CommentAnswerInput]


class CommentAnswerView(CommentAnswerInput):
    model_config = ConfigDict(from_attributes=True)

    id: int


class CommentSubmissionView(BaseModel):
    id: int
    game_id: int
    review_status: ReviewStatus
    submitted_at: datetime | None
    answers: list[CommentAnswerView]


class AiCommentUpdate(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


class AiCommentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    critical_position_id: int
    move_number: int
    generated_text: str
    current_text: str
    model_version: str
    updated_at: datetime


class SearchResult(BaseModel):
    source_type: str
    source_id: int
    game_id: int
    move_number: int | None = None
    title: str
    text: str
    event_name: str | None = None
    score: float = 0
    backend: str


class SearchResponse(BaseModel):
    query: str
    backend: str
    results: list[SearchResult]


class SubmitResponse(BaseModel):
    id: int
    review_status: ReviewStatus
    submitted_at: datetime


class RewardSummary(BaseModel):
    pending_yen: int = Field(ge=0)
    fixed_yen: int = Field(ge=0)
    payout_available_yen: int = Field(ge=0)
    approved_games: int = Field(ge=0)
    minimum_payout_yen: int = 3000
