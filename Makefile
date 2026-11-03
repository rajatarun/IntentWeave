.PHONY: install lint test validate sam-build

install:
	pip install -r requirements-dev.txt

lint:
	ruff check src tests
	ruff format --check src tests

test:
	pytest -q

validate:
	PATH="$$HOME/.local/bin:$$PATH" sam validate --lint

sam-build:
	PATH="$$HOME/.local/bin:$$PATH" sam build
