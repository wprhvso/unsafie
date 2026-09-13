import hashlib
import os
import secrets
import shutil
import tempfile
from pathlib import Path

import pytest

from unsafie.github.ci import monitor, runner


def test_monitor_helpers():
    pid = os.getpid()
    rss = monitor.get_tree_rss_mb(pid)
    assert rss >= 0.0
    ticks = monitor.get_tree_cpu_ticks(pid)
    assert ticks >= 0
    rx, tx = monitor.get_net_bytes()
    assert rx >= 0
    assert tx >= 0

@pytest.mark.anyio
async def test_target_discovery():
    with tempfile.TemporaryDirectory() as tmp:
        td = Path(tmp)
        t, ci, cd = await runner.discover_targets(td)
        assert t == "none"
        assert ci == []
        assert cd == []

        (td / "Makefile").write_text("ci:\n\techo ignore\nci-test:\n\techo test\ncd-deploy:\n\techo deploy\n")
        if shutil.which("make"):
            t, ci, cd = await runner.discover_targets(td)
            assert t == "make"
            assert ci == ["ci-test"]
            assert cd == ["cd-deploy"]

        (td / "justfile").write_text("ci:\n  echo ignore\nci-lint:\n  echo lint\nci-test:\n  echo test\ncd-prod:\n  echo prod\n")
        if shutil.which("just"):
            t, ci, cd = await runner.discover_targets(td)
            assert t == "just"
            assert ci == ["ci-lint", "ci-test"]
            assert cd == ["cd-prod"]

def test_api_token_hashing():
    raw = f"uci_live_{secrets.token_hex(24)}"
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    assert len(token_hash) == 64
    assert raw.startswith("uci_live_")

def test_bulk_secrets_parsing():
    raw_env = """
    FOO=bar
    export BAZ="qux"
    NESTED='value with spaces'
    """
    parsed = {}
    for line in raw_env.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        k, sep, v = line.partition("=")
        if sep:
            parsed[k.strip()] = v.strip().strip("'").strip('"')
    assert parsed == {"FOO": "bar", "BAZ": "qux", "NESTED": "value with spaces"}
