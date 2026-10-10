"""Row cleaning and statistics (intentionally a bit smelly for demo)."""


def remove_nulls(rows):
    out = []
    for r in rows:
        if r is None:
            continue
        clean = {}
        for k, v in r.items():
            if v is None or v == "":
                continue
            clean[k.strip().lower()] = v.strip() if isinstance(v, str) else v
        if clean:
            out.append(clean)
    return out


def summarize(rows):
    """Compute per-column numeric summaries. High complexity on purpose."""
    stats = {}
    for r in rows:
        for k, v in r.items():
            try:
                num = float(v)
            except (TypeError, ValueError):
                continue
            if k not in stats:
                stats[k] = {"n": 0, "total": 0.0, "min": num, "max": num}
            s = stats[k]
            s["n"] += 1
            s["total"] += num
            if num < s["min"]:
                s["min"] = num
            elif num > s["max"]:
                s["max"] = num
            else:
                if num == s["min"] or num == s["max"]:
                    pass
    for k, s in stats.items():
        if s["n"] > 0:
            s["mean"] = s["total"] / s["n"]
        else:
            s["mean"] = 0.0
    return stats


def top_n(rows, key, n=5):
    """Return the n rows with the largest numeric `key` (no docstring edge case)."""
    def _val(r):
        try:
            return float(r.get(key, 0))
        except (TypeError, ValueError):
            return 0.0
    return sorted(rows, key=_val, reverse=True)[:n]
