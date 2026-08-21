"""
SSRF Guard — Server-Side Request Forgery Protection
=====================================================
Prevents the bot from being used as an SSRF proxy by validating all
outbound URLs before making HTTP requests.

Blocked targets:
  • Private/RFC-1918 IP ranges (10.x, 172.16–31.x, 192.168.x, 127.x)
  • Link-local ranges (169.254.x.x — cloud metadata endpoints)
  • Loopback (::1, ::ffff:127.x.x.x)
  • IPv6 private ranges (fc00::/7, fe80::/10)
  • AWS/GCP/Azure metadata endpoints (169.254.169.254, metadata.google.internal)
  • localhost and common internal hostnames
  • DNS rebinding protection via async DNS pre-resolution

Also enforces:
  • Max redirect depth (5)
  • Max response size (10 MB)
  • Allowed schemes: http, https only
  • Request timeout (5s)
  • User-Agent that doesn't identify the bot
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
from urllib.parse import urljoin, urlparse

import dns.exception
import dns.resolver

from src.utils.logger import get_logger

logger = get_logger(__name__)

# ── Blocked IP networks ────────────────────────────────────────────────────────
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),   # link-local / metadata
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),    # CGNAT
    ipaddress.ip_network("198.51.100.0/24"),  # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),   # TEST-NET-3
    ipaddress.ip_network("240.0.0.0/4"),      # Reserved
    ipaddress.ip_network("255.255.255.255/32"),
]

_BLOCKED_IPV6 = [
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("::ffff:0:0/96"),    # IPv4-mapped
]

# Blocked hostnames
_BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
    "metadata.goog",
    "169.254.169.254",
    "metadata.azure.com",
    "metadata.internal",
    "instance-data",
    "computeMetadata",
}

# Blocked URL patterns (known malicious / internal)
_BLOCKED_PATTERNS = re.compile(
    r"(?:localhost|127\.|10\.|192\.168\.|172\.1[6-9]\.|172\.2[0-9]\.|172\.3[01]\.|"
    r"169\.254\.|metadata\.google|instance-data)",
    re.IGNORECASE,
)

_ALLOWED_SCHEMES = {"http", "https"}
MAX_REDIRECT_DEPTH = 5
MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MB
REQUEST_TIMEOUT_S = 5.0
SAFE_USER_AGENT = "Mozilla/5.0 (compatible; LinkChecker/1.0)"


class SSRFViolation(Exception):
    pass


def _is_ip_blocked(ip_str: str) -> bool:
    """Check if an IP address falls in a blocked network."""
    try:
        ip = ipaddress.ip_address(ip_str)
        networks = _BLOCKED_IPV6 if ip.version == 6 else _BLOCKED_NETWORKS
        return any(ip in net for net in networks)
    except ValueError:
        return True  # unparseable = blocked


def _resolve_hostname_sync(hostname: str) -> list[str]:
    resolver = dns.resolver.Resolver()
    resolver.timeout = 2.0
    resolver.lifetime = 2.0

    results: list[str] = []
    for record_type in ("A", "AAAA"):
        try:
            answers = resolver.resolve(hostname, record_type)
            results.extend(str(rdata) for rdata in answers)
        except dns.exception.DNSException:
            continue
    return results


async def _resolve_hostname(hostname: str) -> list[str]:
    """Resolve hostname off the event loop; return empty on failure."""
    try:
        return await asyncio.to_thread(_resolve_hostname_sync, hostname)
    except (OSError, dns.exception.DNSException):
        return []


async def validate_url(url: str) -> tuple[bool, str]:
    """
    Validate a URL for SSRF safety.
    Returns (safe: bool, reason: str).

    Must be called before any outbound HTTP request.
    """
    if not url:
        return False, "empty_url"

    parsed = urlparse(url)

    # Scheme check
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return False, f"blocked_scheme:{parsed.scheme}"

    hostname = parsed.hostname
    if not hostname:
        return False, "no_hostname"

    # Direct IP check
    try:
        ip = ipaddress.ip_address(hostname)
        if _is_ip_blocked(str(ip)):
            return False, f"blocked_ip:{hostname}"
        return True, ""
    except ValueError:
        pass  # It's a hostname, not a raw IP

    # Known blocked hostnames
    if hostname.lower() in _BLOCKED_HOSTNAMES:
        return False, f"blocked_hostname:{hostname}"

    # Pattern-based block
    if _BLOCKED_PATTERNS.search(url):
        return False, "blocked_pattern"

    # DNS resolution check (prevent DNS rebinding)
    resolved_ips = await _resolve_hostname(hostname)
    if not resolved_ips:
        logger.warning("ssrf_dns_unresolvable", hostname=hostname)
        return False, "dns_unresolvable"

    for ip_str in resolved_ips:
        if _is_ip_blocked(ip_str):
            logger.warning(
                "ssrf_blocked_resolved_ip",
                hostname=hostname,
                resolved_ip=ip_str,
            )
            return False, f"ssrf_resolved_to_private:{ip_str}"

    return True, ""


async def safe_fetch(url: str, timeout: float = REQUEST_TIMEOUT_S) -> tuple[bytes | None, str]:
    """
    Fetch a URL with full SSRF protection.
    Returns (content_bytes, error_message). content_bytes is None on failure.
    """
    import httpx

    safe, reason = await validate_url(url)
    if not safe:
        logger.warning("ssrf_fetch_blocked", url=url[:100], reason=reason)
        return None, reason

    try:
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=timeout,
            headers={"User-Agent": SAFE_USER_AGENT},
        ) as client:
            current_url = url
            for redirect_count in range(MAX_REDIRECT_DEPTH + 1):
                current_safe, current_reason = await validate_url(current_url)
                if not current_safe:
                    logger.warning(
                        "ssrf_redirect_blocked",
                        original_url=url[:100],
                        final_url=current_url[:100],
                        reason=current_reason,
                    )
                    return None, f"ssrf_redirect:{current_reason}"

                response = await client.get(current_url)
                if response.is_redirect or response.is_permanent_redirect:
                    location = response.headers.get("location")
                    if not location:
                        return None, "redirect_without_location"
                    if redirect_count >= MAX_REDIRECT_DEPTH:
                        return None, "max_redirect_depth"
                    current_url = urljoin(current_url, location)
                    continue

                if len(response.content) > MAX_RESPONSE_BYTES:
                    return None, "response_too_large"
                return response.content, ""

            return None, "max_redirect_depth"

    except Exception as exc:
        return None, str(exc)
