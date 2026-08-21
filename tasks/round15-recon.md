# Reconnaissance — Round 15 Group Systems

## Baseline

The approved Round 14 archive was restored into `/home/ubuntu/guardian_work`. After installing the declared runtime dependencies plus `aiosqlite` required by the existing SQLite test fixtures, and starting local Redis, the unmodified baseline passed with:

- `python -m compileall -q -f .`
- `python -m pytest tests/ -q -W error`: **245 passed**

The first baseline attempt failed only because the sandbox did not initially have `pytest`, `aiosqlite`, or `redis-server`; these were environment prerequisites, not repository regressions.

## Verified group execution path

Group messages enter `src/handlers/message_handler.py::handle_message`, which filters to `group`/`supergroup` and calls `src.pipeline.orchestrator::run_pipeline`. Group member updates enter `handle_member_update`, which invokes join telemetry, raid detection, CAPTCHA, welcome, and leave handling. Administrative commands are registered in the same handler module and are delegated to `admin_commands.py`; sensitive commands use `_require_group_admin` or `_admin_only` and Telegram membership checks.

## Candidate configuration-drift gaps

1. `src/management/group_settings.py` declares an `anti_raid` per-group setting with default `on` and validation values `on/off`. `src/pipeline/raid_detector.py::check_raid` reads only global `settings.raid_join_threshold` and `settings.raid_join_window_seconds`; it does not read the group setting. Therefore the declared per-group anti-raid control appears disconnected from the real join-flood enforcement path.
2. `group_settings.py` declares `silent_mode`, while `src/layers/action_execution.py` appears to emit warnings without consulting that setting. This requires direct confirmation before choosing the scope.
3. `group_settings.py` declares `warn_limit`, while `src/layers/smart_warn.py` appears to use a separate `warnlimit:{chat_id}` key. This requires direct confirmation before choosing the scope.

## Round 15 constraint

Per the project continuation policy, select one evidence-backed gap, implement the smallest architectural change, add positive/negative/failure tests, run the focused and full suites, then update documentation and rebuild the archive. Do not add unrelated features or claim live Telegram validation.

## Official documentation findings

Telegram’s official Bot API documents that chat-member updates are a distinct update type and that group permission mutations are constrained by bot administrator status and available privileges [1]. The python-telegram-bot v22 documentation confirms that `ChatMemberHandler.CHAT_MEMBER` handles `Update.chat_member`, while `MY_CHAT_MEMBER` is a separate type; the handler only receives the update stream configured by the application [2]. These constraints support keeping raid detection best-effort and making any per-group control explicit rather than claiming guaranteed enforcement.

References:

[1]: https://core.telegram.org/bots/api "Telegram Bot API"
[2]: https://docs.python-telegram-bot.org/en/v22.5/telegram.ext.chatmemberhandler.html "ChatMemberHandler — python-telegram-bot v22.5"
