import importlib
import os
import shutil
import site
import subprocess
import sys
import sysconfig

from unsafie_sdk.errors import UnsafieError

TOOLCHAINS = ("chrome", "xvfb", "kasmvnc", "nix", "rust", "tools")
KASMVNC = "1.5.0"


def install(*packages: str, upgrade: bool = False, timeout: float = 600.0) -> list[str]:
    """Install python packages into this interpreter with uv, right now.

    install("pandas", "httpx") — then simply `import pandas`.
    """
    wanted = [name for name in packages if name.strip()]
    if not wanted:
        return []
    line = _installer(wanted, upgrade)
    done = subprocess.run(line, capture_output=True, text=True, check=False, timeout=timeout)
    if done.returncode != 0:
        tail = (done.stderr or done.stdout).strip()[-600:]
        raise UnsafieError(f"could not install {', '.join(wanted)}: {tail}")
    _refresh()
    return wanted


def _installer(packages: list[str], upgrade: bool) -> list[str]:
    if shutil.which("uv"):
        line = ["uv", "pip", "install", "--python", sys.executable, "--quiet"]
    else:
        line = [sys.executable, "-m", "pip", "install", "--quiet"]
    if upgrade:
        line.append("--upgrade")
    return [*line, *packages]


def _refresh() -> None:
    for path in {sysconfig.get_paths().get("purelib"), *site.getsitepackages()}:
        if path and path not in sys.path:
            sys.path.append(path)
    importlib.invalidate_caches()


def missing(error: ModuleNotFoundError) -> str:
    """The distribution name to install for a failed import."""
    return (error.name or "").split(".")[0]


def setup(*what: str, timeout: float = 1800.0) -> dict[str, str]:
    """Install a toolchain on this machine: chrome, xvfb, kasmvnc, nix, rust, tools."""
    unknown = [name for name in what if name not in TOOLCHAINS]
    if unknown:
        raise UnsafieError(f"nothing known as {', '.join(unknown)}", f"known: {', '.join(TOOLCHAINS)}")
    done: dict[str, str] = {}
    for name in what:
        done[name] = _toolchain(name, timeout)
    return done


def _toolchain(name: str, timeout: float) -> str:
    if _already(name):
        return "already there"
    if name == "chrome":
        return _apt(["chromium-browser"], timeout)
    if name == "xvfb":
        return _apt(["xvfb", "openbox", "x11-utils", "xauth", "xfonts-base"], timeout)
    if name == "tools":
        return _apt(["ripgrep", "fd-find", "jq", "zstd", "p7zip-full", "imagemagick"], timeout)
    if name == "kasmvnc":
        return _kasmvnc(timeout)
    if name == "nix":
        return _shell(
            "curl -fsSL https://nixos.org/nix/install | sh -s -- --daemon --yes --no-channel-add",
            timeout,
        )
    if name == "rust":
        return _shell(
            "curl -fsSL https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain stable",
            timeout,
        )
    return "unknown"


def _already(name: str) -> bool:
    probes = {
        "chrome": ("google-chrome", "chromium", "chromium-browser"),
        "xvfb": ("Xvfb",),
        "kasmvnc": ("Xkasmvnc", "kasmvncserver"),
        "nix": ("nix",),
        "rust": ("cargo",),
        "tools": ("rg", "jq"),
    }.get(name, ())
    return any(shutil.which(binary) for binary in probes)


def _sudo(line: list[str]) -> list[str]:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return line
    return ["sudo", "-n", *line] if shutil.which("sudo") else line


def _apt(packages: list[str], timeout: float) -> str:
    environment = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
    for line in (["apt-get", "update"], ["apt-get", "install", "-y", "--no-install-recommends", *packages]):
        done = subprocess.run(
            _sudo(line), env=environment, capture_output=True, text=True, check=False, timeout=timeout
        )
        if done.returncode != 0:
            raise UnsafieError(f"apt failed: {done.stderr.strip()[-300:]}")
    return "installed"


def _kasmvnc(timeout: float) -> str:
    codename = "noble"
    try:
        for line in open("/etc/os-release", encoding="utf-8"):
            if line.startswith("VERSION_CODENAME="):
                codename = line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    architecture = subprocess.run(
        ["dpkg", "--print-architecture"], capture_output=True, text=True, check=False
    ).stdout.strip() or "amd64"
    package = f"kasmvncserver_{codename}_{KASMVNC}_{architecture}.deb"
    url = f"https://github.com/kasmtech/KasmVNC/releases/download/v{KASMVNC}/{package}"
    target = f"/tmp/{package}"
    fetch = subprocess.run(
        ["curl", "-fsSL", "--retry", "3", "-o", target, url], capture_output=True, check=False,
        timeout=timeout,
    )
    if fetch.returncode != 0:
        raise UnsafieError("could not download KasmVNC")
    return _apt([target], timeout)


def _shell(command: str, timeout: float) -> str:
    done = subprocess.run(
        ["/bin/bash", "-lc", command], capture_output=True, text=True, check=False, timeout=timeout
    )
    if done.returncode != 0:
        raise UnsafieError(f"installer failed: {done.stderr.strip()[-300:]}")
    return "installed"
