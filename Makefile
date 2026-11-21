.DEFAULT_GOAL := help
.PHONY: e2e-sibei docker-fluidsynth help install lint fmt typecheck test test-integration check licenses hooks

help:  ## List targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-18s %s\n", $$1, $$2}'

install:  ## Install dependencies from the lockfile
	uv sync --frozen

lint:  ## Ruff check and format check
	uv run ruff check .
	uv run ruff format --check .

fmt:  ## Apply ruff fixes and formatting
	uv run ruff check --fix .
	uv run ruff format .

typecheck:  ## mypy (strict) on src
	uv run mypy

test:  ## Fast no-infra tests
	uv run pytest tests/unit -q

test-integration:  ## Tests that need fluidsynth and a soundfont
	uv run pytest tests/integration -q

check: lint typecheck test  ## The pre-push gate: lint, types, fast tests

licenses:  ## Fail if a runtime dependency is GPL/AGPL
	uv run --no-dev python scripts/check_licenses.py

hooks:  ## Install the pre-push hook
	ln -sf ../../scripts/git-hooks/pre-push .git/hooks/pre-push

docker-fluidsynth:  ## Build the fluidsynth image used when no local fluidsynth is installed
	docker build -t mat-fluidsynth docker/fluidsynth

e2e-sibei:  ## Audio to PDF through a local sibei-score (needs SIBEI_SCORE_DIR)
	scripts/e2e-sibei.sh
