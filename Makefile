# Self-documenting commands
.DEFAULT_GOAL := help
.PHONY: help
help: ## Show this help message
	@awk 'BEGIN {FS = ":.*?## "}; /^[a-zA-Z0-9_-]+:.*?## / {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: clean
clean: ## Remove temporary files
	@rm -rf .ipynb_checkpoints
	@rm -rf **/.ipynb_checkpoints
	@rm -rf __pycache__
	@rm -rf **/__pycache__
	@rm -rf **/**/__pycache__
	@rm -rf .pytest_cache
	@rm -rf **/.pytest_cache
	@rm -rf .ruff_cache
	@rm -rf .coverage
	@rm -rf build
	@rm -rf dist
	@rm -rf *.egg-info
	@rm -rf .mypy_cache
	@rm -rf .coverage*

.PHONY: venv
uv:  ## Install uv if it's not present.
	@command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh
	@uv sync --all-extras > /dev/null 2>&1

.PHONY: bump
bump: ## Show the next version
	@uv run bump-my-version show-bump

.PHONY: bump-patch
bump-patch: uv ## Bump patch version
	@printf "Applying patch bump\n"
	@uv run bump-my-version bump patch
	@$(MAKE) bump

.PHONY: bump-minor
bump-minor: uv ## Bump minor version
	@printf "Applying minor bump\n"
	@uv run bump-my-version bump minor
	@$(MAKE) bump

.PHONY: bump-major
bump-major: uv ## Bump major version
	@printf "Applying major bump\n"
	@uv run bump-my-version bump major
	@$(MAKE) bump

.PHONY: lint
lint: uv ## Run linters
	@printf "Running linters\n"
	@uv run ruff check

.PHONY: format
format: uv ## Format code
	@printf "Formatting code\n"
	@uv run ruff format

.PHONY: test
test: ## Run tests
	@printf "Running tests\n"
	@uv run tox
	$(MAKE) clean

.PHONY: check
check: uv ## Run linting, formatting, and tests
	@$(MAKE) lint
	@$(MAKE) format
	@$(MAKE) test
	@$(MAKE) clean

.PHONY: build
build: uv ## Build the project, documentation, and Docker image
	@printf "Building project\n"
	$(MAKE) check
	@uv build
