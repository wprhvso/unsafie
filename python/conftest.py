import site
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
candidates = [
    *root.glob(".venv/lib/python*/site-packages"),
    Path("/var/lib/unsafie/venv/lib/python3.14/site-packages"),
]
for p in candidates:
    if p.is_dir() and str(p) not in sys.path:
        site.addsitedir(str(p))

src_wire = root / "unsafie-wire" / "src"
if src_wire.is_dir() and str(src_wire) not in sys.path:
    sys.path.insert(0, str(src_wire))


def pytest_configure(config):
    if not config.pluginmanager.has_plugin("anyio"):
        import anyio.pytest_plugin

        config.pluginmanager.register(anyio.pytest_plugin, name="anyio")
