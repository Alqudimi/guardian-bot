# Round 13 research notes

## Official sources

1. Telegram Bot API: https://core.telegram.org/bots/api
   The current official API reference documents callback queries, update delivery, group chat member updates, explicit administrator requirements for some update types, and current Bot API changes. The project must continue validating callback context locally and must not assume that a callback can identify a group independently of the message/update context.

2. python-telegram-bot JobQueue v22.5: https://docs.python-telegram-bot.org/en/v22.5/telegram.ext.jobqueue.html
   JobQueue is an asynchronous convenience wrapper over APScheduler. Long-lived scheduled work needs explicit ownership and lifecycle handling in the application rather than untracked fire-and-forget tasks.

3. python-telegram-bot ChatPermissions v22.5: https://docs.python-telegram-bot.org/en/v22.5/telegram.chatpermissions.html
   Chat permission mutations are represented by explicit Telegram permission fields. The bot must still have the relevant administrator rights in the target chat; local policy cannot make an unsupported Telegram mutation valid.

## Round 13 decisions

The first verified gaps were a race window in `GameSessionManager.create_session` and uncontrolled automatic smart replies in groups. The implementation therefore adds a Redis distributed lock and persists a waiting session before returning, and adds the per-group `smart_responses` setting with a Redis cooldown for automatic Quran responses. Explicit download intent remains immediate because it is a direct user request.

A Chameleon private topic callback is intentionally allowed to target the bound group session because the game sends topic selection to the selector's private chat. All other game callbacks carrying a chat binding must match the callback message chat. This exception is narrow and covered by a regression test.
