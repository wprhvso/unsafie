"""What a machine installs for itself before it joins the pool."""

import os
import shutil
import subprocess

TOOLCHAINS = ("chrome", "xvfb", "kasmvnc", "nix", "rust", "tools")
KASMVNC = "1.5.0"


def setup(*what: str, timeout: float = 1800.0) -> dict[str, str]:
    """Install toolchains on this machine: chrome, xvfb, kasmvnc, nix, rust, tools."""
    unknown = [name for name in what if name not in TOOLCHAINS]
    if unknown:
        raise ValueError(f"nothing known as {', '.join(unknown)}; known: {', '.join(TOOLCHAINS)}")
    return {name: _toolchain(name, timeout) for name in what}


def _toolchain(name: str, timeout: float) -> str:
    if _already(name):
        return "already there"
    try:
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
    except (OSError, subprocess.SubprocessError) as broken:
        return f"failed: {broken}"
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
    lines = (["apt-get", "update"], ["apt-get", "install", "-y", "--no-install-recommends", *packages])
    for line in lines:
        done = subprocess.run(
            _sudo(line), env=environment, capture_output=True, text=True, check=False, timeout=timeout
        )
        if done.returncode != 0:
            return f"apt failed: {done.stderr.strip()[-300:]}"
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
    fetched = subprocess.run(
        ["curl", "-fsSL", "--retry", "3", "-o", target, url],
        capture_output=True, check=False, timeout=timeout,
    )
    if fetched.returncode != 0:
        return "could not download KasmVNC"
    return _apt([target], timeout)


def _shell(command: str, timeout: float) -> str:
    done = subprocess.run(
        ["/bin/bash", "-lc", command], capture_output=True, text=True, check=False, timeout=timeout
    )
    return "installed" if done.returncode == 0 else f"failed: {done.stderr.strip()[-300:]}"
