#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PYTHONPATH="${PYTHONPATH:-.}"
python -m compileall -q -f .
python -m pytest tests/ -q -W error
python -m pip check
python -m pip_audit -r requirements.txt
printf 'verification=passed\n'
