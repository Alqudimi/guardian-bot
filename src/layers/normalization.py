"""
Message Normalization Layer
---------------------------
Responsibilities:
- Unicode normalization (NFC)
- Remove invisible / zero-width characters
- Normalize Arabic & Latin homoglyphs
- Clean Zalgo text
- Emoji normalization (strip variation selectors)
- URL extraction and canonicalization
- Forwarded message unpacking
- Message fingerprint generation for dedup
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

from src.pipeline.context import NormalizedMessage, PipelineContext
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ── Invisible / zero-width characters ────────────────────────────────────────
_INVISIBLE_CHARS = re.compile(
    r"[\u200b\u200c\u200d\u200e\u200f\u202a-\u202e\u2060\u2061\u2062\u2063"
    r"\ufeff\u00ad\u034f\u115f\u1160\u17b4\u17b5\u3164\uffa0]",
    re.UNICODE,
)

# Variation selector range (FE00–FE0F, VS1–VS16, tags)
_VARIATION_SELECTORS = re.compile(
    r"[\ufe00-\ufe0f\U000e0100-\U000e01ef\U000e0000-\U000e007f]",
    re.UNICODE,
)

# Zalgo detection: combining marks stacking more than N per base character
_ZALGO_COMBINING = re.compile(r"[\u0300-\u036f\u0489]{3,}", re.UNICODE)

# URL pattern (broad)
_URL_PATTERN = re.compile(
    r"(?:https?://|ftp://|t\.me/|tg://|@)[^\s\u200b\"'<>()[\]{}]{4,}",
    re.IGNORECASE | re.UNICODE,
)

# Telegram invite links
_INVITE_PATTERN = re.compile(
    r"(?:https?://)?t\.me/(?:joinchat/|\+)[A-Za-z0-9_-]{10,}",
    re.IGNORECASE,
)

# Repeated characters (≥5 of the same in a row)
_REPEATED_CHARS = re.compile(r"(.)\1{4,}", re.UNICODE)

# Arabic homoglyph map — common look-alike substitutions used to evade filters
_ARABIC_HOMOGLYPHS: dict[str, str] = {
    "\u0647": "\u0647",  # ه normalized
    "\u06be": "\u0647",  # ھ → ه
    "\u06c1": "\u0647",  # ہ → ه
    "\u06c3": "\u0629",  # ۃ → ة
    "\u0643": "\u0643",  # ك normalized
    "\u06a9": "\u0643",  # ک → ك
    "\u06aa": "\u0643",  # ڪ → ك
    "\u0649": "\u0649",  # ى normalized
    "\u06cc": "\u0649",  # ی → ى
    "\u064a": "\u0649",  # ي → ى
}

# Latin confusables → ASCII (partial list for common phishing chars)
_LATIN_CONFUSABLES: dict[str, str] = {
    "\u0430": "a",  # Cyrillic а → a
    "\u0435": "e",  # Cyrillic е → e
    "\u043e": "o",  # Cyrillic о → o
    "\u0440": "r",  # Cyrillic р → r
    "\u0441": "c",  # Cyrillic с → c
    "\u0443": "u",  # Cyrillic у → u
    "\u0445": "x",  # Cyrillic х → x
    "\u0456": "i",  # Cyrillic і → i
    "\u04cf": "l",  # Cyrillic ӏ → l
    "\u1d0f": "o",  # Small capital O
    "\u2080": "0",  # Subscript 0
    "\u01a0": "O",  # Ơ → O
    "\u0d20": "t",  # Malayalam
}


def _normalize_homoglyphs(text: str) -> tuple[str, bool]:
    changed = False
    result = []
    for ch in text:
        mapped = _ARABIC_HOMOGLYPHS.get(ch) or _LATIN_CONFUSABLES.get(ch)
        if mapped and mapped != ch:
            result.append(mapped)
            changed = True
        else:
            result.append(ch)
    return "".join(result), changed


def _clean_zalgo(text: str) -> tuple[str, bool]:
    cleaned, n = _ZALGO_COMBINING.subn("", text)
    return cleaned, n > 0


def _extract_urls(text: str) -> list[str]:
    return _URL_PATTERN.findall(text)


def _canonicalize_url(url: str) -> str:
    url = url.strip().rstrip(".,;!?)")
    if not url.startswith(("http://", "https://", "ftp://", "tg://")):
        url = "https://" + url.lstrip("@")
    return url.lower()


def _compute_fingerprint(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


async def run_normalization(ctx: PipelineContext) -> None:
    """
    Runs the full normalization pipeline and populates ctx.normalized.
    """
    msg = ctx.message
    raw_text: str = msg.text or msg.caption or ""

    # 1. Unicode NFKC normalization (stricter than NFC — collapses compatibility
    #    equivalents such as fullwidth Latin, superscripts, fractions, and many
    #    homoglyph variants that NFC leaves intact)
    text = unicodedata.normalize("NFKC", raw_text)

    # 2. Strip invisible / zero-width chars
    text = _INVISIBLE_CHARS.sub("", text)

    # 3. Strip variation selectors (emoji presentation modifiers)
    text = _VARIATION_SELECTORS.sub("", text)

    # 4. Zalgo cleaning
    text, zalgo_detected = _clean_zalgo(text)

    # 5. Homoglyph normalization
    text, homoglyph_normalized = _normalize_homoglyphs(text)

    # 6. URL extraction (from cleaned text)
    raw_urls = _extract_urls(text)
    canonical_urls = [_canonicalize_url(u) for u in raw_urls]

    # 7. Invite link detection
    has_invite = bool(_INVITE_PATTERN.search(raw_text))

    # 8. Mention count
    mentions = msg.parse_entities(["mention", "text_mention"])
    mention_count = len(mentions)

    # 9. Repeated chars
    has_repeated = bool(_REPEATED_CHARS.search(text))

    # 10. Forwarded message metadata
    is_forwarded = bool(
        msg.forward_origin
        or msg.forward_from
        or msg.forward_from_chat
    )
    forward_origin_id: int | None = None
    if msg.forward_from:
        forward_origin_id = msg.forward_from.id
    elif msg.forward_from_chat:
        forward_origin_id = msg.forward_from_chat.id

    # 11. Media detection
    has_media = bool(
        msg.photo or msg.video or msg.document or msg.animation
        or msg.sticker or msg.audio or msg.voice or msg.video_note
    )
    media_type: str | None = None
    if msg.photo:
        media_type = "photo"
    elif msg.video:
        media_type = "video"
    elif msg.document:
        media_type = "document"
    elif msg.animation:
        media_type = "animation"
    elif msg.sticker:
        media_type = "sticker"

    # 12. Fingerprint only textual content. Media-only messages have no
    # meaningful content fingerprint and must be handled by media-rate rules.
    fingerprint = _compute_fingerprint(text) if text.strip() else ""

    # 13. Composite obfuscation score (0–100)
    #     Combines independent evasion signals into a single indicator used
    #     by the risk-scoring layer.
    obfuscation_score = 0.0
    if zalgo_detected:
        obfuscation_score += 35.0
    if homoglyph_normalized:
        obfuscation_score += 30.0
    # Invisible / variation chars removed → length shrank significantly
    shrink_ratio = (len(raw_text) - len(text)) / max(len(raw_text), 1)
    if shrink_ratio > 0.15:
        obfuscation_score += min(35.0, shrink_ratio * 100)
    obfuscation_score = min(100.0, obfuscation_score)

    ctx.normalized = NormalizedMessage(
        original_text=raw_text,
        clean_text=text,
        fingerprint=fingerprint,
        urls=canonical_urls,
        has_media=has_media,
        media_type=media_type,
        is_forwarded=is_forwarded,
        forward_origin_id=forward_origin_id,
        mention_count=mention_count,
        has_invite_link=has_invite,
        zalgo_detected=zalgo_detected,
        homoglyph_normalized=homoglyph_normalized,
        obfuscation_score=obfuscation_score,
    )

    # Flag repeated chars in spam signals for fast rules
    if has_repeated:
        ctx.spam.repeated_chars = True

    logger.debug(
        "normalization_complete",
        user_id=ctx.user_id,
        chat_id=ctx.chat_id,
        fingerprint=fingerprint,
        zalgo=zalgo_detected,
        homoglyph=homoglyph_normalized,
        url_count=len(canonical_urls),
        mention_count=mention_count,
    )
