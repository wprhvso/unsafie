import os
import shutil
import subprocess

TOOLCHAINS = ("kameleo", "nix", "rust", "tools", "libreoffice")

PROBES: dict[str, tuple[tuple[str, ...], ...]] = {
    "kameleo": (("docker",),),
    "nix": (("nix",),),
    "rust": (("cargo",),),
    "tools": (("rg",), ("jq",), ("zstd",), ("convert", "magick"), ("gh",)),
    "libreoffice": (("soffice", "libreoffice"),),
}


def setup(*what: str, timeout: float = 1800.0) -> dict[str, str]:
    wanted = [name for name in what if name in TOOLCHAINS]
    if not wanted:
        wanted = list(TOOLCHAINS)
    return {name: _toolchain(name, timeout) for name in wanted}


def missing(name: str) -> list[str]:
    return [
        " | ".join(group)
        for group in PROBES.get(name, ())
        if not any(shutil.which(binary) for binary in group)
    ]


def _toolchain(name: str, timeout: float) -> str:
    absent = missing(name)
    if not absent:
        return "already there"
    try:
        if name == "kameleo":
            return _apt(["docker.io"], timeout)
        if name == "tools":
            return _apt(["ripgrep", "fd-find", "jq", "zstd", "p7zip-full", "imagemagick", "gh"], timeout)
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
        if name == "libreoffice":
            return _apt(
                [
                    "libreoffice-writer-nogui",
                    "libreoffice-calc-nogui",
                    "libreoffice-impress-nogui",
                    "fonts-dejavu-core",
                    "fonts-liberation2",
                ],
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
            _sudo(line), env=environment, capture_output=True, text=True, check=False, timeout=timeout,
        )
        if done.returncode != 0:
            return f"apt failed: {done.stderr.strip()[-300:]}"
    return "installed"



def _shell(command: str, timeout: float) -> str:
    done = subprocess.run(
        ["/bin/bash", "-lc", command], capture_output=True, text=True, check=False, timeout=timeout,
    )
    return "installed" if done.returncode == 0 else f"failed: {done.stderr.strip()[-300:]}"
