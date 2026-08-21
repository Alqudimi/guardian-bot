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


class MafiaGame(BaseGame):
    """Bot-native Mafia with real player actions delivered through Telegram DMs."""

    MIN_PLAYERS = 3

    def __init__(self, chat_id: int, game_id: str):
        super().__init__(chat_id, game_id)
        self.host_id: int | None = None
        self.players: dict[int, dict[str, Any]] = {}
        self.game_phase = "registration"
        self.round_count = 0
        self.votes: dict[int, int] = {}
        self.night_actions: dict[int, dict[str, Any]] = {}
        self.mafia_ids: list[int] = []
        self.doctor_id: int | None = None
        self.detective_id: int | None = None
        self.killed_id: int | None = None
        self.protected_id: int | None = None

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.status = "running"
        self.game_phase = "registration"
        user = update.effective_user
        if user is not None:
            self.host_id = user.id
            self.players[user.id] = {
                "name": user.full_name,
                "role": "unassigned",
                "is_alive": True,
            }
        keyboard = [[InlineKeyboardButton("Join game", callback_data="game:mafia:join")]]
        await update.message.reply_text(
            "🎮 *Mafia registration started*\n\n"
            "Players can join with the button. The host can start with `/mafia_start` "
            f"after at least {self.MIN_PLAYERS} players join.",
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
        if len(parts) < 3 or parts[:2] != ["game", "mafia"]:
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
            self.players[user.id] = {
                "name": user.full_name,
                "role": "unassigned",
                "is_alive": True,
            }
            await query.answer("You joined the game")
            await context.bot.send_message(
                self.chat_id,
                f"👤 {user.full_name} joined Mafia ({len(self.players)} players).",
            )
            return

        if action == "vote":
            if self.game_phase != "day" or user.id not in self._alive_ids():
                await query.answer("Voting is not available", show_alert=True)
                return
            target_id = self._parse_target(parts, 3)
            if target_id is None or target_id not in self._alive_ids() or target_id == user.id:
                await query.answer("Choose a valid living player", show_alert=True)
                return
            self.votes[user.id] = target_id
            await query.answer("Vote recorded")
            if len(self.votes) == len(self._alive_ids()):
                await self.resolve_day(context)
            return

        if action == "night":
            await self._handle_night_action(parts, user.id, query, context)
            return

        await query.answer("Unknown game action", show_alert=True)

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.message
        user = update.effective_user
        if message is None or user is None:
            return
        text = (message.text or "").strip()
        if text != "/mafia_start":
            return
        if user.id != self.host_id:
            await message.reply_text("Only the game host can start Mafia.")
            return
        if self.game_phase != "registration":
            await message.reply_text("This Mafia game has already started.")
            return
        if len(self.players) < self.MIN_PLAYERS:
            await message.reply_text(f"At least {self.MIN_PLAYERS} players are required.")
            return
        await self.begin_game(context)

    async def begin_game(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        player_ids = list(self.players)
        random.shuffle(player_ids)
        mafia_count = max(1, len(player_ids) // 4)
        role_pool = ["mafia"] * mafia_count
        if len(player_ids) >= 4:
            role_pool.append("doctor")
        if len(player_ids) >= 5:
            role_pool.append("detective")
        role_pool.extend(["villager"] * (len(player_ids) - len(role_pool)))
        random.shuffle(role_pool)

        self.mafia_ids = []
        self.doctor_id = None
        self.detective_id = None
        for player_id, role in zip(player_ids, role_pool, strict=True):
            self.players[player_id].update(role=role, is_alive=True)
            if role == "mafia":
                self.mafia_ids.append(player_id)
            elif role == "doctor":
                self.doctor_id = player_id
            elif role == "detective":
                self.detective_id = player_id

        self.round_count += 1
        self.game_phase = "night"
        self.night_actions = {}
        self.killed_id = None
        self.protected_id = None

        try:
            await context.bot.send_message(
                self.chat_id,
                "🌙 Night has started. Mafia, doctor, and detective must act through their private buttons.",
            )
            for player_id, player in self.players.items():
                await context.bot.send_message(
                    player_id,
                    f"Your Mafia role is: *{player['role']}*",
                    parse_mode="Markdown",
                )
            await self._send_night_controls(context)
        except TelegramError as exc:
            self.status = "ended"
            self.game_phase = "ended"
            await context.bot.send_message(
                self.chat_id,
                "❌ Mafia stopped because a private role message could not be delivered. "
                "Each player must open the bot in a private chat first.",
            )
            logger.warning("mafia_private_delivery_failed", error=type(exc).__name__)

    async def _send_night_controls(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        alive_targets = self._alive_ids()
        for player_id in self.mafia_ids:
            targets = [pid for pid in alive_targets if pid not in self.mafia_ids]
            await self._send_action_buttons(context, player_id, "kill", targets)
        if self.doctor_id in self._alive_ids():
            await self._send_action_buttons(context, self.doctor_id, "protect", alive_targets)
        if self.detective_id in self._alive_ids():
            targets = [pid for pid in alive_targets if pid != self.detective_id]
            await self._send_action_buttons(context, self.detective_id, "inspect", targets)

    async def _send_action_buttons(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        player_id: int | None,
        action: str,
        targets: list[int],
    ) -> None:
        if player_id is None or not targets:
            return
        keyboard = [
            [
                InlineKeyboardButton(
                    self.players[target]["name"],
                    callback_data=f"game:mafia:night:{action}:{target}:{self.chat_id}",
                )
            ]
            for target in targets
        ]
        await context.bot.send_message(
            player_id,
            f"Choose your night action: {action}",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def _handle_night_action(self, parts, user_id, query, context) -> None:
        if self.game_phase != "night" or user_id not in self._alive_ids():
            await query.answer("Night actions are not available", show_alert=True)
            return
        if len(parts) < 5:
            await query.answer("Invalid night action", show_alert=True)
            return
        action = parts[3]
        target_id = self._parse_target(parts, 4)
        role = self.players[user_id]["role"]
        allowed = {"mafia": "kill", "doctor": "protect", "detective": "inspect"}.get(role)
        if target_id is None or action != allowed or target_id not in self._alive_ids():
            await query.answer("This action is not allowed", show_alert=True)
            return
        if role == "mafia" and target_id in self.mafia_ids:
            await query.answer("Mafia cannot target mafia", show_alert=True)
            return
        if role in {"doctor", "detective"} and target_id == user_id:
            await query.answer("Choose another living player", show_alert=True)
            return
        self.night_actions[user_id] = {"action": action, "target": target_id}
        await query.answer("Night action recorded")
        required = [pid for pid in (self.mafia_ids + [self.doctor_id, self.detective_id]) if pid]
        required = [pid for pid in required if pid in self._alive_ids()]
        if all(pid in self.night_actions for pid in required):
            await self.resolve_night(context)

    async def resolve_night(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        kill_targets = [
            item["target"]
            for pid, item in self.night_actions.items()
            if pid in self.mafia_ids and item["action"] == "kill"
        ]
        if kill_targets:
            self.killed_id = Counter(kill_targets).most_common(1)[0][0]
        doctor_action = self.night_actions.get(self.doctor_id or -1)
        self.protected_id = doctor_action["target"] if doctor_action else None
        detective_action = self.night_actions.get(self.detective_id or -1)
        if detective_action and self.detective_id is not None:
            target = detective_action["target"]
            await context.bot.send_message(
                self.detective_id,
                f"Investigation: {self.players[target]['name']} is "
                f"{'Mafia' if target in self.mafia_ids else 'not Mafia'}.",
            )
        await self.begin_day(context)

    async def begin_day(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.game_phase = "day"
        self.votes = {}
        death_message = "No one died during the night."
        if self.killed_id and self.killed_id != self.protected_id:
            self.players[self.killed_id]["is_alive"] = False
            death_message = f"☀️ {self.players[self.killed_id]['name']} was killed during the night."
        await context.bot.send_message(self.chat_id, death_message)
        if await self.check_winner(context):
            return
        targets = self._alive_ids()
        keyboard = [
            [
                InlineKeyboardButton(
                    self.players[target]["name"],
                    callback_data=f"game:mafia:vote:{target}:{self.chat_id}",
                )
            ]
            for target in targets
        ]
        await context.bot.send_message(
            self.chat_id,
            "☀️ Day discussion started. Vote for a living player.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def resolve_day(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.votes:
            return
        counts = Counter(self.votes.values())
        highest = counts.most_common()
        if len(highest) > 1 and highest[0][1] == highest[1][1]:
            await context.bot.send_message(self.chat_id, "The vote was tied; nobody was eliminated.")
        else:
            lynched_id = highest[0][0]
            self.players[lynched_id]["is_alive"] = False
            await context.bot.send_message(
                self.chat_id,
                f"⚖️ {self.players[lynched_id]['name']} was eliminated."
                f" Role: {self.players[lynched_id]['role']}.",
            )
        if await self.check_winner(context):
            return
        self.game_phase = "night"
        self.night_actions = {}
        self.killed_id = None
        self.protected_id = None
        await context.bot.send_message(self.chat_id, "🌙 Night has started again.")
        await self._send_night_controls(context)

    async def check_winner(self, context: ContextTypes.DEFAULT_TYPE) -> bool:
        alive_mafia = [pid for pid in self.mafia_ids if pid in self._alive_ids()]
        alive_non_mafia = [
            pid for pid in self._alive_ids() if pid not in self.mafia_ids
        ]
        if not alive_mafia:
            await context.bot.send_message(self.chat_id, "🎉 Villagers win!")
            await self.stop()
            return True
        if len(alive_mafia) >= len(alive_non_mafia):
            await context.bot.send_message(self.chat_id, "💀 Mafia wins!")
            await self.stop()
            return True
        return False

    def _alive_ids(self) -> list[int]:
        return [pid for pid, player in self.players.items() if player.get("is_alive")]

    @staticmethod
    def _parse_target(parts: list[str], index: int) -> int | None:
        try:
            return int(parts[index])
        except (IndexError, TypeError, ValueError):
            return None

    async def stop(self) -> None:
        self.status = "ended"
        self.game_phase = "ended"
        self.night_actions = {}
        self.votes = {}

    def get_game_state(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "host_id": self.host_id,
            "players": self.players,
            "game_phase": self.game_phase,
            "round_count": self.round_count,
            "votes": self.votes,
            "night_actions": self.night_actions,
            "mafia_ids": self.mafia_ids,
            "doctor_id": self.doctor_id,
            "detective_id": self.detective_id,
            "killed_id": self.killed_id,
            "protected_id": self.protected_id,
        }

    def load_game_state(self, state: dict[str, Any]) -> None:
        self.status = state.get("status", "waiting")
        self.host_id = self._as_int(state.get("host_id"))
        self.players = {
            int(pid): data for pid, data in state.get("players", {}).items()
        }
        self.game_phase = state.get("game_phase", "registration")
        self.round_count = int(state.get("round_count", 0))
        self.votes = {int(pid): int(target) for pid, target in state.get("votes", {}).items()}
        self.night_actions = {
            int(pid): data for pid, data in state.get("night_actions", {}).items()
        }
        self.mafia_ids = [int(pid) for pid in state.get("mafia_ids", [])]
        self.doctor_id = self._as_int(state.get("doctor_id"))
        self.detective_id = self._as_int(state.get("detective_id"))
        self.killed_id = self._as_int(state.get("killed_id"))
        self.protected_id = self._as_int(state.get("protected_id"))

    @staticmethod
    def _as_int(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None
