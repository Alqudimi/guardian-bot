import math
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes


class BaseGame(ABC):
    def __init__(self, chat_id: int, game_id: str):
        self.chat_id = chat_id
        self.game_id = game_id
        self.status = "waiting"  # waiting, running, ended
        self.players: dict[int, Any] = {}  # user_id -> Player object (to be defined by each game)

    @abstractmethod
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """بدء اللعبة أو التسجيل"""
        pass

    @abstractmethod
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """التعامل مع ضغطات الأزرار"""
        pass

    @abstractmethod
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """التعامل مع الرسائل النصية (للألعاب النصية)"""
        pass

    @abstractmethod
    async def stop(self):
        """إنهاء اللعبة وتنظيف الموارد"""
        pass

    def get_scores(self) -> dict[int, float]:
        """Return per-player scores that may be archived after the session ends."""
        scores: dict[int, float] = {}
        for player_id, player in self.players.items():
            if not isinstance(player, Mapping):
                continue
            try:
                score = float(player.get("score", 0))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(score) or abs(score) > 1_000_000_000:
                continue
            if score.is_integer():
                score = int(score)
            scores[int(player_id)] = score
        return scores

    @abstractmethod
    def get_game_state(self) -> dict[str, Any]:
        """الحصول على حالة اللعبة الحالية للتخزين"""
        pass

    @abstractmethod
    def load_game_state(self, state: dict[str, Any]):
        """تحميل حالة اللعبة من التخزين"""
        pass
