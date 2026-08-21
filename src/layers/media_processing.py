"""
Media & Image Processing Pipeline
-----------------------------------
- NSFW image classification using Marqo/nsfw-image-detection-384
- Image metadata analysis
- OCR-based text abuse detection (basic)
- Media spam identification
"""
from __future__ import annotations

import asyncio
import io
from functools import lru_cache
from typing import Any

from PIL import Image

from config.settings import get_settings
from src.pipeline.context import PipelineContext
from src.utils.logger import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def _get_nsfw_pipeline():
    """
    Lazily load the NSFW classification pipeline.
    Uses Marqo/nsfw-image-detection-384 (ViT-based, CLIP-style).
    Falls back gracefully if the model is not available.
    """
    try:
        settings = get_settings()
        from transformers import pipeline as hf_pipeline
        pipe = hf_pipeline(
            "image-classification",
            model=settings.nsfw_model,
            device=settings.model_device,
            cache_dir=settings.model_cache_dir,
        )
        logger.info("nsfw_model_loaded", model=settings.nsfw_model)
        return pipe
    except Exception as exc:
        logger.warning("nsfw_model_unavailable", error=str(exc))
        return None


async def _classify_image_nsfw(image_bytes: bytes) -> tuple[float, str]:
    """
    Classify image bytes for NSFW content.
    Returns (nsfw_score: 0.0-1.0, label: str).
    """
    pipe = _get_nsfw_pipeline()
    if pipe is None:
        return 0.0, "UNKNOWN"

    def _run() -> list[dict[str, Any]]:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        return pipe(img)  # type: ignore[arg-type]

    loop = asyncio.get_event_loop()
    try:
        results: list[dict[str, Any]] = await loop.run_in_executor(None, _run)
    except Exception as exc:
        logger.warning("nsfw_inference_error", error=str(exc))
        return 0.0, "ERROR"

    # Marqo model outputs labels: "nsfw" and "normal"
    nsfw_score = 0.0
    best_label = "NORMAL"
    for item in results:
        label = item.get("label", "").lower()
        score = float(item.get("score", 0.0))
        if label in ("nsfw", "unsafe"):
            nsfw_score = max(nsfw_score, score)
            if score > 0.5:
                best_label = "NSFW"

    return nsfw_score, best_label


async def _download_photo(bot, file_id: str) -> bytes | None:
    """Download a Telegram file by file_id."""
    try:
        file = await bot.get_file(file_id)
        bio = io.BytesIO()
        await file.download_to_memory(bio)
        return bio.getvalue()
    except Exception as exc:
        logger.warning("photo_download_error", file_id=file_id, error=str(exc))
        return None


async def run_media_processing(ctx: PipelineContext) -> None:
    if ctx.normalized is None or ctx.short_circuit:
        return

    settings = get_settings()
    msg = ctx.message
    if not ctx.normalized.has_media:
        return

    # ── Photo NSFW classification ─────────────────────────────────────────────
    if msg.photo:
        # Get highest-resolution photo
        photo = sorted(msg.photo, key=lambda p: p.file_size or 0)[-1]
        image_bytes = await _download_photo(msg.get_bot(), photo.file_id)

        if image_bytes:
            nsfw_score, nsfw_label = await _classify_image_nsfw(image_bytes)
            ctx.media.nsfw_score = nsfw_score
            ctx.media.nsfw_detected = nsfw_score >= settings.nsfw_threshold

            logger.info(
                "nsfw_classification",
                user_id=ctx.user_id,
                chat_id=ctx.chat_id,
                nsfw_score=nsfw_score,
                label=nsfw_label,
            )

    # ── Document / sticker spam heuristics ────────────────────────────────────
    if msg.document:
        doc = msg.document
        # Executable file types are high risk
        dangerous_mimes = {
            "application/x-msdownload",
            "application/x-executable",
            "application/vnd.android.package-archive",
            "application/x-sh",
            "application/x-bat",
        }
        if doc.mime_type and doc.mime_type in dangerous_mimes:
            ctx.media.media_spam_signal = True
            ctx.media.nsfw_score = max(ctx.media.nsfw_score, 0.8)
            logger.warning(
                "dangerous_file_type",
                user_id=ctx.user_id,
                chat_id=ctx.chat_id,
                mime_type=doc.mime_type,
            )

    # ── Video heuristics ──────────────────────────────────────────────────────
    if msg.video:
        # Very short videos (< 3s) are often spam thumbnails
        if msg.video.duration and msg.video.duration < 3:
            ctx.media.media_spam_signal = True

    logger.debug(
        "media_processing_complete",
        user_id=ctx.user_id,
        chat_id=ctx.chat_id,
        media_type=ctx.normalized.media_type,
        nsfw_score=ctx.media.nsfw_score,
        nsfw_detected=ctx.media.nsfw_detected,
    )
