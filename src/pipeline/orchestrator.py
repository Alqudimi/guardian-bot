"""
Pipeline Orchestrator  (v3 — 17-layer pipeline)
================================================
Layer order:
  0.  DoS Pre-check          (memory + rate safety)
  1.  Normalization
  2.  Fast Rules              (whitelist / blacklist / instant patterns)
  3.  Flood / Spam Detection ─┐ parallel
  4.  Behavioral Analysis    ─┘
  5.  Account Intelligence
  6.  Evasion Detection
  7.  Near-Duplicate         ─┐ parallel
  8.  Link Analysis          ─┤ parallel
  9.  Media Processing       ─┤ parallel
  10. Anti-Forward           ─┘ parallel
  11. Language Guard
  12. AI Moderation
  13. Risk Scoring
  14. Decision Engine
  15. Action Execution
  16. Audit Logging + Modlog

Cross-cutting:
  - Cross-group intelligence applied at intake (pre-layer 1)
  - Adaptive thresholds injected into context
  - API Sentinel + Circuit Breaker at execution (layer 15)
  - Token Guard applied to all outbound messages
  - Modlog forwarding after every punitive action
"""
from __future__ import annotations

import asyncio

from telegram import Bot, Update

from src.intelligence.adaptive_thresholds import (
    record_group_message,
)
from src.intelligence.cross_group_intel import should_apply_cross_group_restrictions
from src.layers.account_intelligence import run_account_intelligence
from src.layers.action_execution import execute_action
from src.layers.ai_moderation import run_ai_moderation
from src.layers.anti_forward import run_anti_forward
from src.layers.audit_logging import run_audit_logging
from src.layers.behavioral_analysis import run_behavioral_analysis
from src.layers.decision_engine import run_decision_engine
from src.layers.evasion_detection import run_evasion_detection
from src.layers.fast_rules import run_fast_rules
from src.layers.flood_detection import run_flood_detection
from src.layers.language_guard import run_language_guard
from src.layers.link_analysis import run_link_analysis
from src.layers.media_processing import run_media_processing
from src.layers.near_duplicate import run_near_duplicate_detection
from src.layers.normalization import run_normalization
from src.layers.risk_scoring import run_risk_scoring
from src.management.modlog import log_moderation_event
from src.management.reports import record_action_stat, record_layer_failure
from src.management.user_info import increment_message_count
from src.pipeline.context import PipelineContext
from src.security.dos_protection import _process_rss_mb, check_message_safe, should_shed_ai
from src.utils.logger import get_logger

logger = get_logger(__name__)


async def run_pipeline(update: Update, bot: Bot) -> PipelineContext | None:
    ctx = PipelineContext.from_update(update)
    if ctx is None:
        return None

    try:
        # ── Layer 0: DoS pre-check ─────────────────────────────────────────────
        text = ctx.message.text if ctx.message else None
        safe, dos_reason = await check_message_safe(text)
        if not safe:
            logger.warning("dos_check_failed", reason=dos_reason, user_id=ctx.user_id)
            return ctx

        # ── Record message activity ────────────────────────────────────────────
        await asyncio.gather(
            _safe(record_group_message, ctx.chat_id, "activity_record"),
            _safe(increment_message_count, ctx.user_id, ctx.chat_id, "msg_count"),
        )

        # ── Cross-group threat check (pre-pipeline) ────────────────────────────
        await _cross_group_intake(ctx)
        if ctx.short_circuit:
            await _finish(ctx, bot)
            return ctx

        # ── Layer 1: Normalization ─────────────────────────────────────────────
        await _safe(run_normalization, ctx, "normalization")

        # ── Layer 2: Fast Rules ────────────────────────────────────────────────
        await _safe(run_fast_rules, ctx, "fast_rules")
        if ctx.short_circuit and ctx.spam.whitelist_hit:
            return ctx

        # ── Layers 3 & 4: Flood + Behavioral (parallel) ───────────────────────
        await asyncio.gather(
            _safe(run_flood_detection, ctx, "flood_detection"),
            _safe(run_behavioral_analysis, ctx, "behavioral_analysis"),
        )

        # ── Layer 5: Account Intelligence ─────────────────────────────────────
        await _safe(run_account_intelligence, ctx, "account_intelligence")

        # Short-circuit for blacklist / admin-impersonation
        if ctx.short_circuit and ctx.spam.fast_rule_block:
            await _finish(ctx, bot)
            return ctx

        # ── Layer 6: Evasion Detection ─────────────────────────────────────────
        await _safe(run_evasion_detection, ctx, "evasion_detection")

        # ── Layers 7–10: Near-Dup + Link + Media + Anti-Forward (parallel) ────
        await asyncio.gather(
            _safe(run_near_duplicate_detection, ctx, "near_duplicate"),
            _safe(run_link_analysis, ctx, "link_analysis"),
            _safe(run_media_processing, ctx, "media_processing"),
            _safe(run_anti_forward, ctx, "anti_forward"),
        )

        # ── Layer 11: Language Guard ───────────────────────────────────────────
        await _safe(run_language_guard, ctx, "language_guard")

        # ── Layer 12: AI Moderation ───────────────────────────────────────────
        # Skip if: definitive signal already found, OR memory pressure
        rss = _process_rss_mb()
        if (
            ctx.spam.flood_score < 85
            and not ctx.media.nsfw_detected
            and not should_shed_ai(rss)
        ):
            await _safe(run_ai_moderation, ctx, "ai_moderation")

        # ── Layers 13–16 ──────────────────────────────────────────────────────
        await _safe(run_risk_scoring, ctx, "risk_scoring")
        await _safe(run_decision_engine, ctx, "decision_engine")
        await _safe(execute_action, ctx, "action_execution", bot=bot)

        # Post-action: audit log + mod-log + report stats (parallel)
        await asyncio.gather(
            _safe(run_audit_logging, ctx, "audit_logging"),
            _safe(log_moderation_event, bot, ctx, "modlog"),
            _safe(_record_stats, ctx, "stats"),
        )

        logger.debug(
            "pipeline_v3_complete",
            user_id=ctx.user_id,
            chat_id=ctx.chat_id,
            action=ctx.decision.action,
            risk=round(ctx.risk.total, 2),
            layer_failures=ctx.layer_failures,
        )

    except Exception as exc:
        logger.error(
            "pipeline_fatal_error",
            user_id=getattr(ctx, "user_id", None),
            chat_id=getattr(ctx, "chat_id", None),
            error=str(exc),
            exc_info=True,
        )

    return ctx


async def _cross_group_intake(ctx: PipelineContext) -> None:
    try:
        should_restrict, threat_level, reason = await should_apply_cross_group_restrictions(
            ctx.user_id, ctx.chat_id
        )
        if should_restrict:
            ctx.short_circuit = True
            ctx.spam.blacklist_hit = True
            ctx.spam.fast_rule_block = True
            ctx.decision.action = "ban_perm" if int(threat_level) >= 4 else "ban_temp"
            ctx.decision.reason = f"cross_group_threat:{reason}"
            ctx.decision.notify_admin = True
            from src.management.modlog import log_critical_threat
            await _safe(
                log_critical_threat, None, ctx.chat_id, ctx.user_id, int(threat_level),
                "critical_threat_log"
            )
    except Exception as exc:
        logger.debug("cross_group_intake_error", error=str(exc))


async def _finish(ctx: PipelineContext, bot: Bot) -> None:
    await _safe(run_risk_scoring, ctx, "risk_scoring")
    await _safe(run_decision_engine, ctx, "decision_engine")
    await _safe(execute_action, ctx, "action_execution", bot=bot)
    await asyncio.gather(
        _safe(run_audit_logging, ctx, "audit_logging"),
        _safe(log_moderation_event, bot, ctx, "modlog"),
        _safe(_record_stats, ctx, "stats"),
    )


async def _record_stats(ctx: PipelineContext) -> None:
    for layer_name in ctx.layer_failures:
        await record_layer_failure(ctx.chat_id, layer_name)

    if ctx.decision and ctx.decision.action not in ("allow", "silent_log"):
        from src.layers.audit_logging import _infer_violation_category
        await record_action_stat(
            ctx.chat_id,
            ctx.decision.action,
            _infer_violation_category(ctx),
            user_id=ctx.user_id,
        )


async def _safe(fn, *args, **kwargs) -> None:
    layer_name = "unknown"
    actual_args = args

    # Last positional string arg is the layer name
    if args and isinstance(args[-1], str):
        layer_name = args[-1]
        actual_args = args[:-1]

    try:
        if kwargs:
            await fn(*actual_args, **kwargs)
        else:
            await fn(*actual_args)
    except Exception as exc:
        ctx_arg = actual_args[0] if actual_args else None
        if hasattr(ctx_arg, "layer_failures") and layer_name not in ctx_arg.layer_failures:
            ctx_arg.layer_failures.append(layer_name)
        logger.error(
            "pipeline_layer_error",
            layer=layer_name,
            user_id=getattr(ctx_arg, "user_id", None),
            chat_id=getattr(ctx_arg, "chat_id", None),
            error=str(exc),
            exc_info=True,
        )
