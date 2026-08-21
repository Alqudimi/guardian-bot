from __future__ import annotations

import asyncio
import json
from collections import OrderedDict
from typing import ClassVar
from uuid import uuid4

from config.settings import get_settings
from src.games.base import BaseGame
from src.games.manager import GameManager
from src.utils.logger import get_logger
from src.utils.redis_client import get_redis

logger = get_logger(__name__)

MAX_ACTIVE_SESSIONS = 100
SESSION_TTL_SECONDS = 24 * 60 * 60
GAME_SCORE_TTL_SECONDS = 365 * 24 * 60 * 60
_SESSION_LOCK_TTL_SECONDS = 10
_SESSION_LOCK_ATTEMPTS = 20
_RELEASE_LOCK_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


class GameSessionManager:
    """Manage one persistent, bot-owned game session per chat."""

    _active_sessions: ClassVar[OrderedDict[str, BaseGame]] = OrderedDict()

    @classmethod
    async def _get_redis_key(cls, chat_id: int, game_id: str) -> str:
        settings = get_settings()
        return f"{settings.redis_prefix}game_session:{chat_id}:{game_id}"

    @classmethod
    def _cache_session(cls, session_key: str, game_instance: BaseGame) -> None:
        cls._active_sessions[session_key] = game_instance
        if hasattr(cls._active_sessions, "move_to_end"):
            cls._active_sessions.move_to_end(session_key)
        while len(cls._active_sessions) > MAX_ACTIVE_SESSIONS:
            oldest_key, _ = cls._active_sessions.popitem(last=False)
            logger.info("game_session_evicted_from_memory", session_key=oldest_key)

    @classmethod
    async def _acquire_session_lock(cls, redis, chat_id: int, game_name: str) -> tuple[str, str]:
        settings = get_settings()
        lock_key = f"{settings.redis_prefix}game_session_lock:{chat_id}:{game_name}"
        token = uuid4().hex
        for _ in range(_SESSION_LOCK_ATTEMPTS):
            acquired = await redis.set(
                lock_key,
                token,
                ex=_SESSION_LOCK_TTL_SECONDS,
                nx=True,
            )
            if acquired:
                return lock_key, token
            await asyncio.sleep(0.05)
        raise RuntimeError("game session is busy")

    @staticmethod
    async def _release_session_lock(redis, lock_key: str, token: str) -> None:
        await redis.eval(_RELEASE_LOCK_SCRIPT, 1, lock_key, token)

    @classmethod
    async def _score_key(cls, chat_id: int, game_name: str) -> str:
        settings = get_settings()
        return f"{settings.redis_prefix}game_scores:{chat_id}:{game_name}"

    @classmethod
    async def _score_marker_key(cls, chat_id: int, game_name: str) -> str:
        settings = get_settings()
        return f"{settings.redis_prefix}game_scores_saved:{chat_id}:{game_name}"

    @classmethod
    async def persist_scores(cls, game_instance: BaseGame) -> bool:
        """Archive final player scores exactly once after a game ends."""
        scores = game_instance.get_scores()
        if not scores:
            return False

        redis = await get_redis()
        lock_key, lock_token = await cls._acquire_session_lock(
            redis, game_instance.chat_id, game_instance.game_id
        )
        try:
            marker_key = await cls._score_marker_key(
                game_instance.chat_id, game_instance.game_id
            )
            if await redis.exists(marker_key):
                return False

            score_key = await cls._score_key(
                game_instance.chat_id, game_instance.game_id
            )
            pipeline = redis.pipeline()
            for user_id, score in scores.items():
                pipeline.zincrby(score_key, score, str(user_id))
            pipeline.expire(score_key, GAME_SCORE_TTL_SECONDS)
            pipeline.set(
                marker_key,
                "1",
                ex=GAME_SCORE_TTL_SECONDS,
                nx=True,
            )
            results = await pipeline.execute()
            if not results[-1]:
                return False

            logger.info(
                "game_scores_persisted",
                chat_id=game_instance.chat_id,
                game_name=game_instance.game_id,
                players=len(scores),
            )
            return True
        finally:
            await cls._release_session_lock(redis, lock_key, lock_token)

    @classmethod
    async def get_scoreboard(
        cls, chat_id: int, game_name: str, limit: int = 10
    ) -> list[tuple[int, float]]:
        """Read the durable scoreboard for one group and game."""
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        redis = await get_redis()
        score_key = await cls._score_key(chat_id, game_name)
        rows = await redis.zrevrange(score_key, 0, limit - 1, withscores=True)
        return [
            (int(user_id.decode() if isinstance(user_id, bytes) else user_id), float(score))
            for user_id, score in rows
        ]

    @classmethod
    async def create_session(cls, chat_id: int, game_name: str) -> BaseGame:
        game_class = GameManager.get_game_class(game_name)
        session_key = await cls._get_redis_key(chat_id, game_name)
        redis = await get_redis()
        lock_key, lock_token = await cls._acquire_session_lock(redis, chat_id, game_name)
        try:
            existing = await cls.get_session(chat_id, game_name)
            if existing and existing.status in {"waiting", "running"}:
                raise ValueError(f"Game '{game_name}' is already active in this chat")

            game_instance = game_class(chat_id=chat_id, game_id=game_name)
            await redis.delete(await cls._score_marker_key(chat_id, game_name))
            cls._cache_session(session_key, game_instance)
            await redis.set(
                session_key,
                json.dumps(game_instance.get_game_state()),
                ex=SESSION_TTL_SECONDS,
            )
            logger.info("game_session_created", chat_id=chat_id, game_name=game_name)
            return game_instance
        finally:
            await cls._release_session_lock(redis, lock_key, lock_token)

    @classmethod
    async def get_session(cls, chat_id: int, game_name: str) -> BaseGame | None:
        session_key = await cls._get_redis_key(chat_id, game_name)
        legacy_key = f"game_session:{chat_id}:{game_name}"
        cached_key = next(
            (key for key in (session_key, legacy_key) if key in cls._active_sessions),
            None,
        )
        if cached_key is not None:
            game_instance = cls._active_sessions[cached_key]
            if hasattr(cls._active_sessions, "move_to_end"):
                cls._active_sessions.move_to_end(cached_key)
            return game_instance

        redis = await get_redis()
        stored_state = await redis.get(session_key)
        if stored_state is None and legacy_key != session_key:
            stored_state = await redis.get(legacy_key)
        if stored_state is None:
            return None

        try:
            if isinstance(stored_state, bytes):
                stored_state = stored_state.decode("utf-8")
            state = json.loads(stored_state)
            game_class = GameManager.get_game_class(game_name)
            game_instance = game_class(chat_id=chat_id, game_id=game_name)
            game_instance.load_game_state(state)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            await redis.delete(session_key)
            logger.warning(
                "game_session_discarded",
                chat_id=chat_id,
                game_name=game_name,
                error=type(exc).__name__,
            )
            return None

        cls._cache_session(session_key, game_instance)
        logger.info("game_session_loaded", chat_id=chat_id, game_name=game_name)
        return game_instance

    @classmethod
    async def update_session(cls, game_instance: BaseGame) -> None:
        session_key = await cls._get_redis_key(game_instance.chat_id, game_instance.game_id)
        cls._cache_session(session_key, game_instance)
        redis = await get_redis()
        await redis.set(
            session_key,
            json.dumps(game_instance.get_game_state()),
            ex=SESSION_TTL_SECONDS,
        )
        logger.debug(
            "game_session_updated",
            chat_id=game_instance.chat_id,
            game_id=game_instance.game_id,
            status=game_instance.status,
        )

    @classmethod
    async def delete_session(cls, chat_id: int, game_id: str) -> None:
        session_key = await cls._get_redis_key(chat_id, game_id)
        legacy_key = f"game_session:{chat_id}:{game_id}"
        cls._active_sessions.pop(session_key, None)
        cls._active_sessions.pop(legacy_key, None)
        redis = await get_redis()
        await redis.delete(session_key, legacy_key)
        logger.info("game_session_deleted", chat_id=chat_id, game_id=game_id)

    @classmethod
    async def get_active_game_for_chat(cls, chat_id: int) -> BaseGame | None:
        for game_instance in cls._active_sessions.values():
            if game_instance.chat_id == chat_id and game_instance.status == "running":
                return game_instance

        settings = get_settings()
        redis = await get_redis()
        pattern = f"{settings.redis_prefix}game_session:{chat_id}:*"
        async for raw_key in redis.scan_iter(match=pattern):
            key = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else raw_key
            game_name = key.rsplit(":", 1)[-1]
            try:
                game_instance = await cls.get_session(chat_id, game_name)
            except ValueError:
                await redis.delete(key)
                continue
            if game_instance and game_instance.status == "running":
                return game_instance
        return None
