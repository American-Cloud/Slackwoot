.PHONY: install dev run migrate db-upgrade db-downgrade db-history

install:
	pip install -e .

dev: install
	python run.py

run: install
	python run.py

# Database migration commands
migrate:
	alembic revision --autogenerate -m "$(msg)"

db-upgrade:
	alembic upgrade head

db-downgrade:
	alembic downgrade -1

db-history:
	alembic history --verbose
