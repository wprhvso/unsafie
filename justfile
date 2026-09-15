set dotenv-load := true

sync:
    cd python && uv sync --all-groups --all-extras

fix:
    cd python && ruff format
    cd python && ruff check --fix --unsafe-fixes

ci-basedpyright: sync
    cd python && basedpyright

ci-ruff:
    cd python && ruff check

ci-ruff-format:
    cd python && ruff format --check

ci-pytest: sync
    cd python && pytest tests/

cd-ansible *args:
    #!/usr/bin/env bash
    set -euo pipefail
    [ -f .env ] && set -a && . ./.env && set +a
    if [ -z "${VAULT_PASS:-}" ]; then
        if [ -f .vault_pass ]; then
            VAULT_PASS=$(cat .vault_pass)
        elif [ -f ansible/.vault_pass ]; then
            VAULT_PASS=$(cat ansible/.vault_pass)
        fi
    fi
    if [ -z "${VAULT_PASS:-}" ]; then
        echo "VAULT_PASS not found" >&2
        exit 1
    fi
    echo "$VAULT_PASS" > ansible/.vault_pass
    chmod 600 ansible/.vault_pass
    if [ -n "${SSH_PRIVATE_KEY:-}" ]; then
        mkdir -p ~/.ssh
        chmod 700 ~/.ssh
        echo "$SSH_PRIVATE_KEY" > ~/.ssh/id_ed25519
        chmod 600 ~/.ssh/id_ed25519
    fi
    cd ansible
    ansible-galaxy install -r requirements.yml
    [ -d ~/.local/share/mitogen ] || export ANSIBLE_STRATEGY=linear
    ANSIBLE_HOST_KEY_CHECKING=False ansible-playbook site.yml {{args}}

push-secrets:
    #!/usr/bin/env bash
    set -euo pipefail
    [ -f .env ] || { echo ".env not found" >&2; exit 1; }
    set -a && . ./.env && set +a
    if [ -z "${VAULT_PASS:-}" ]; then
        if [ -f .vault_pass ]; then
            VAULT_PASS=$(cat .vault_pass)
        elif [ -f ansible/.vault_pass ]; then
            VAULT_PASS=$(cat ansible/.vault_pass)
        fi
    fi
    if [ -z "${VAULT_PASS:-}" ]; then
        echo "VAULT_PASS not found" >&2
        exit 1
    fi
    if [ -z "${CI_TOKEN:-}" ]; then
        echo "CI_TOKEN not found" >&2
        exit 1
    fi
    TMP=$(mktemp)
    trap 'rm -f "$TMP"' EXIT
    cp .env "$TMP"
    grep -q '^VAULT_PASS=' "$TMP" 2>/dev/null || echo "VAULT_PASS=$VAULT_PASS" >> "$TMP"
    REPO="${GITHUB_REPOSITORY:-}"
    if [ -z "$REPO" ]; then
        REPO=$(git config --get remote.origin.url | sed -E 's/.*[:/]([^/]+\/[^/]+)(\.git)?$/\1/' | sed 's/\.git$//')
    fi
    API_URL="${PUBLIC_BASE_URL:-https://unsafie.com}"
    API_URL="${API_URL%/}"
    curl -sSf -X PUT "$API_URL/api/ci/secrets/$REPO/bulk" \
        -H "Authorization: Bearer $CI_TOKEN" \
        -H "Content-Type: text/plain" \
        --data-binary @"$TMP"
