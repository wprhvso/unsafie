fix:
    cd python && ruff format
    cd python && ruff check --fix --unsafe-fixes

ci-basedpyright:
    cd python && basedpyright

ci-ruff:
    cd python && ruff check

ci-ruff-format:
    cd python && ruff format --check

ci-pytest:
    cd python && pytest tests/
