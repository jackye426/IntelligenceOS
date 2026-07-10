"""TikTok video component models (soft-label v1)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

HookType = Literal[
    "myth_correction",
    "warning",
    "direct_question",
    "symptom_recognition",
    "unexpected_fact",
    "authority_statement",
    "personal_story",
    "list_promise",
    "outcome_promise",
    "contrarian_claim",
    "other",
]

HOOK_TYPE_VALUES: tuple[str, ...] = (
    "myth_correction",
    "warning",
    "direct_question",
    "symptom_recognition",
    "unexpected_fact",
    "authority_statement",
    "personal_story",
    "list_promise",
    "outcome_promise",
    "contrarian_claim",
    "other",
)

HookChannel = Literal["spoken", "onscreen", "both", "caption_only"]
Specificity = Literal["low", "medium", "high", "unclear"]
FunnelStage = Literal["TOFU", "MOFU", "BOFU", "unclear"]
CtaPresent = Literal["true", "false", "unclear"]  # stored as bool | use TriState
TriStateBool = bool | None

CtaPosition = Literal["open", "mid", "end", "caption", "multiple", "none"]
CtaChannel = Literal["spoken", "onscreen", "caption", "both", "none"]
CtaExplicitness = Literal["explicit", "implicit", "none", "unclear"]
CtaUrgency = Literal["none", "soft", "hard", "unclear"]


class HookComponents(BaseModel):
    text: str
    channel: HookChannel = "spoken"
    type: HookType
    type_other: str | None = None
    emotional_mechanism_raw: str | None = None
    specificity: Specificity = "unclear"
    target_audience_raw: str | None = None
    creates_curiosity: bool | None = None
    contradicts_common_belief: bool | None = None
    payoff_clear: bool | None = None
    seconds_to_main_claim: float | None = None
    window_sec_hint: float | None = None

    @field_validator("window_sec_hint", "seconds_to_main_claim", mode="before")
    @classmethod
    def _coerce_float(cls, v: Any) -> float | None:
        if v is None or v == "":
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            # allow "0.0-7.3" → take first number
            import re

            m = re.search(r"-?\d+(?:\.\d+)?", v)
            return float(m.group(0)) if m else None
        return None

    @field_validator("channel", mode="before")
    @classmethod
    def _coerce_hook_channel(cls, v: Any) -> str:
        if v in {"spoken", "onscreen", "both", "caption_only"}:
            return v
        if v == "caption":
            return "caption_only"
        return "spoken"

    @field_validator("specificity", mode="before")
    @classmethod
    def _coerce_specificity(cls, v: Any) -> str:
        if v in {"low", "medium", "high", "unclear"}:
            return v
        return "unclear"

    @model_validator(mode="after")
    def _other_requires_note(self) -> HookComponents:
        if self.type == "other" and not (self.type_other or "").strip():
            self.type_other = "unspecified"
        if self.type != "other":
            self.type_other = None
        return self


class ClaimBlock(BaseModel):
    text: str
    start_sec: float | None = None
    end_sec: float | None = None

    @field_validator("start_sec", "end_sec", mode="before")
    @classmethod
    def _coerce_sec(cls, v: Any) -> float | None:
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None


class ExplanationBlock(BaseModel):
    summary: str
    start_sec: float | None = None
    end_sec: float | None = None

    @field_validator("start_sec", "end_sec", mode="before")
    @classmethod
    def _coerce_sec(cls, v: Any) -> float | None:
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None


class CtaComponents(BaseModel):
    present: bool | Literal["unclear"] = False
    wording: str | None = None
    position: CtaPosition = "none"
    channel: CtaChannel = "none"
    explicitness: CtaExplicitness = "none"
    requested_action_raw: str | None = None
    value_exchange_raw: str | None = None
    urgency: CtaUrgency = "none"
    funnel_stage: FunnelStage | None = None

    @field_validator("present", mode="before")
    @classmethod
    def _coerce_present(cls, v: Any) -> bool | Literal["unclear"]:
        if v is True or v is False:
            return v
        if isinstance(v, str):
            low = v.strip().lower()
            if low in {"true", "yes", "1"}:
                return True
            if low in {"false", "no", "0"}:
                return False
            if low == "unclear":
                return "unclear"
        if v is None:
            return "unclear"
        return "unclear"

    @field_validator("channel", mode="before")
    @classmethod
    def _coerce_cta_channel(cls, v: Any) -> str:
        if v in {"spoken", "onscreen", "caption", "both", "none"}:
            return v
        if v in {"caption_only", "link_in_bio"}:
            return "caption"
        return "none"

    @field_validator("position", mode="before")
    @classmethod
    def _coerce_position(cls, v: Any) -> str:
        if v in {"open", "mid", "end", "caption", "multiple", "none"}:
            return v
        return "none"

    @field_validator("explicitness", mode="before")
    @classmethod
    def _coerce_explicitness(cls, v: Any) -> str:
        if v in {"explicit", "implicit", "none", "unclear"}:
            return v
        if isinstance(v, str) and v.lower() in {"high", "strong"}:
            return "explicit"
        if isinstance(v, str) and v.lower() in {"low", "weak"}:
            return "implicit"
        return "unclear"

    @field_validator("urgency", mode="before")
    @classmethod
    def _coerce_urgency(cls, v: Any) -> str:
        if v in {"none", "soft", "hard", "unclear"}:
            return v
        if isinstance(v, str) and v.lower() in {"low", "mild"}:
            return "soft"
        if isinstance(v, str) and v.lower() in {"high", "strong"}:
            return "hard"
        return "unclear"

    @field_validator("funnel_stage", mode="before")
    @classmethod
    def _coerce_funnel(cls, v: Any) -> str | None:
        if v is None or v == "":
            return None
        if v in {"TOFU", "MOFU", "BOFU", "unclear"}:
            return v
        return "unclear"


class TopicComponents(BaseModel):
    primary_raw: str | None = None
    secondary_raw: list[str] = Field(default_factory=list)

    @field_validator("secondary_raw", mode="before")
    @classmethod
    def _coerce_secondary(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x) for x in v]
        if isinstance(v, str):
            return [v] if v.strip() else []
        return []


class SpeakerComponents(BaseModel):
    primary_raw: str | None = None
    type_raw: str | None = None


class ExtractionMeta(BaseModel):
    method: str = "batch_llm_v1"
    model: str | None = None
    extracted_at: str | None = None
    confidence: float = 0.0
    needs_review: bool = False
    inputs_hash: str | None = None

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_conf(cls, v: Any) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0


class VideoComponents(BaseModel):
    video_id: str
    length_sec: int | None = None
    hook: HookComponents
    main_claim: ClaimBlock
    supporting_explanation: ExplanationBlock
    funnel_stage: FunnelStage = "unclear"
    funnel_rationale: str | None = None
    cta: CtaComponents = Field(default_factory=CtaComponents)
    topic: TopicComponents = Field(default_factory=TopicComponents)
    speaker: SpeakerComponents = Field(default_factory=SpeakerComponents)
    format_raw: str | None = None
    caption_analysis: None = None  # deferred — always null in v1
    extraction: ExtractionMeta = Field(default_factory=ExtractionMeta)

    @field_validator("caption_analysis", mode="before")
    @classmethod
    def _force_caption_null(cls, _v: Any) -> None:
        return None

    @field_validator("funnel_stage", mode="before")
    @classmethod
    def _coerce_funnel(cls, v: Any) -> str:
        if v in {"TOFU", "MOFU", "BOFU", "unclear"}:
            return v
        return "unclear"

    @field_validator("length_sec", mode="before")
    @classmethod
    def _coerce_length(cls, v: Any) -> int | None:
        if v is None or v == "":
            return None
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None
