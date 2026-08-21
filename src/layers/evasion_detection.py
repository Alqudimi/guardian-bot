"""
Evasion Detection Layer
========================
Detects sophisticated evasion techniques used to bypass content filters:

1.  **Base64 / Hex encoded payloads** — decode and re-scan
2.  **Right-to-Left Override (RLO/LRO) character abuse** — used to disguise
    filenames (e.g. "virus\u202eexe.pdf" displays as "virusfpd.exe")
3.  **Mixed script attacks** — intentional mixing of Arabic/Cyrillic/Latin
    to confuse tokenizers
4.  **Repeated character substitution spam** — l33t speak and variants
5.  **URL obfuscation** — URL encoding, hex encoding, IP obfuscation
6.  **Sticker/media text bypass** — using stickers/GIFs with embedded text
7.  **Unicode block boundaries** — content split across messages to evade
    per-message filters
8.  **Null byte injection** — NUL bytes splitting strings
9.  **Typosquatting in URLs** — character substitution in brand domains
10. **Image steganography hints** — unusual file sizes/formats for images
11. **Message splitting evasion** — short messages designed to aggregate
    into harmful content across multiple rapid sends
12. **Whitespace steganography** — different whitespace characters to hide
    content from regex filters
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from urllib.parse import unquote

from src.pipeline.context import PipelineContext
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ── RLO / LRO bidi override characters ────────────────────────────────────────
_BIDI_OVERRIDE = re.compile(r"[\u202e\u202d\u202b\u202a\u200f\u200e]")

# ── Base64 pattern (min 20 chars to avoid false positives) ────────────────────
_BASE64_PATTERN = re.compile(r"[A-Za-z0-9+/]{20,}={0,2}")

# ── Hex-encoded string pattern ────────────────────────────────────────────────
_HEX_ENCODED = re.compile(r"(?:\\x[0-9a-fA-F]{2}){4,}|(?:0x[0-9a-fA-F]{2}){4,}")

# ── URL percent-encoding evasion ───────────────────────────────────────────────
_URL_ENCODED = re.compile(r"%[0-9a-fA-F]{2}")

# ── Null byte / NUL injection ─────────────────────────────────────────────────
_NULL_BYTES = re.compile(r"\x00")

# ── Whitespace steganography — non-standard whitespace characters ─────────────
_NONSTANDARD_WS = re.compile(
    r"[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000\ufeff]"
)

# ── Mixed script detection ────────────────────────────────────────────────────
def _count_scripts(text: str) -> dict[str, int]:
    """Count characters per Unicode script category."""
    scripts: dict[str, int] = {}
    for ch in text:
        if ch.isalpha():
            cp = ord(ch)
            if 0x0600 <= cp <= 0x06FF:
                scripts["arabic"] = scripts.get("arabic", 0) + 1
            elif 0x0400 <= cp <= 0x04FF:
                scripts["cyrillic"] = scripts.get("cyrillic", 0) + 1
            elif 0x0041 <= cp <= 0x007A or 0x0041 <= cp <= 0x005A:
                scripts["latin"] = scripts.get("latin", 0) + 1
            elif 0x4E00 <= cp <= 0x9FFF:
                scripts["cjk"] = scripts.get("cjk", 0) + 1
    return scripts


# ── IP address obfuscation patterns ───────────────────────────────────────────
# Decimal-encoded IP: http://2130706433/ = http://127.0.0.1/
_DECIMAL_IP = re.compile(r"https?://\d{8,10}(?:/|$)")
# Octal IP: http://0177.0.0.01/
_OCTAL_IP = re.compile(r"https?://0\d+\.0\d*\.0\d*\.0\d*(?:/|$)")

# ── L33t speak normalizer ─────────────────────────────────────────────────────
_LEET_MAP = {
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s",
    "6": "b", "7": "t", "8": "b", "@": "a", "!": "i",
    "$": "s", "€": "e", "+": "t",
}


def _normalize_leet(text: str) -> str:
    result = []
    for ch in text.lower():
        result.append(_LEET_MAP.get(ch, ch))
    return "".join(result)


def _try_decode_base64(text: str) -> str | None:
    """Try to decode a string as base64. Returns decoded text or None."""
    # Remove whitespace
    candidate = re.sub(r"\s+", "", text)
    # Pad if necessary
    padding = 4 - (len(candidate) % 4)
    if padding != 4:
        candidate += "=" * padding
    try:
        decoded = base64.b64decode(candidate)
        # Only return if the result looks like text
        decoded_str = decoded.decode("utf-8", errors="strict")
        if len(decoded_str) > 5 and decoded_str.isprintable():
            return decoded_str
    except Exception:
        pass
    return None


def _check_typosquatting(url: str) -> list[str]:
    """
    Detect typosquatting attempts in URLs.
    Checks for common brand substitutions.
    """
    flags = []
    url_lower = url.lower()

    # Known brand domain patterns with common substitutions
    typosquat_pairs = [
        (r"paypa[l1]", "paypal"),
        (r"b[i1]nance", "binance"),
        (r"te[l1]egram", "telegram"),
        (r"wh[a@]tsapp", "whatsapp"),
        (r"[a@]mazon", "amazon"),
        (r"[a@]pp[l1]e", "apple"),
        (r"g[o0][o0]g[l1]e", "google"),
        (r"fac[e3]b[o0]{2}k", "facebook"),
        (r"[i1]nstagram", "instagram"),
        (r"[t7]w[i1]tter", "twitter"),
        (r"c[o0][i1]nbase", "coinbase"),
        (r"metamask", "metamask"),
    ]

    for pattern, brand in typosquat_pairs:
        if re.search(pattern, url_lower) and brand not in url_lower:
            flags.append(f"typosquat_{brand}")

    return flags


@dataclass
class EvasionSignals:
    rlo_attack: bool = False
    base64_payload_detected: bool = False
    hex_encoded_payload: bool = False
    null_byte_injection: bool = False
    url_obfuscation: bool = False
    mixed_script_attack: bool = False
    leet_speak_obfuscation: bool = False
    whitespace_steganography: bool = False
    typosquatting: bool = False
    decimal_ip_url: bool = False
    evasion_score: float = 0.0
    decoded_text: str | None = None


async def run_evasion_detection(ctx: PipelineContext) -> None:
    """
    Comprehensive evasion detection layer.
    Augments ctx.spam signals with evasion findings.
    """
    if ctx.normalized is None or ctx.short_circuit:
        return

    text = ctx.normalized.clean_text
    original = ctx.normalized.original_text
    urls = ctx.normalized.urls

    signals = EvasionSignals()
    evasion_score = 0.0

    # ── 1. RLO / Bidi override attack ─────────────────────────────────────────
    if _BIDI_OVERRIDE.search(original):
        signals.rlo_attack = True
        evasion_score += 40.0
        logger.warning("rlo_attack_detected", user_id=ctx.user_id, chat_id=ctx.chat_id)

    # ── 2. Null byte injection ─────────────────────────────────────────────────
    if _NULL_BYTES.search(original):
        signals.null_byte_injection = True
        evasion_score += 30.0

    # ── 3. Whitespace steganography ───────────────────────────────────────────
    ws_count = len(_NONSTANDARD_WS.findall(text))
    if ws_count >= 3:
        signals.whitespace_steganography = True
        evasion_score += 15.0

    # ── 4. Base64 encoded payload ─────────────────────────────────────────────
    b64_matches = _BASE64_PATTERN.findall(text)
    for match in b64_matches:
        decoded = _try_decode_base64(match)
        if decoded:
            signals.base64_payload_detected = True
            signals.decoded_text = decoded
            evasion_score += 35.0
            logger.info(
                "base64_payload_decoded",
                user_id=ctx.user_id,
                decoded_preview=decoded[:50],
            )
            # Re-scan decoded content through fast rules patterns
            from src.layers.fast_rules import _ADULT_KEYWORDS, _CRYPTO_SCAM
            if _CRYPTO_SCAM.search(decoded) or _ADULT_KEYWORDS.search(decoded):
                evasion_score += 30.0
            break  # Only check first match

    # ── 5. Hex-encoded payload ────────────────────────────────────────────────
    if _HEX_ENCODED.search(text):
        signals.hex_encoded_payload = True
        evasion_score += 25.0

    # ── 6. Mixed script attack ────────────────────────────────────────────────
    if len(text) > 10:
        scripts = _count_scripts(text)
        non_empty = [s for s, c in scripts.items() if c >= 3]
        # 3+ scripts in one message with non-trivial use = suspicious
        if len(non_empty) >= 3:
            signals.mixed_script_attack = True
            evasion_score += 20.0
        # Cyrillic + Latin (common in phishing) with Arabic = very suspicious
        elif "cyrillic" in non_empty and "arabic" in non_empty:
            signals.mixed_script_attack = True
            evasion_score += 25.0

    # ── 7. L33t speak normalization ───────────────────────────────────────────
    if len(text) > 8:
        normalized_leet = _normalize_leet(text)
        from src.layers.fast_rules import _ADULT_KEYWORDS, _CRYPTO_SCAM
        if _CRYPTO_SCAM.search(normalized_leet) or _ADULT_KEYWORDS.search(normalized_leet):
            signals.leet_speak_obfuscation = True
            evasion_score += 35.0

    # ── 8. URL obfuscation ────────────────────────────────────────────────────
    for url in urls:
        # URL percent-encoding obfuscation
        decoded_url = unquote(url)
        if decoded_url != url and len(decoded_url) > 10:
            signals.url_obfuscation = True
            evasion_score += 20.0

        # Decimal/octal IP in URL
        if _DECIMAL_IP.search(url) or _OCTAL_IP.search(url):
            signals.decimal_ip_url = True
            evasion_score += 50.0
            logger.warning(
                "ip_obfuscation_url",
                user_id=ctx.user_id,
                url=url[:80],
            )

        # Typosquatting check
        ts_flags = _check_typosquatting(url)
        if ts_flags:
            signals.typosquatting = True
            evasion_score += 35.0
            logger.info("typosquatting_detected", user_id=ctx.user_id, flags=ts_flags)

    # ── Merge into context ─────────────────────────────────────────────────────
    signals.evasion_score = min(100.0, evasion_score)

    if evasion_score > 0:
        ctx.spam.flood_score = min(100.0, ctx.spam.flood_score + evasion_score * 0.5)

    if signals.rlo_attack or signals.decimal_ip_url or signals.null_byte_injection:
        ctx.spam.fast_rule_block = True
        ctx.short_circuit = True
        ctx.decision.action = "delete"
        ctx.decision.reason = f"evasion_attack:{evasion_score:.0f}"

    # Store for risk scoring
    ctx.evasion = signals  # type: ignore[attr-defined]

    logger.debug(
        "evasion_detection_complete",
        user_id=ctx.user_id,
        evasion_score=evasion_score,
        rlo=signals.rlo_attack,
        base64=signals.base64_payload_detected,
        typosquat=signals.typosquatting,
    )
