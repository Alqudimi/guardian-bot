"""
Link & URL Security Analysis Layer
-----------------------------------
- URL expansion and redirect chain tracing
- Domain reputation evaluation (DB cache + heuristics)
- Phishing detection heuristics
- Telegram invite abuse detection
- Suspicious domain pattern recognition
- External threat intelligence (optional, async)
"""
from __future__ import annotations

import asyncio
import re
from urllib.parse import urljoin, urlparse

import httpx
import tldextract
from sqlalchemy import select

from config.settings import get_settings
from src.db.models import DomainReputation
from src.db.session import db_session
from src.pipeline.context import PipelineContext
from src.security.ssrf_guard import validate_url
from src.utils.logger import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)

# ── Suspicious TLDs (high-abuse registrars) ────────────────────────────────────
_SUSPICIOUS_TLDS = {
    "tk", "ml", "ga", "cf", "gq",  # Freenom
    "xyz", "top", "club", "online", "site", "info",
    "win", "bid", "date", "racing", "stream",
}

# ── Known phishing brands to spoof ────────────────────────────────────────────
_BRAND_KEYWORDS = re.compile(
    r"(?:paypal|binance|coinbase|metamask|telegram|whatsapp|facebook|instagram|"
    r"twitter|tiktok|amazon|apple|google|microsoft|bankofamerica|chase|wellsfargo|"
    r"crypto|wallet|blockchain|defi|nft|airdrop)",
    re.IGNORECASE,
)

# Suspicious path patterns in URLs
_SUSPICIOUS_PATHS = re.compile(
    r"(?:/login|/signin|/verify|/confirm|/secure|/account|/wallet|/recover|/reset|"
    r"/admin|/panel|/gift|/free|/claim|/bonus)",
    re.IGNORECASE,
)

# ── URL shorteners that hide the final destination ─────────────────────────────
_SHORTENERS = {
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly",
    "buff.ly", "rebrand.ly", "short.link", "tiny.cc", "is.gd",
    "cutt.ly", "rb.gy", "shorturl.at",
}


def _parse_domain(url: str) -> str | None:
    try:
        extracted = tldextract.extract(url)
        if extracted.domain and extracted.suffix:
            return f"{extracted.domain}.{extracted.suffix}".lower()
    except Exception:
        pass
    return None


def _is_suspicious_domain(domain: str) -> bool:
    extracted = tldextract.extract(domain)
    tld = extracted.suffix.lower() if extracted.suffix else ""
    if tld in _SUSPICIOUS_TLDS:
        return True
    if _BRAND_KEYWORDS.search(domain):
        return True
    return False


def _is_shortener(domain: str) -> bool:
    return domain.lower() in _SHORTENERS


async def _get_domain_reputation_cached(domain: str) -> float:
    settings = get_settings()
    redis = await get_redis()
    cache_key = f"{settings.redis_prefix}domrep:{domain}"
    cached = await redis.get(cache_key)
    if cached is not None:
        return float(cached)

    risk = 0.0
    try:
        async with db_session() as session:
            result = await session.execute(
                select(DomainReputation).where(DomainReputation.domain == domain)
            )
            rep = result.scalar_one_or_none()
            if rep:
                risk = rep.risk_score
    except Exception as exc:
        logger.debug("domain_rep_db_error", domain=domain, error=str(exc))

    # Cache for 30 minutes
    await redis.setex(cache_key, 1800, str(risk))
    return risk


async def _expand_url(url: str, timeout: float = 3.0) -> str | None:
    """Follow redirects only after validating the source and final destination."""
    safe, reason = await validate_url(url)
    if not safe:
        logger.warning("link_expansion_blocked", url=url[:200], reason=reason)
        return None

    try:
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0"},
        ) as client:
            current_url = url
            for redirect_count in range(6):
                current_safe, current_reason = await validate_url(current_url)
                if not current_safe:
                    logger.warning(
                        "link_redirect_blocked",
                        original_url=url[:200],
                        final_url=current_url[:200],
                        reason=current_reason,
                    )
                    return None
                response = await client.head(current_url)
                if response.is_redirect or response.is_permanent_redirect:
                    location = response.headers.get("location")
                    if not location or redirect_count == 5:
                        return None
                    current_url = urljoin(current_url, location)
                    continue
                return current_url
            return None
    except (httpx.HTTPError, ValueError):
        return None


async def _check_single_url(url: str) -> tuple[float, list[str]]:
    """
    Returns (risk_score 0-100, list[flag_strings]) for a single URL.
    """
    flags: list[str] = []
    risk = 0.0

    domain = _parse_domain(url)
    if not domain:
        return 10.0, ["unparseable_domain"]

    # Shortener — expand
    final_url = url
    if _is_shortener(domain):
        flags.append("url_shortener")
        risk += 15.0
        expanded = await _expand_url(url)
        if expanded:
            final_url = expanded
            expanded_domain = _parse_domain(expanded)
            if expanded_domain:
                domain = expanded_domain

    parsed = urlparse(final_url)

    # Suspicious TLD / brand impersonation
    if _is_suspicious_domain(domain):
        flags.append("suspicious_domain")
        risk += 30.0

    if _BRAND_KEYWORDS.search(domain):
        flags.append("brand_impersonation")
        risk += 35.0

    if _SUSPICIOUS_PATHS.search(parsed.path):
        flags.append("suspicious_path")
        risk += 20.0

    # IP address instead of domain
    if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", domain):
        flags.append("ip_address_url")
        risk += 25.0

    # HTTP (not HTTPS) for credential-looking domains
    if parsed.scheme == "http" and _BRAND_KEYWORDS.search(domain):
        flags.append("http_credential_domain")
        risk += 20.0

    # DB reputation
    db_risk = await _get_domain_reputation_cached(domain)
    risk += db_risk * 40.0  # scale 0-1 → 0-40

    return min(100.0, risk), flags


async def run_link_analysis(ctx: PipelineContext) -> None:
    if ctx.normalized is None or ctx.short_circuit:
        return

    urls = ctx.normalized.urls
    if not urls:
        return

    # Telegram invite link abuse
    if ctx.normalized.has_invite_link:
        # Allow invites only from admins (checked later in decision engine)
        ctx.links.invite_abuse = True
        ctx.links.link_risk_score = max(ctx.links.link_risk_score, 40.0)

    # Analyze all URLs concurrently
    tasks = [_check_single_url(url) for url in urls[:10]]  # cap at 10
    results = await asyncio.gather(*tasks, return_exceptions=True)

    max_risk = 0.0
    risky_urls: list[str] = []
    suspicious_domains: list[str] = []

    for url, result in zip(urls[:10], results, strict=True):
        if isinstance(result, Exception):
            continue
        risk_score, flags = result
        if risk_score > 40:
            risky_urls.append(url)
        if "suspicious_domain" in flags or "brand_impersonation" in flags:
            d = _parse_domain(url)
            if d:
                suspicious_domains.append(d)
        if "brand_impersonation" in flags and risk_score > 60:
            ctx.links.phishing_detected = True
        max_risk = max(max_risk, risk_score)

    ctx.links.risky_urls = risky_urls
    ctx.links.suspicious_domains = suspicious_domains
    ctx.links.link_risk_score = max_risk

    if max_risk > 70:
        ctx.links.phishing_detected = True

    logger.debug(
        "link_analysis_complete",
        user_id=ctx.user_id,
        chat_id=ctx.chat_id,
        url_count=len(urls),
        max_risk=max_risk,
        phishing=ctx.links.phishing_detected,
        risky_count=len(risky_urls),
    )
