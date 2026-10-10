"""Sample project: a tiny data-pipeline CLI used to demo CodeAtlas."""
from . import loader, transform, report

def main(paths):
    """Run the pipeline: load, clean, analyze and report on CSV files."""
    rows = loader.load_many(paths)
    clean = transform.remove_nulls(rows)
    stats = transform.summarize(clean)
    report.save_report(stats)
    report.print_summary(stats)

if __name__ == "__main__":
    import sys
    main(sys.argv[1:])
