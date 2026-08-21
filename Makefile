.PHONY: install test compile lint audit check verify db-upgrade run docker-up

install:
	python3 -m pip install -r requirements.txt

compile:
	python -m compileall -q -f .

test:
	PYTHONPATH=. python -m pytest tests/ -q -W error

lint:
	ruff check --select E9,F401,RUF012 src tests config

audit:
	pip check
	pip-audit -r requirements.txt

check: compile test audit

verify: check

db-upgrade:
	alembic upgrade head

run:
	PYTHONPATH=. python main.py

docker-up:
	docker compose up -d --build
