from pathlib import Path


def _get_process_tree_pids(root_pid: int) -> set[int]:
    pids = {root_pid}
    proc = Path("/proc")
    if not proc.is_dir():
        return pids
    try:
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            try:
                status_file = entry / "status"
                if not status_file.is_file():
                    continue
                with open(status_file, encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if line.startswith("PPid:"):
                            ppid = int(line.split()[1])
                            if ppid in pids:
                                pids.add(pid)
                            break
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
    except Exception:
        pass
    return pids

def get_tree_rss_mb(root_pid: int) -> float:
    pids = _get_process_tree_pids(root_pid)
    total_kb = 0
    for pid in pids:
        try:
            with open(f"/proc/{pid}/status", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        parts = line.split()
                        if len(parts) >= 2 and parts[1].isdigit():
                            total_kb += int(parts[1])
                        break
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    return round(total_kb / 1024.0, 2)

def get_tree_cpu_ticks(root_pid: int) -> int:
    pids = _get_process_tree_pids(root_pid)
    total_ticks = 0
    for pid in pids:
        try:
            with open(f"/proc/{pid}/stat", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                idx = content.rfind(")")
                if idx != -1:
                    fields = content[idx + 2:].split()
                    utime = int(fields[11])
                    stime = int(fields[12])
                    total_ticks += utime + stime
        except (FileNotFoundError, ProcessLookupError, PermissionError, IndexError, ValueError):
            continue
    return total_ticks

def get_net_bytes() -> tuple[int, int]:
    rx = 0
    tx = 0
    try:
        with open("/proc/net/dev", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()[2:]
            for line in lines:
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
