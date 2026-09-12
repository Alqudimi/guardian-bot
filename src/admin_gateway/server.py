"""Authenticated control plane for Guardian Bot; disabled unless explicitly configured."""
from __future__ import annotations

import asyncio
import hmac
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from aiohttp import web
from sqlalchemy import func, select, text
from telegram import Bot, ChatPermissions
from telegram.error import TelegramError

from config.settings import get_settings
from src.db.models import ActionType, Group, GroupMember, ModerationEvent, User
from src.db.session import db_session
from src.layers.smart_warn import reset_warns
from src.management.group_patterns import add_group_pattern, list_group_patterns, remove_group_pattern
from src.management.group_settings import get_all_settings, set_setting, validate_setting
from src.management.reports import generate_report
from src.utils.logger import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)

_ADMIN_STATUSES = {"administrator", "creator"}
_MAX_PAGE_SIZE = 100
_MUTATING_ACTIONS = {"MUTE", "UNMUTE", "BAN", "UNBAN", "KICK", "UNDO"}
_MEMBER_ACTIONS = _MUTATING_ACTIONS | {"RESET_WARNS"}
_REDACTED_KEYS = {"token", "secret", "password", "authorization", "cookie", "api_key"}


def _request_id(request: web.Request) -> str:
    return request.headers.get("X-Request-Id", "")[:64] or f"gw-{int(time.time() * 1000)}"


def _response(
    request: web.Request,
    *,
    ok: bool,
    availability: str,
    data: Any | None = None,
    code: str | None = None,
    message: str | None = None,
    status: int = 200,
) -> web.Response:
    payload: dict[str, Any] = {
        "ok": ok,
        "requestId": _request_id(request),
        "availability": availability,
    }
    if data is not None:
        payload["data"] = data
    if not ok:
        payload["error"] = {
            "code": code or "EXECUTION_FAILED",
            "message": message or "The requested operation could not be completed.",
        }
    return web.json_response(payload, status=status)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).lower() in _REDACTED_KEYS else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _safe_int(raw: str | None, *, field: str, minimum: int = 1, maximum: int = 2**53 - 1) -> int:
    try:
        value = int(raw or "")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{field} is out of range")
    return value


def _group_id(raw: str | None) -> int:
    """Accept both legacy positive chat IDs and negative Telegram supergroup IDs."""
    return _safe_int(raw, field="groupId", minimum=-(2**53 - 1))


class AdminGateway:
    """A small aiohttp service sharing the bot lifecycle and authenticated with a bearer secret."""

    def __init__(self, bot: Bot):
        self._bot = bot
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    async def start(self) -> None:
        settings = get_settings()
        if not settings.admin_gateway_enabled:
            logger.info("admin_gateway_disabled")
            return
        app = web.Application(middlewares=[self._auth_middleware])
        app.router.add_get("/v1/status", self.status)
        app.router.add_get("/v1/ops/moderation-thresholds", self.moderation_thresholds)
        app.router.add_get("/v1/groups", self.list_groups)
        app.router.add_get("/v1/groups/{group_id}/settings", self.get_settings)
        app.router.add_patch("/v1/groups/{group_id}/settings", self.update_settings)
        app.router.add_get("/v1/groups/{group_id}/patterns", self.list_patterns)
        app.router.add_post("/v1/groups/{group_id}/patterns", self.add_pattern)
        app.router.add_delete("/v1/groups/{group_id}/patterns/{pattern_id}", self.remove_pattern)
        app.router.add_get("/v1/groups/{group_id}/report", self.group_report)
        app.router.add_get("/v1/moderation-events", self.list_events)
        app.router.add_get("/v1/groups/{group_id}/members", self.list_members)
        app.router.add_post("/v1/groups/{group_id}/members/{user_id}/actions", self.member_action)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, settings.admin_gateway_host, settings.admin_gateway_port)
        await self._site.start()
        logger.info("admin_gateway_started", host=settings.admin_gateway_host, port=settings.admin_gateway_port)

    async def stop(self) -> None:
        if self._runner is None:
            return
        await self._runner.cleanup()
        self._runner = None
        self._site = None
        logger.info("admin_gateway_stopped")

    @web.middleware
    async def _auth_middleware(self, request: web.Request, handler):
        configured = get_settings().admin_gateway_token
        header = request.headers.get("Authorization", "")
        token = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else ""
        if not configured or not token or not hmac.compare_digest(token, configured):
            return _response(
                request,
                ok=False,
                availability="UNAVAILABLE",
                code="UNAUTHENTICATED",
                message="The control gateway request was not authenticated.",
                status=401,
            )
        return await handler(request)

    async def _operator(self, request: web.Request, group_id: int, body: dict[str, Any] | None = None) -> tuple[int | None, web.Response | None]:
        raw = (body or {}).get("operatorTelegramId") or request.query.get("operatorTelegramId")
        try:
            operator_id = _safe_int(str(raw), field="operatorTelegramId")
        except ValueError:
            return None, _response(request, ok=False, availability="UNAVAILABLE", code="VALIDATION_ERROR", message="A valid operator identity is required.", status=422)
        if operator_id not in get_settings().telegram_admin_ids:
            return None, _response(request, ok=False, availability="UNAVAILABLE", code="FORBIDDEN", message="The operator is not allowlisted for Guardian Bot administration.", status=403)
        try:
            member = await self._bot.get_chat_member(group_id, operator_id)
        except TelegramError as exc:
            logger.warning("admin_gateway_operator_lookup_failed", chat_id=group_id, user_id=operator_id, error=type(exc).__name__)
            return None, _response(request, ok=False, availability="DEGRADED", code="TELEGRAM_UNAVAILABLE", message="Telegram could not verify the operator for this group.", status=503)
        if getattr(member, "status", None) not in _ADMIN_STATUSES:
            return None, _response(request, ok=False, availability="UNAVAILABLE", code="FORBIDDEN", message="The operator is not an administrator of the selected group.", status=403)
        return operator_id, None

    async def _bot_can_restrict(self, request: web.Request, group_id: int) -> web.Response | None:
        try:
            identity = await self._bot.get_me()
            membership = await self._bot.get_chat_member(group_id, identity.id)
        except TelegramError as exc:
            logger.warning("admin_gateway_bot_rights_lookup_failed", chat_id=group_id, error=type(exc).__name__)
            return _response(request, ok=False, availability="DEGRADED", code="TELEGRAM_UNAVAILABLE", message="Telegram could not verify the bot permissions.", status=503)
        if getattr(membership, "status", None) not in _ADMIN_STATUSES or not getattr(membership, "can_restrict_members", False):
            return _response(request, ok=False, availability="UNAVAILABLE", code="BOT_PERMISSION_MISSING", message="The bot lacks the required member-restriction permission.", status=403)
        return None

    async def status(self, request: web.Request) -> web.Response:
        checks: list[dict[str, Any]] = []
        started = time.perf_counter()
        try:
            await self._bot.get_me()
            checks.append({"component": "TELEGRAM", "status": "AVAILABLE", "summary": "Telegram transport responded.", "durationMs": round((time.perf_counter() - started) * 1000)})
        except TelegramError:
            checks.append({"component": "TELEGRAM", "status": "DEGRADED", "summary": "Telegram transport did not respond.", "durationMs": round((time.perf_counter() - started) * 1000)})
        started = time.perf_counter()
        try:
            redis = await get_redis()
            await redis.ping()
            checks.append({"component": "REDIS", "status": "AVAILABLE", "summary": "Redis responded to ping.", "durationMs": round((time.perf_counter() - started) * 1000)})
        except Exception as exc:
            logger.warning("admin_gateway_redis_probe_failed", error=type(exc).__name__)
            checks.append({"component": "REDIS", "status": "DEGRADED", "summary": "Redis did not respond to the gateway probe.", "durationMs": round((time.perf_counter() - started) * 1000)})
        started = time.perf_counter()
        try:
            async with db_session() as session:
                await session.execute(text("SELECT 1"))
            checks.append({"component": "POSTGRES", "status": "AVAILABLE", "summary": "Database query completed.", "durationMs": round((time.perf_counter() - started) * 1000)})
        except Exception as exc:
            logger.warning("admin_gateway_db_probe_failed", error=type(exc).__name__)
            checks.append({"component": "POSTGRES", "status": "DEGRADED", "summary": "Database query did not complete.", "durationMs": round((time.perf_counter() - started) * 1000)})
        checks.extend([
            {"component": "BOT", "status": "AVAILABLE", "summary": "Guardian Bot control gateway is serving authenticated requests.", "durationMs": None},
            {"component": "SETTINGS", "status": "AVAILABLE", "summary": "Canonical group settings manager is loaded.", "durationMs": None},
            {"component": "CELERY", "status": "DISABLED", "summary": "No worker probe is configured in the control gateway.", "durationMs": None},
            {"component": "DOCKER", "status": "DISABLED", "summary": "No Docker probe is configured in the control gateway.", "durationMs": None},
        ])
        return _response(request, ok=True, availability="AVAILABLE", data={"components": checks, "checkedAt": datetime.now(tz=UTC).isoformat()})

    async def list_groups(self, request: web.Request) -> web.Response:
        try:
            async with db_session() as session:
                rows = (await session.execute(select(Group).order_by(Group.updated_at.desc()).limit(_MAX_PAGE_SIZE))).scalars().all()
        except Exception as exc:
            logger.warning("admin_gateway_groups_query_failed", error=type(exc).__name__)
            return _response(request, ok=False, availability="DEGRADED", code="DATABASE_UNAVAILABLE", message="Groups cannot be read while the database is unavailable.", status=503)
        return _response(request, ok=True, availability="AVAILABLE", data={"groups": [{"id": row.id, "title": row.title, "username": row.username, "isActive": row.is_active, "raidLockdown": row.raid_lockdown, "slowModeActive": row.slow_mode_active, "updatedAt": _iso(row.updated_at)} for row in rows]})

    async def moderation_thresholds(self, request: web.Request) -> web.Response:
        try:
            window_seconds = _safe_int(request.query.get("windowSeconds", "900"), field="windowSeconds", maximum=86_400)
            threshold = _safe_int(request.query.get("threshold", "20"), field="threshold", maximum=500)
            cutoff = datetime.now(tz=UTC) - timedelta(seconds=window_seconds)
            async with db_session() as session:
                rows = (await session.execute(
                    select(ModerationEvent.group_id, func.count(ModerationEvent.id).label("event_count"))
                    .where(ModerationEvent.created_at >= cutoff)
                    .group_by(ModerationEvent.group_id)
                    .having(func.count(ModerationEvent.id) >= threshold)
                    .order_by(func.count(ModerationEvent.id).desc())
                    .limit(_MAX_PAGE_SIZE)
                )).all()
        except ValueError:
            return _response(request, ok=False, availability="UNAVAILABLE", code="VALIDATION_ERROR", message="The moderation threshold request is invalid.", status=422)
        except Exception as exc:
            logger.warning("admin_gateway_moderation_thresholds_failed", error=type(exc).__name__)
            return _response(request, ok=False, availability="DEGRADED", code="DATABASE_UNAVAILABLE", message="Moderation thresholds cannot be evaluated.", status=503)
        groups = [{"groupId": row.group_id, "eventCount": int(row.event_count)} for row in rows]
        return _response(request, ok=True, availability="AVAILABLE", data={"windowSeconds": window_seconds, "threshold": threshold, "groups": groups})

    async def get_settings(self, request: web.Request) -> web.Response:
        try:
            group_id = _group_id(request.match_info["group_id"])
        except ValueError as exc:
            return _response(request, ok=False, availability="UNAVAILABLE", code="VALIDATION_ERROR", message=str(exc), status=422)
        _, error = await self._operator(request, group_id)
        if error is not None:
            return error
        try:
            settings = await get_all_settings(group_id)
        except Exception as exc:
            logger.warning("admin_gateway_settings_read_failed", chat_id=group_id, error=type(exc).__name__)
            return _response(request, ok=False, availability="DEGRADED", code="REDIS_UNAVAILABLE", message="Group settings could not be read.", status=503)
        return _response(request, ok=True, availability="AVAILABLE", data={"groupId": group_id, "settings": settings})

    async def update_settings(self, request: web.Request) -> web.Response:
        try:
            group_id = _group_id(request.match_info["group_id"])
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("request body must be a JSON object")
            changes = body.get("changes")
            if not isinstance(changes, dict) or not changes or len(changes) > 23:
                raise ValueError("changes must contain one to 23 settings")
            normalized = {str(field): str(value) for field, value in changes.items()}
            for field, value in normalized.items():
                validate_setting(field, value)
        except (ValueError, TypeError):
            return _response(request, ok=False, availability="UNAVAILABLE", code="VALIDATION_ERROR", message="The settings update is invalid.", status=422)
        _, error = await self._operator(request, group_id, body)
        if error is not None:
            return error
        try:
            for field, value in normalized.items():
                await set_setting(group_id, field, value)
            settings = await get_all_settings(group_id)
        except Exception as exc:
            logger.warning("admin_gateway_settings_write_failed", chat_id=group_id, error=type(exc).__name__)
            return _response(request, ok=False, availability="DEGRADED", code="SETTINGS_WRITE_FAILED", message="Group settings were not fully updated.", status=503)
        return _response(request, ok=True, availability="AVAILABLE", data={"groupId": group_id, "settings": settings})

    async def list_events(self, request: web.Request) -> web.Response:
        try:
            limit = _safe_int(request.query.get("limit", "50"), field="limit", maximum=_MAX_PAGE_SIZE)
            group_id = _group_id(request.query["groupId"]) if "groupId" in request.query else None
            user_id = _safe_int(request.query["userId"], field="userId") if "userId" in request.query else None
            clauses = []
            if group_id is not None:
                clauses.append(ModerationEvent.group_id == group_id)
            if user_id is not None:
                clauses.append(ModerationEvent.user_id == user_id)
            async with db_session() as session:
                statement = select(ModerationEvent).order_by(ModerationEvent.created_at.desc()).limit(limit)
                if clauses:
                    statement = statement.where(*clauses)
                rows = (await session.execute(statement)).scalars().all()
        except (ValueError, KeyError):
            return _response(request, ok=False, availability="UNAVAILABLE", code="VALIDATION_ERROR", message="The event filter is invalid.", status=422)
        except Exception as exc:
            logger.warning("admin_gateway_events_query_failed", error=type(exc).__name__)
            return _response(request, ok=False, availability="DEGRADED", code="DATABASE_UNAVAILABLE", message="Moderation events cannot be read.", status=503)
        events = [{"id": row.id, "groupId": row.group_id, "userId": row.user_id, "messageId": row.message_id, "messagePreview": (row.message_text or "")[:240] or None, "violationCategory": getattr(row.violation_category, "value", str(row.violation_category)), "actionTaken": getattr(row.action_taken, "value", str(row.action_taken)), "riskScore": row.risk_score, "toxicityScore": row.toxicity_score, "nsfwScore": row.nsfw_score, "spamScore": row.spam_score, "linkRiskScore": row.link_risk_score, "behavioralRisk": row.behavioral_risk, "explanation": row.explanation, "signals": _redact(row.signals or {}), "dryRun": row.dry_run, "createdAt": _iso(row.created_at)} for row in rows]
        return _response(request, ok=True, availability="AVAILABLE", data={"events": events})

    async def list_patterns(self, request: web.Request) -> web.Response:
        try:
            group_id = _group_id(request.match_info["group_id"])
        except ValueError as exc:
            return _response(request, ok=False, availability="UNAVAILABLE", code="VALIDATION_ERROR", message=str(exc), status=422)
        _, error = await self._operator(request, group_id)
        if error is not None:
            return error
        try:
            patterns = await list_group_patterns(group_id)
        except Exception as exc:
            logger.warning("admin_gateway_patterns_read_failed", chat_id=group_id, error=type(exc).__name__)
            return _response(request, ok=False, availability="DEGRADED", code="REDIS_UNAVAILABLE", message="Group patterns could not be read.", status=503)
        return _response(request, ok=True, availability="AVAILABLE", data={"groupId": group_id, "patterns": [{"id": item.pattern_id, "type": item.pattern_type, "category": item.category, "pattern": item.pattern} for item in patterns]})

    async def add_pattern(self, request: web.Request) -> web.Response:
        try:
            group_id = _group_id(request.match_info["group_id"])
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("request body must be a JSON object")
            pattern_type = str(body.get("type", ""))
            category = str(body.get("category", ""))
            pattern = str(body.get("pattern", ""))
        except (ValueError, TypeError):
            return _response(request, ok=False, availability="UNAVAILABLE", code="VALIDATION_ERROR", message="The group pattern is invalid.", status=422)
        _, error = await self._operator(request, group_id, body)
        if error is not None:
            return error
        try:
            item = await add_group_pattern(group_id, pattern_type, category, pattern)
        except ValueError:
            return _response(request, ok=False, availability="UNAVAILABLE", code="VALIDATION_ERROR", message="The group pattern is invalid.", status=422)
        except Exception as exc:
            logger.warning("admin_gateway_pattern_add_failed", chat_id=group_id, error=type(exc).__name__)
            return _response(request, ok=False, availability="DEGRADED", code="PATTERN_WRITE_FAILED", message="The group pattern could not be saved.", status=503)
        return _response(request, ok=True, availability="AVAILABLE", data={"groupId": group_id, "pattern": {"id": item.pattern_id, "type": item.pattern_type, "category": item.category, "pattern": item.pattern}})

    async def remove_pattern(self, request: web.Request) -> web.Response:
        try:
            group_id = _group_id(request.match_info["group_id"])
            pattern_id = str(request.match_info["pattern_id"])
        except ValueError as exc:
            return _response(request, ok=False, availability="UNAVAILABLE", code="VALIDATION_ERROR", message=str(exc), status=422)
        _, error = await self._operator(request, group_id)
        if error is not None:
            return error
        try:
            removed = await remove_group_pattern(group_id, pattern_id)
        except Exception as exc:
            logger.warning("admin_gateway_pattern_remove_failed", chat_id=group_id, error=type(exc).__name__)
            return _response(request, ok=False, availability="DEGRADED", code="REDIS_UNAVAILABLE", message="The group pattern could not be removed.", status=503)
        if not removed:
            return _response(request, ok=False, availability="UNAVAILABLE", code="NOT_FOUND", message="The group pattern was not found.", status=404)
        return _response(request, ok=True, availability="AVAILABLE", data={"groupId": group_id, "patternId": pattern_id})

    async def group_report(self, request: web.Request) -> web.Response:
        try:
            group_id = _group_id(request.match_info["group_id"])
            days = _safe_int(request.query.get("days", "7"), field="days", maximum=90)
        except ValueError as exc:
            return _response(request, ok=False, availability="UNAVAILABLE", code="VALIDATION_ERROR", message=str(exc), status=422)
        _, error = await self._operator(request, group_id)
        if error is not None:
            return error
        try:
            report = await generate_report(group_id, days)
        except Exception as exc:
            logger.warning("admin_gateway_report_failed", chat_id=group_id, error=type(exc).__name__)
            return _response(request, ok=False, availability="DEGRADED", code="REPORT_UNAVAILABLE", message="The moderation report could not be generated.", status=503)
        return _response(request, ok=True, availability="AVAILABLE", data={"groupId": group_id, "days": days, "report": _redact(vars(report))})

    async def list_members(self, request: web.Request) -> web.Response:
        try:
            group_id = _group_id(request.match_info["group_id"])
            limit = _safe_int(request.query.get("limit", "50"), field="limit", maximum=_MAX_PAGE_SIZE)
        except ValueError as exc:
            return _response(request, ok=False, availability="UNAVAILABLE", code="VALIDATION_ERROR", message=str(exc), status=422)
        _, error = await self._operator(request, group_id)
        if error is not None:
            return error
        try:
            async with db_session() as session:
                rows = (await session.execute(select(GroupMember, User).join(User, GroupMember.user_id == User.id).where(GroupMember.group_id == group_id).order_by(GroupMember.updated_at.desc()).limit(limit))).all()
        except Exception as exc:
            logger.warning("admin_gateway_members_query_failed", chat_id=group_id, error=type(exc).__name__)
            return _response(request, ok=False, availability="DEGRADED", code="DATABASE_UNAVAILABLE", message="Members cannot be read.", status=503)
        members = [{"userId": member.user_id, "username": user.username, "firstName": user.first_name, "lastName": user.last_name, "trustScore": member.trust_score, "riskIndex": member.risk_index, "violationCount": member.violation_count, "warnCount": member.warn_count, "isWhitelisted": member.is_whitelisted, "isBlacklisted": member.is_blacklisted, "isMuted": member.is_muted, "muteUntil": _iso(member.mute_until), "joinedAt": _iso(member.joined_at), "updatedAt": _iso(member.updated_at)} for member, user in rows]
        return _response(request, ok=True, availability="AVAILABLE", data={"groupId": group_id, "members": members})

    async def member_action(self, request: web.Request) -> web.Response:
        try:
            group_id = _group_id(request.match_info["group_id"])
            target_user_id = _safe_int(request.match_info["user_id"], field="targetUserId")
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("request body must be a JSON object")
            action = str(body.get("action", "")).upper()
            if action not in _MEMBER_ACTIONS:
                raise ValueError("unsupported action")
            duration = body.get("durationSeconds")
            if duration is not None:
                duration = _safe_int(str(duration), field="durationSeconds", minimum=60, maximum=366 * 24 * 60 * 60)
        except (ValueError, TypeError):
            return _response(request, ok=False, availability="UNAVAILABLE", code="VALIDATION_ERROR", message="The requested member action is invalid or not exposed by the gateway.", status=422)
        _, error = await self._operator(request, group_id, body)
        if error is not None:
            return error
        if action == "RESET_WARNS":
            try:
                await reset_warns(target_user_id, group_id)
            except Exception as exc:
                logger.warning("admin_gateway_reset_warns_failed", chat_id=group_id, user_id=target_user_id, error=type(exc).__name__)
                return _response(request, ok=False, availability="DEGRADED", code="REDIS_UNAVAILABLE", message="Warning history could not be reset.", status=503)
            return _response(request, ok=True, availability="AVAILABLE", data={"action": action, "userId": target_user_id})
        rights_error = await self._bot_can_restrict(request, group_id)
        if rights_error is not None:
            return rights_error
        try:
            if action == "MUTE":
                until = datetime.now(tz=UTC) + timedelta(seconds=duration or 3600)
                await self._bot.restrict_chat_member(group_id, target_user_id, permissions=ChatPermissions(can_send_messages=False), until_date=until)
            elif action == "UNMUTE":
                await self._bot.restrict_chat_member(group_id, target_user_id, permissions=ChatPermissions(can_send_messages=True, can_send_audios=True, can_send_documents=True, can_send_photos=True, can_send_videos=True, can_send_polls=True, can_send_other_messages=True))
            elif action == "BAN":
                until = datetime.now(tz=UTC) + timedelta(seconds=duration) if duration else None
                await self._bot.ban_chat_member(group_id, target_user_id, until_date=until)
            elif action == "UNBAN":
                await self._bot.unban_chat_member(group_id, target_user_id, only_if_banned=True)
            elif action == "KICK":
                await self._bot.ban_chat_member(group_id, target_user_id)
                await asyncio.sleep(0.5)
                await self._bot.unban_chat_member(group_id, target_user_id)
            else:
                async with db_session() as session:
                    event = (await session.execute(select(ModerationEvent).where(ModerationEvent.group_id == group_id, ModerationEvent.user_id == target_user_id, ModerationEvent.action_taken.in_((ActionType.MUTE_TEMP, ActionType.BAN_TEMP, ActionType.BAN_PERM))).order_by(ModerationEvent.created_at.desc(), ModerationEvent.id.desc()).limit(1))).scalar_one_or_none()
                if event is None:
                    return _response(request, ok=False, availability="UNAVAILABLE", code="NOT_FOUND", message="No reversible moderation event exists for this user.", status=404)
                action_value = getattr(event.action_taken, "value", str(event.action_taken))
                if action_value in {ActionType.BAN_TEMP.value, ActionType.BAN_PERM.value}:
                    await self._bot.unban_chat_member(group_id, target_user_id, only_if_banned=True)
                else:
                    await self._bot.restrict_chat_member(group_id, target_user_id, permissions=ChatPermissions(can_send_messages=True, can_send_audios=True, can_send_documents=True, can_send_photos=True, can_send_videos=True, can_send_polls=True, can_send_other_messages=True))
        except TelegramError as exc:
            logger.warning("admin_gateway_member_action_failed", chat_id=group_id, user_id=target_user_id, action=action, error=type(exc).__name__)
            return _response(request, ok=False, availability="DEGRADED", code="TELEGRAM_EXECUTION_FAILED", message="Telegram did not confirm the requested member action.", status=503)
        except Exception as exc:
            logger.warning("admin_gateway_member_action_internal_failed", chat_id=group_id, user_id=target_user_id, action=action, error=type(exc).__name__)
            return _response(request, ok=False, availability="DEGRADED", code="EXECUTION_FAILED", message="The requested member action could not be completed.", status=503)
        return _response(request, ok=True, availability="AVAILABLE", data={"action": action, "userId": target_user_id})
