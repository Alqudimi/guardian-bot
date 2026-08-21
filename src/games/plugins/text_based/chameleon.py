from __future__ import annotations

import random
from collections import Counter
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from src.games.base import BaseGame
from src.utils.logger import get_logger

logger = get_logger(__name__)

TOPICS = {
    "Animals": ["Dog", "Cat", "Elephant", "Lion", "Giraffe", "Monkey", "Tiger", "Rabbit"],
    "Food": ["Pizza", "Burger", "Sushi", "Pasta", "Taco", "Salad", "Steak", "Soup"],
    "Countries": ["USA", "Japan", "Brazil", "France", "Egypt", "India", "China", "Canada"],
}


class ChameleonGame(BaseGame):
    """Bot-native Chameleon with private word delivery and public clue/vote rounds."""

    MIN_PLAYERS = 3

    def __init__(self, chat_id: int, game_id: str):
        super().__init__(chat_id, game_id)
        self.host_id: int | None = None
        self.players: dict[int, dict[str, Any]] = {}
        self.game_phase = "registration"
        self.current_topic: str | None = None
        self.current_word: str | None = None
        self.chameleon_id: int | None = None
        self.clues: dict[int, str] = {}
        self.votes: dict[int, int] = {}
        self.turn_order: list[int] = []
        self.current_turn_index = 0
        self.round_count = 0

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.status = "running"
        self.game_phase = "registration"
        user = update.effective_user
        if user is not None:
            self.host_id = user.id
            self.players[user.id] = {"name": user.full_name, "score": 0}
        keyboard = [[InlineKeyboardButton("Join game", callback_data="game:chameleon:join")]]
        await update.message.reply_text(
            "🦎 *Chameleon registration started*\n\n"
            f"At least {self.MIN_PLAYERS} players are required. The host starts with `/cham_start`.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )

    async def handle_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        user = update.effective_user
        if query is None or user is None:
            return
        parts = (query.data or "").split(":")
        if len(parts) < 3 or parts[:2] != ["game", "chameleon"]:
            await query.answer("Invalid game action", show_alert=True)
            return
        action = parts[2]

        if action == "join":
            if self.game_phase != "registration":
                await query.answer("Registration is closed", show_alert=True)
                return
            if user.id in self.players:
                await query.answer("You are already registered", show_alert=True)
                return
            self.players[user.id] = {"name": user.full_name, "score": 0}
            await query.answer("You joined the game")
            await context.bot.send_message(
                self.chat_id,
                f"🦎 {user.full_name} joined Chameleon ({len(self.players)} players).",
            )
            return

        if action == "select_topic":
            if self.game_phase != "topic_selection" or not self.turn_order:
                await query.answer("Topic selection is not available", show_alert=True)
                return
            if user.id != self.turn_order[0]:
                await query.answer("Only the selected player can choose", show_alert=True)
                return
            if len(parts) < 5 or parts[3] not in TOPICS:
                await query.answer("Invalid topic", show_alert=True)
                return
            self.current_topic = parts[3]
            await query.answer("Topic selected")
            await self.begin_round(context)
            return

        if action == "vote":
            if self.game_phase != "voting" or user.id not in self.players:
                await query.answer("Voting is not available", show_alert=True)
                return
            target_id = self._parse_target(parts, 3)
            if target_id is None or target_id not in self.players or target_id == user.id:
                await query.answer("Choose another player", show_alert=True)
                return
            self.votes[user.id] = target_id
            await query.answer("Vote recorded")
            if len(self.votes) == len(self.players):
                await self.resolve_voting(context)
            return

        await query.answer("Unknown game action", show_alert=True)

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.message
        user = update.effective_user
        if message is None or user is None:
            return
        text = (message.text or "").strip()
        if text == "/cham_start":
            if user.id != self.host_id:
                await message.reply_text("Only the game host can start Chameleon.")
                return
            if self.game_phase != "registration":
                await message.reply_text("This Chameleon game has already started.")
                return
            if len(self.players) < self.MIN_PLAYERS:
                await message.reply_text(f"At least {self.MIN_PLAYERS} players are required.")
                return
            await self.start_topic_selection(context)
            return

        if self.game_phase != "clue_giving":
            return
        if not self.turn_order or self.current_turn_index >= len(self.turn_order):
            return
        if user.id != self.turn_order[self.current_turn_index]:
            return
        if not text or len(text) > 120:
            await message.reply_text("Clues must contain between 1 and 120 characters.")
            return
        self.clues[user.id] = text
        self.current_turn_index += 1
        if self.current_turn_index >= len(self.turn_order):
            await self.start_voting(context)
            return
        next_player = self.players[self.turn_order[self.current_turn_index]]["name"]
        await context.bot.send_message(self.chat_id, f"Next clue: {next_player}.")

    async def start_topic_selection(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.game_phase = "topic_selection"
        self.turn_order = list(self.players)
        random.shuffle(self.turn_order)
        selector_id = self.turn_order[0]
        keyboard = [
            [InlineKeyboardButton(topic, callback_data=f"game:chameleon:select_topic:{topic}:{self.chat_id}")]
            for topic in TOPICS
        ]
        try:
            await context.bot.send_message(
                selector_id,
                "Choose the topic for this round:",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            await context.bot.send_message(
                self.chat_id,
                f"🎲 {self.players[selector_id]['name']} is choosing the topic privately.",
            )
        except TelegramError as exc:
            await self.stop()
            await context.bot.send_message(
                self.chat_id,
                "❌ Chameleon stopped because the topic selector must open the bot in private chat first.",
            )
            logger.warning("chameleon_topic_delivery_failed", error=type(exc).__name__)

    async def begin_round(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        if self.current_topic not in TOPICS:
            await self.stop()
            return
        self.game_phase = "clue_giving"
        self.round_count += 1
        self.current_word = random.choice(TOPICS[self.current_topic])
        self.chameleon_id = random.choice(self.turn_order)
        self.clues = {}
        self.votes = {}
        self.current_turn_index = 0
        try:
            await context.bot.send_message(
                self.chat_id,
                f"🦎 Topic: {self.current_topic}. Each player will submit one clue in turn.",
            )
            for player_id in self.turn_order:
                message = (
                    "You are the CHAMELEON. Blend in without knowing the word."
                    if player_id == self.chameleon_id
                    else f"The secret word is: {self.current_word}"
                )
                await context.bot.send_message(player_id, message)
            await context.bot.send_message(
                self.chat_id,
                f"First clue: {self.players[self.turn_order[0]]['name']}.",
            )
        except TelegramError as exc:
            await self.stop()
            await context.bot.send_message(
                self.chat_id,
                "❌ Chameleon stopped because every player must open the bot in private chat first.",
            )
            logger.warning("chameleon_word_delivery_failed", error=type(exc).__name__)

    async def start_voting(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.game_phase = "voting"
        self.votes = {}
        clue_summary = "\n".join(
            f"{self.players[player_id]['name']}: {clue}"
            for player_id, clue in self.clues.items()
        )
        keyboard = [
            [
                InlineKeyboardButton(
                    self.players[player_id]["name"],
                    callback_data=f"game:chameleon:vote:{player_id}:{self.chat_id}",
                )
            ]
            for player_id in self.turn_order
        ]
        await context.bot.send_message(
            self.chat_id,
            f"Clues:\n{clue_summary}\n\nWho is the Chameleon?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def resolve_voting(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.votes:
            return
        counts = Counter(self.votes.values())
        highest = counts.most_common()
        selected_id = highest[0][0]
        tied = len(highest) > 1 and highest[0][1] == highest[1][1]
        caught = not tied and selected_id == self.chameleon_id
        if caught:
            await context.bot.send_message(
                self.chat_id,
                f"✅ The group caught {self.players[self.chameleon_id]['name']}.",
            )
            for player_id in self.players:
                if player_id != self.chameleon_id:
                    self.players[player_id]["score"] += 1
        else:
            await context.bot.send_message(
                self.chat_id,
                f"❌ The Chameleon escaped: {self.players[self.chameleon_id]['name']}.",
            )
            if self.chameleon_id is not None:
                self.players[self.chameleon_id]["score"] += 2
        await self.stop()

    async def stop(self) -> None:
        self.status = "ended"
        self.game_phase = "ended"
        self.current_word = None
        self.votes = {}
        from src.games.session import GameSessionManager

        await GameSessionManager.persist_scores(self)

    def get_game_state(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "host_id": self.host_id,
            "players": self.players,
            "game_phase": self.game_phase,
            "current_topic": self.current_topic,
            "chameleon_id": self.chameleon_id,
            "clues": self.clues,
            "votes": self.votes,
            "turn_order": self.turn_order,
            "current_turn_index": self.current_turn_index,
            "round_count": self.round_count,
        }

    def load_game_state(self, state: dict[str, Any]) -> None:
        self.status = state.get("status", "waiting")
        self.host_id = self._as_int(state.get("host_id"))
        self.players = {
            int(player_id): data for player_id, data in state.get("players", {}).items()
        }
        self.game_phase = state.get("game_phase", "registration")
        self.current_topic = state.get("current_topic")
        self.chameleon_id = self._as_int(state.get("chameleon_id"))
        self.clues = {int(player_id): clue for player_id, clue in state.get("clues", {}).items()}
        self.votes = {
            int(player_id): int(target)
            for player_id, target in state.get("votes", {}).items()
        }
        self.turn_order = [int(player_id) for player_id in state.get("turn_order", [])]
        self.current_turn_index = int(state.get("current_turn_index", 0))
        self.round_count = int(state.get("round_count", 0))
        self.current_word = None

    @staticmethod
    def _parse_target(parts: list[str], index: int) -> int | None:
        try:
            return int(parts[index])
        except (IndexError, TypeError, ValueError):
            return None

    @staticmethod
    def _as_int(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None
