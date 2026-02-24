.PHONY: install dev run

install:
	pip install -e .

dev: install
	python run.py

run: install
	python run.py
