"""Data models for RecallFabric evaluation framework."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Turn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: str = "user"
    content: str
    fact_id: str | None = None
    fact_content: str | None = None
    is_distractor: bool = False
    is_update: bool = False
    supersedes_fact_id: str | None = None


class Session(BaseModel):
    model_config = ConfigDict(extra="ignore")

    session_id: str
    turns: list[Turn] = Field(default_factory=list)


class Question(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question_id: str
    question: str
    expected_memory_ids: list[str] = Field(default_factory=list)
    expected_answer: str
    acceptable_answers: list[str] = Field(default_factory=list)
    contradicted_answers: list[str] = Field(default_factory=list)
    is_conflict_test: bool = False
    latest_fact: str | None = None
    superseded_fact: str | None = None


class Conversation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    conversation_id: str
    user_id: str
    sessions: list[Session] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)


class IngestResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: str
    message: str
    memories_stored: int = 0
    latency_ms: float = 0.0
    is_distractor: bool = False
    is_update: bool = False
    fact_id: str | None = None


class AnswerResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: str
    question_id: str
    question: str
    reply: str
    retrieved_memory_ids: list[str] = Field(default_factory=list)
    retrieved_contents: list[str] = Field(default_factory=list)
    latency_ms: float = 0.0


class QuestionEvaluation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question_id: str
    question: str
    system: str
    reply: str
    expected_answer: str
    retrieved_memory_ids: list[str] = Field(default_factory=list)
    expected_memory_ids: list[str] = Field(default_factory=list)
    precision_at_k: dict[int, float] = Field(default_factory=dict)
    recall_at_k: dict[int, float] = Field(default_factory=dict)
    exact_match: float = 0.0
    fuzzy_match: float = 0.0
    llm_judge_score: float | None = None
    is_hallucination: bool = False
    conflict_resolved_correctly: bool | None = None
    answer_latency_ms: float = 0.0


class SystemMetrics(BaseModel):
    model_config = ConfigDict(extra="ignore")

    system_name: str
    total_conversations: int = 0
    total_questions: int = 0
    precision_at_k: dict[str, float] = Field(default_factory=dict)
    recall_at_k: dict[str, float] = Field(default_factory=dict)
    exact_match: float = 0.0
    fuzzy_match: float = 0.0
    llm_judge: float | None = None
    hallucination_rate: float = 0.0
    conflict_accuracy: float = 0.0
    ingest_p50_ms: float = 0.0
    ingest_p95_ms: float = 0.0
    answer_p50_ms: float = 0.0
    answer_p95_ms: float = 0.0
    avg_memories_per_conv: float = 0.0
    duplicate_rate: float = 0.0
    distractor_rejection_rate: float = 0.0


class EvaluationReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    timestamp: str
    config: dict[str, Any] = Field(default_factory=dict)
    dataset_summary: dict[str, Any] = Field(default_factory=dict)
    systems: dict[str, SystemMetrics] = Field(default_factory=dict)
    cross_model_consistency: dict[str, Any] | None = None
