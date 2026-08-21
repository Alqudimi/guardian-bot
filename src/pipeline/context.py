"""
Pipeline execution context — carries all data through the processing layers.
Immutable inputs are set once; mutable outputs are accumulated as layers run.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from telegram import Message, Update, User


@dataclass
class NormalizedMessage:
    """Output of the normalization layer."""
    original_text: str
    clean_text: str
    fingerprint: str
    urls: list[str] = field(default_factory=list)
    has_media: bool = False
    media_type: str | None = None
    is_forwarded: bool = False
    forward_origin_id: int | None = None
    mention_count: int = 0
    has_invite_link: bool = False
    zalgo_detected: bool = False
    homoglyph_normalized: bool = False
    obfuscation_score: float = 0.0   # 0–100 composite evasion signal


@dataclass
class SpamSignals:
    flood_triggered: bool = False
    burst_triggered: bool = False
    duplicate_detected: bool = False
    mention_spam: bool = False
    link_spam: bool = False
    forwarded_spam: bool = False
    media_spam: bool = False
    repeated_chars: bool = False
    blacklist_hit: bool = False
    whitelist_hit: bool = False
    fast_rule_block: bool = False
    entropy_score: float = 1.0
    flood_score: float = 0.0
    coordinated_score: float = 0.0


@dataclass
class UserBehaviorSignals:
    trust_score: float = 50.0
    risk_index: float = 0.0
    violation_count: int = 0
    warn_count: int = 0
    is_new_account: bool = False
    account_age_days: int | None = None
    message_rate_anomaly: bool = False
    behavioral_risk: float = 0.0


@dataclass
class LinkSignals:
    risky_urls: list[str] = field(default_factory=list)
    phishing_detected: bool = False
    invite_abuse: bool = False
    redirect_chain_suspicious: bool = False
    link_risk_score: float = 0.0
    suspicious_domains: list[str] = field(default_factory=list)


@dataclass
class MediaSignals:
    nsfw_score: float = 0.0
    nsfw_detected: bool = False
    has_ocr_abuse: bool = False
    media_spam_signal: bool = False


@dataclass
class AISignals:
    toxicity_score: float = 0.0
    toxicity_label: str = "SAFE"
    toxicity_confidence: float = 0.0
    hate_speech: bool = False
    harassment: bool = False
    offensive: bool = False


@dataclass
class RiskScore:
    total: float = 0.0
    spam_component: float = 0.0
    toxicity_component: float = 0.0
    nsfw_component: float = 0.0
    link_component: float = 0.0
    behavioral_component: float = 0.0
    account_age_component: float = 0.0
    explanation: str = ""
    signals_detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class Decision:
    action: str = "allow"
    reason: str = ""
    mute_duration_seconds: int = 0
    ban_duration_seconds: int = 0
    notify_admin: bool = False
    explanation: str = ""
    warning_text: str = ""   # Custom warning message set by language_guard or other layers


@dataclass
class PipelineContext:
    """
    Central context object passed through every pipeline layer.
    Created once per incoming update and mutated in-place.
    """
    update: Update
    message: Message
    user: User
    chat_id: int
    user_id: int
    message_id: int
    pipeline_start_ts: float = field(default_factory=time.monotonic)

    # Outputs populated by layers
    normalized: NormalizedMessage | None = None
    spam: SpamSignals = field(default_factory=SpamSignals)
    behavior: UserBehaviorSignals = field(default_factory=UserBehaviorSignals)
    links: LinkSignals = field(default_factory=LinkSignals)
    media: MediaSignals = field(default_factory=MediaSignals)
    ai: AISignals = field(default_factory=AISignals)
    risk: RiskScore = field(default_factory=RiskScore)
    decision: Decision = field(default_factory=Decision)
    execution_status: str = "not_started"
    execution_error: str | None = None

    # Control flags
    short_circuit: bool = False  # set by fast rules to skip AI layers
    skip_ai: bool = False
    layer_failures: list[str] = field(default_factory=list)

    @classmethod
    def from_update(cls, update: Update) -> PipelineContext | None:
        msg = update.effective_message
        user = update.effective_user
        if not msg or not user:
            return None
        return cls(
            update=update,
            message=msg,
            user=user,
            chat_id=msg.chat_id,
            user_id=user.id,
            message_id=msg.message_id,
        )

    @property
    def elapsed_ms(self) -> float:
        return (time.monotonic() - self.pipeline_start_ts) * 1000

    def fingerprint_text(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]
