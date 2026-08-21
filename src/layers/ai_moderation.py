"""
AI Moderation Layer
--------------------
Arabic toxicity / hate-speech detection using:
  hossam87/bert-base-arabic-hate-speech

Outputs per message:
- toxicity_score  (0.0 – 1.0)
- toxicity_label  (SAFE | HATE | OFFENSIVE | HARASSMENT | …)
- toxicity_confidence

The model is loaded once and cached. Inference runs in a thread-pool
executor to avoid blocking the asyncio event loop.
"""
from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any

from config.settings import get_settings
from src.pipeline.context import PipelineContext
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Labels the model returns; map to our canonical labels
_LABEL_MAP = {
    "hate": "HATE",
    "hate speech": "HATE",
    "offensive": "OFFENSIVE",
    "offensive language": "OFFENSIVE",
    "harassment": "HARASSMENT",
    "normal": "SAFE",
    "not hate": "SAFE",
    "0": "SAFE",
    "1": "HATE",
}

# Minimum text length to run the model (short/empty texts are skipped)
_MIN_TEXT_LENGTH = 5

# Maximum token length before we truncate (BERT supports 512)
_MAX_INPUT_LENGTH = 512


@lru_cache(maxsize=1)
def _get_toxicity_pipeline():
    """
    Lazily load the Arabic toxicity classifier.
    Uses hossam87/bert-base-arabic-hate-speech.
    Returns None if the model cannot be loaded.
    """
    try:
        settings = get_settings()
        from transformers import pipeline as hf_pipeline
        pipe = hf_pipeline(
            "text-classification",
            model=settings.arabic_toxicity_model,
            device=settings.model_device,
            cache_dir=settings.model_cache_dir,
            truncation=True,
            max_length=_MAX_INPUT_LENGTH,
        )
        logger.info("toxicity_model_loaded", model=settings.arabic_toxicity_model)
        return pipe
    except Exception as exc:
        logger.warning("toxicity_model_unavailable", error=str(exc))
        return None


def _contains_arabic(text: str) -> bool:
    """Quick check: does text contain any Arabic-range Unicode characters?"""
    return any("\u0600" <= ch <= "\u06ff" or "\u0750" <= ch <= "\u077f" for ch in text)


def _run_inference(pipe, text: str) -> list[dict[str, Any]]:
    """Synchronous inference — runs in executor."""
    return pipe(text, return_all_scores=True)


async def run_ai_moderation(ctx: PipelineContext) -> None:
    if ctx.normalized is None or ctx.short_circuit or ctx.skip_ai:
        return

    settings = get_settings()
    text = ctx.normalized.clean_text.strip()

    # Skip very short texts
    if len(text) < _MIN_TEXT_LENGTH:
        return

    # Skip entirely if no Arabic and no suspicious signals
    # (save compute for non-Arabic-language groups)
    has_arabic = _contains_arabic(text)
    has_spam_signal = ctx.spam.flood_score > 30 or ctx.spam.fast_rule_block

    if not has_arabic and not has_spam_signal:
        return

    # Resolve effective toxicity threshold (adaptive per-group override)
    from src.intelligence.adaptive_thresholds import get_group_thresholds
    thresholds = await get_group_thresholds(ctx.chat_id)
    effective_threshold = thresholds.toxicity_threshold or settings.toxicity_threshold

    pipe = _get_toxicity_pipeline()
    if pipe is None:
        logger.debug("ai_moderation_skipped_no_model")
        return

    loop = asyncio.get_event_loop()
    try:
        results = await loop.run_in_executor(
            None, _run_inference, pipe, text[:_MAX_INPUT_LENGTH]
        )
    except Exception as exc:
        logger.warning("toxicity_inference_error", error=str(exc))
        return

    # Parse results — model returns list[list[dict]] or list[dict]
    # Flatten if nested
    if results and isinstance(results[0], list):
        results = results[0]

    toxicity_score = 0.0
    best_label = "SAFE"
    best_confidence = 0.0

    for item in results:
        label_raw = str(item.get("label", "")).lower().strip()
        score = float(item.get("score", 0.0))
        canonical = _LABEL_MAP.get(label_raw, label_raw.upper())

        if canonical != "SAFE" and score > toxicity_score:
            toxicity_score = score
            best_label = canonical
            best_confidence = score

    # If no non-safe label found, check the SAFE label confidence inversely
    if toxicity_score == 0.0:
        for item in results:
            label_raw = str(item.get("label", "")).lower().strip()
            canonical = _LABEL_MAP.get(label_raw, label_raw.upper())
            if canonical == "SAFE":
                toxicity_score = 1.0 - float(item.get("score", 1.0))
                best_confidence = 1.0 - toxicity_score

    ctx.ai.toxicity_score = toxicity_score
    ctx.ai.toxicity_label = best_label
    ctx.ai.toxicity_confidence = best_confidence
    ctx.ai.hate_speech = best_label == "HATE"
    ctx.ai.harassment = best_label == "HARASSMENT"
    ctx.ai.offensive = best_label == "OFFENSIVE"

    # Apply adaptive threshold: if score is below group-specific threshold,
    # downgrade to indicate the model didn't cross the bar for this group.
    if toxicity_score < effective_threshold:
        ctx.ai.toxicity_label = "SAFE"
        ctx.ai.hate_speech = False
        ctx.ai.harassment = False
        ctx.ai.offensive = False

    logger.info(
        "ai_moderation_result",
        user_id=ctx.user_id,
        chat_id=ctx.chat_id,
        toxicity_score=round(toxicity_score, 3),
        label=best_label,
        effective_label=ctx.ai.toxicity_label,
        threshold=round(effective_threshold, 3),
        confidence=round(best_confidence, 3),
        attack_mode=thresholds.attack_mode,
    )
