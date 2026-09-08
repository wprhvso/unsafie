import os
import shutil
import subprocess

TOOLCHAINS = ("chrome", "xvfb", "kasmvnc", "nix", "rust", "tools")
KASMVNC = "1.5.0"

PROBES: dict[str, tuple[tuple[str, ...], ...]] = {
    "chrome": (("google-chrome", "chromium", "chromium-browser"),),
    "xvfb": (("Xvfb",), ("x11vnc",), ("openbox",), ("xauth",)),
    "kasmvnc": (("Xkasmvnc", "kasmvncserver"),),
    "nix": (("nix",),),
    "rust": (("cargo",),),
    "tools": (("rg",), ("jq",), ("zstd",), ("convert", "magick"), ("gh",)),
}


def setup(*what: str, timeout: float = 1800.0) -> dict[str, str]:
    wanted = [name for name in what if name in TOOLCHAINS]
    if not wanted:
        wanted = list(TOOLCHAINS)
    return {name: _toolchain(name, timeout) for name in wanted}


def missing(name: str) -> list[str]:
    absent = []
    for group in PROBES.get(name, ()):
        if not any(shutil.which(binary) for binary in group):
            absent.append(" | ".join(group))
    return absent


def _toolchain(name: str, timeout: float) -> str:
    absent = missing(name)
    if not absent:
        return "already there"
    try:
        if name == "chrome":
            return _apt(["chromium-browser"], timeout)
        if name == "xvfb":
            return _apt(["xvfb", "openbox", "x11-utils", "xauth", "xfonts-base", "x11vnc"], timeout)
        if name == "tools":
            return _apt(["ripgrep", "fd-find", "jq", "zstd", "p7zip-full", "imagemagick", "gh"], timeout)
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
    except Exception as broken:
        return f"failed: {broken}"
    return "unknown"


def _sudo(line: list[str]) -> list[str]:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return line
    return ["sudo", "-n", *line] if shutil.which("sudo") else line


def _apt(packages: list[str], timeout: float) -> str:
    if not shutil.which("apt-get"):
        return "skipped (no apt-get)"
    environment = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
    lines = (["apt-get", "update"], ["apt-get", "install", "-y", "--no-install-recommends", *packages])
    for line in lines:
        done = subprocess.run(
            _sudo(line), env=environment, capture_output=True, text=True, check=False, timeout=timeout
        )
        if done.returncode != 0:
            return f"apt failed: {done.stderr.strip()[-300:]}"
    return "installed"


def _kasmvnc(timeout: float) -> str:
    if not shutil.which("apt-get"):
        return "skipped (no apt-get)"
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
    fetched = subprocess.run(
        ["curl", "-fsSL", "--retry", "3", "-o", target, url],
        capture_output=True, text=True, check=False, timeout=timeout,
    )
    if fetched.returncode != 0:
        return f"could not download {url}: {fetched.stderr.strip()[-200:] or 'curl failed'}"
    return _apt([target], timeout)


def _shell(command: str, timeout: float) -> str:
    done = subprocess.run(
        ["/bin/bash", "-lc", command], capture_output=True, text=True, check=False, timeout=timeout
    )
    return "installed" if done.returncode == 0 else f"failed: {done.stderr.strip()[-300:]}"
