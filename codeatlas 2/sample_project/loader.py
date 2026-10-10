"""CSV loading helpers."""
import csv
import os


def load_one(path):
    """Load a single CSV file into a list of dict rows."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def load_many(paths):
    """Load many CSV files, skipping ones that fail to parse."""
    rows = []
    for p in paths:
        try:
            rows.extend(load_one(p))
        except (FileNotFoundError, csv.Error):
            continue
    return rows
