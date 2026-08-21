# Round 14 research notes

## Official Telegram Bot API

Source: https://core.telegram.org/bots/api

- `chat_member` updates describe status changes for chat members; Telegram requires the bot to be an administrator in the chat and the update type to be explicitly enabled in `allowed_updates`.
- `getUpdates` and webhooks have update-delivery constraints; an empty `allowed_updates` list excludes `chat_member`, `message_reaction`, and `message_reaction_count` by default.
- Telegram Bot API calls are HTTPS requests and failures return an error code/description; implementation must treat API errors as real operation failures rather than success messages.
- The current official page reports Bot API 10.2 changes dated July 14, 2026. New features must be checked against the installed `python-telegram-bot` version before use.

## python-telegram-bot v22.8

Sources:

- https://docs.python-telegram-bot.org/en/v22.8/telegram.ext.chatmemberhandler.html
- https://docs.python-telegram-bot.org/en/v22.8/telegram.chatmemberadministrator.html
- https://docs.python-telegram-bot.org/en/v22.8/telegram.error.html

- `ChatMemberHandler` provides `CHAT_MEMBER`, `MY_CHAT_MEMBER`, and `ANY_CHAT_MEMBER` update categories; the project currently uses `CHAT_MEMBER` for member joins/departures.
- Administrator capability data is represented by `ChatMemberAdministrator`; sensitive commands must continue to verify actual Telegram membership status and capabilities.
- Telegram API failures are represented by the library's error types and should be caught at operation boundaries, with internal logging and safe user-facing messages.

## Design consequences for Round 14

1. Do not claim guaranteed protection against spam, bans, or group closure. The bot can only act on updates it receives and permissions Telegram grants.
2. Prefer existing pipeline layers and Redis group settings over parallel moderation implementations.
3. Any new automatic response needs a group-level enable flag, cooldown/reservation, and failure isolation.
4. Any moderation action needs explicit permission checks, execution-status/audit alignment, and tests for Telegram failure.
5. Any new game or score feature must remain bot-native, use the existing GameSessionManager, and define an actual scoring contract before persisting results.
