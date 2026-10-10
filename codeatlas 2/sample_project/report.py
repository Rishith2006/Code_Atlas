"""Report rendering: console summary and CSV export."""
import csv


def print_summary(stats):
    """Print per-column min/mean/max to stdout."""
    for col, s in sorted(stats.items()):
        print(f"{col}: n={s['n']} min={s['min']:.2f} "
              f"mean={s['mean']:.2f} max={s['max']:.2f}")


def export_csv(stats, path="report.csv"):
    """Write the stats table to a CSV file."""
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["column", "n", "min", "mean", "max"])
        for col, s in sorted(stats.items()):
            w.writerow([col, s["n"], s["min"], s["mean"], s["max"]])
    return path


def save_report(stats):
    """Save report via CSV export and return the file path."""
    path = export_csv(stats)
    print(f"report written to {path}")
    return path
