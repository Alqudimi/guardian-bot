#!/usr/bin/env bash
set -u
cd "$(dirname "${BASH_SOURCE[0]}")/.."
printf '%s\n' 'Guardian Bot environment doctor'
printf 'python: '; python3 --version || true
printf 'redis: '; command -v redis-cli >/dev/null && redis-cli ping 2>/dev/null || printf 'unavailable\n'
printf 'postgres: '; command -v pg_isready >/dev/null && pg_isready 2>/dev/null || printf 'unavailable\n'
printf 'docker: '; command -v docker >/dev/null && docker --version || printf 'unavailable\n'
printf 'python-telegram-bot: '; python3 -c 'import telegram; print(telegram.__version__)' 2>/dev/null || printf 'unavailable\n'
printf 'celery: '; python3 -c 'import celery; print(celery.__version__)' 2>/dev/null || printf 'unavailable\n'
printf 'secrets tracked: '; git ls-files | grep -E '(^|/)(\.env($|\.)|.*\.pem$|.*\.key$)' >/dev/null && printf 'WARNING\n' || printf 'none detected\n'
