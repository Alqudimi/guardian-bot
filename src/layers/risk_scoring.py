"""
Risk Scoring Engine
--------------------
Combines signals from all upstream layers into a single risk score (0–100).

Weights are tuned to minimize false positives while catching high-confidence
threats. Each component is capped independently, then summed with weights.

Components:
  - spam          (flood + fast rules + duplicate + entropy)
  - toxicity      (AI model output)
  - nsfw          (image classification)
  - link_risk     (URL analysis)
  - behavioral    (trust + history)
  - account_age   (new account penalty)

Final score: 0 = clean, 100 = certain threat
"""
from __future__ import annotations

from config.settings import get_settings
from src.pipeline.context import PipelineContext, RiskScore
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Component weights (must sum to 1.0)
_WEIGHTS = {
    "spam": 0.28,
    "toxicity": 0.25,
    "nsfw": 0.20,
    "link": 0.15,
    "behavioral": 0.08,
    "account_age": 0.04,
}


def _build_explanation(ctx: PipelineContext, components: dict[str, float]) -> str:
    settings = get_settings()
    parts: list[str] = []

    if ctx.spam.flood_triggered:
        parts.append(f"flood(rate={ctx.spam.flood_score:.0f})")
    if ctx.spam.burst_triggered:
        parts.append("burst")
    if ctx.spam.duplicate_detected:
        parts.append("duplicate")
    if ctx.spam.blacklist_hit:
        parts.append("blacklist")
    if ctx.spam.link_spam:
        parts.append("link_spam")
    if ctx.spam.mention_spam:
        parts.append("mention_spam")
    if ctx.spam.forwarded_spam:
        parts.append("forwarded_spam")
    if ctx.spam.coordinated_score > 0:
        parts.append(f"coordinated({ctx.spam.coordinated_score:.0f})")

    if ctx.ai.toxicity_score >= settings.toxicity_threshold:
        parts.append(
            f"toxicity={ctx.ai.toxicity_label}({ctx.ai.toxicity_score:.2f})"
        )

    if ctx.media.nsfw_detected:
        parts.append(f"nsfw({ctx.media.nsfw_score:.2f})")

    if ctx.links.phishing_detected:
        parts.append("phishing")
    if ctx.links.invite_abuse:
        parts.append("invite_abuse")
    if ctx.links.link_risk_score > 40:
        parts.append(f"link_risk({ctx.links.link_risk_score:.0f})")

    if ctx.behavior.is_new_account:
        parts.append("new_account")
    if ctx.behavior.message_rate_anomaly:
        parts.append("rate_anomaly")
    if ctx.behavior.trust_score < 30:
        parts.append(f"low_trust({ctx.behavior.trust_score:.0f})")
    if ctx.behavior.violation_count > 3:
        parts.append(f"repeat_offender({ctx.behavior.violation_count})")

    if ctx.normalized and ctx.normalized.zalgo_detected:
        parts.append("zalgo")
    if ctx.normalized and ctx.normalized.homoglyph_normalized:
        parts.append("homoglyph")

    summary = " | ".join(parts) if parts else "no_signals"
    return f"risk_score={ctx.risk.total:.1f} [{summary}]"


async def run_risk_scoring(ctx: PipelineContext) -> None:
    settings = get_settings()
    if ctx.short_circuit and ctx.spam.whitelist_hit:
        ctx.risk.total = 0.0
        return

    if ctx.short_circuit and ctx.spam.blacklist_hit:
        ctx.risk.total = 100.0
        return

    # ── Spam component ────────────────────────────────────────────────────────
    spam_raw = ctx.spam.flood_score
    if ctx.spam.duplicate_detected:
        spam_raw = min(100.0, spam_raw + 30.0)
    if ctx.spam.coordinated_score > 0:
        spam_raw = min(100.0, spam_raw + ctx.spam.coordinated_score * 0.3)
    if ctx.spam.entropy_score < 0.3:
        spam_raw = min(100.0, spam_raw + 15.0)
    spam_component = min(100.0, spam_raw)

    # ── Toxicity component ────────────────────────────────────────────────────
    toxicity_component = ctx.ai.toxicity_score * 100.0

    # ── NSFW component ────────────────────────────────────────────────────────
    nsfw_component = ctx.media.nsfw_score * 100.0
    if ctx.media.media_spam_signal:
        nsfw_component = min(100.0, nsfw_component + 30.0)

    # ── Link component ────────────────────────────────────────────────────────
    link_component = ctx.links.link_risk_score
    if ctx.links.phishing_detected:
        link_component = min(100.0, link_component + 40.0)
    if ctx.links.invite_abuse:
        link_component = min(100.0, link_component + 20.0)

    # ── Behavioral component ──────────────────────────────────────────────────
    behavioral_component = ctx.behavior.behavioral_risk

    # ── Account age component ─────────────────────────────────────────────────
    account_age_component = 0.0
    if ctx.behavior.is_new_account:
        account_age_component = 80.0
    elif ctx.behavior.account_age_days is not None and ctx.behavior.account_age_days < 30:
        account_age_component = 50.0

    # ── Weighted total ────────────────────────────────────────────────────────
    components = {
        "spam": spam_component,
        "toxicity": toxicity_component,
        "nsfw": nsfw_component,
        "link": link_component,
        "behavioral": behavioral_component,
        "account_age": account_age_component,
    }

    total = sum(_WEIGHTS[k] * v for k, v in components.items())

    # Hard boosts for definitive signals
    if ctx.links.phishing_detected and link_component > 70:
        total = max(total, 85.0)
    if ctx.media.nsfw_detected and ctx.media.nsfw_score > 0.9:
        total = max(total, 80.0)
    if ctx.ai.hate_speech and ctx.ai.toxicity_score > 0.85:
        total = max(total, 75.0)
    if ctx.spam.blacklist_hit:
        total = 100.0

    total = min(100.0, total)

    ctx.risk = RiskScore(
        total=total,
        spam_component=spam_component,
        toxicity_component=toxicity_component,
        nsfw_component=nsfw_component,
        link_component=link_component,
        behavioral_component=behavioral_component,
        account_age_component=account_age_component,
    )

    ctx.risk.explanation = _build_explanation(ctx, components)
    ctx.risk.signals_detail = {k: round(v, 2) for k, v in components.items()}

    logger.info(
        "risk_score_computed",
        user_id=ctx.user_id,
        chat_id=ctx.chat_id,
        total=round(total, 2),
        components=ctx.risk.signals_detail,
    )
