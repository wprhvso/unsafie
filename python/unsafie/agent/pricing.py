COUNTERS = ("input_tokens", "output_tokens", "total_tokens")


def merge(total: dict, usage: dict) -> dict:
    for key in COUNTERS:
        total[key] = int(total.get(key) or 0) + int((usage or {}).get(key) or 0)
    return total
