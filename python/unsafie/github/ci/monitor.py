import os

PAGE_SIZE = os.sysconf("SC_PAGE_SIZE") or 4096


def get_pgrp_stats(pgid: int) -> tuple[float, int]:
    total_rss_bytes = 0
    total_cpu_ticks = 0
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            pid = int(entry)
            try:
                with open(f"/proc/{pid}/stat", "rb") as f:
                    data = f.read()
                idx = data.rfind(b")")
                if idx == -1:
                    continue
                fields = data[idx + 2 :].split()
                if int(fields[2]) == pgid or pid == pgid:
                    total_cpu_ticks += int(fields[11]) + int(fields[12])
                    with open(f"/proc/{pid}/statm") as fm:
                        pages = int(fm.read().split()[1])
                        total_rss_bytes += pages * PAGE_SIZE
            except (FileNotFoundError, ProcessLookupError, PermissionError, IndexError, ValueError):
                continue
    except Exception:
        pass
    rss_mb = round(total_rss_bytes / (1024 * 1024), 2)
    return rss_mb, total_cpu_ticks


def get_tree_rss_mb(root_pid: int) -> float:
    rss, _ = get_pgrp_stats(root_pid)
    return rss


def get_tree_cpu_ticks(root_pid: int) -> int:
    _, ticks = get_pgrp_stats(root_pid)
    return ticks


def get_net_bytes() -> tuple[int, int]:
    rx = 0
    tx = 0
    try:
        with open("/proc/net/dev", encoding="utf-8", errors="ignore") as f:
            for line in f.readlines()[2:]:
                parts = line.split(":")
                if len(parts) == 2:
                    iface = parts[0].strip()
                    if iface == "lo":
                        continue
                    stats = parts[1].split()
                    if len(stats) >= 9:
                        rx += int(stats[0])
                        tx += int(stats[8])
    except Exception:
        pass
    return rx, tx
