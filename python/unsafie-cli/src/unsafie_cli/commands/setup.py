import os
import shutil
import subprocess

from unsafie_cli.errors import FAILED, OK, CliError, Usage
from unsafie_cli.output import Out
from unsafie_cli.parser import Call

KASMVNC = "1.5.0"

RECIPES: dict[str, list[list[str]]] = {
    "chrome": [
        ["apt-get", "update"],
        ["apt-get", "install", "-y", "--no-install-recommends", "chromium-browser"],
    ],
    "xvfb": [
        ["apt-get", "update"],
        [
            "apt-get",
            "install",
            "-y",
            "--no-install-recommends",
            "xvfb",
            "openbox",
            "x11-utils",
            "xauth",
            "xfonts-base",
        ],
    ],
    "kasmvnc": [],
    "nix": [],
    "rust": [],
    "android": [],
    "tools": [
        ["apt-get", "update"],
        [
            "apt-get",
            "install",
            "-y",
            "--no-install-recommends",
            "ripgrep",
            "fd-find",
            "jq",
            "zstd",
            "p7zip-full",
            "imagemagick",
        ],
    ],
}


def setup(call: Call, out: Out) -> int:
    wanted = call.many("what")
    if not wanted:
        raise Usage("what should I install?", "unsafie setup chrome xvfb kasmvnc nix rust")
    unknown = [name for name in wanted if name not in RECIPES]
    if unknown:
        raise Usage(
            f"nothing known as {', '.join(unknown)}",
            "known: " + ", ".join(sorted(RECIPES)),
        )
    done: dict[str, str] = {}
    for name in wanted:
        done[name] = _install(name, out)
    out.send({"installed": done}, [f"{name}: {state}" for name, state in done.items()])
    return OK if all(state != "failed" for state in done.values()) else FAILED


def _install(name: str, out: Out) -> str:
    if _already(name):
        return "already there"
    if name == "kasmvnc":
        return _kasmvnc(out)
    if name == "nix":
        return _shell(
            "curl -fsSL https://nixos.org/nix/install | sh -s -- --daemon --yes --no-channel-add",
            out,
        )
    if name == "rust":
        return _shell(
            "curl -fsSL https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain stable",
            out,
        )
    if name == "android":
        return "install it from the workflow, it is too large for a lease"
    for line in RECIPES[name]:
        if _run(_sudo(line), out) != 0:
            return "failed"
    return "installed"


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


def _kasmvnc(out: Out) -> str:
    codename = _codename()
    architecture = _arch()
    package = f"kasmvncserver_{codename}_{KASMVNC}_{architecture}.deb"
    url = f"https://github.com/kasmtech/KasmVNC/releases/download/v{KASMVNC}/{package}"
    target = f"/tmp/{package}"
    if _run(["curl", "-fsSL", "--retry", "3", "-o", target, url], out) != 0:
        return "failed"
    if _run(_sudo(["apt-get", "install", "-y", target]), out) != 0:
        return "failed"
    return "installed"


def _codename() -> str:
    try:
        for line in open("/etc/os-release", encoding="utf-8"):
            if line.startswith("VERSION_CODENAME="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "noble"


def _arch() -> str:
    done = subprocess.run(["dpkg", "--print-architecture"], capture_output=True, text=True, check=False)
    return done.stdout.strip() or "amd64"


def _sudo(line: list[str]) -> list[str]:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return line
    if shutil.which("sudo"):
        return ["sudo", "-n", *line]
    return line


def _run(line: list[str], out: Out) -> int:
    environment = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
    done = subprocess.run(line, env=environment, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        out.problem(f"{' '.join(line[:3])}…: {done.stderr.strip()[:200]}")
    return done.returncode


def _shell(command: str, out: Out) -> str:
    done = subprocess.run(["/bin/bash", "-lc", command], capture_output=True, text=True, check=False)
    if done.returncode != 0:
        out.problem(done.stderr.strip()[:300])
        raise CliError("the installer failed", FAILED)
    return "installed"
