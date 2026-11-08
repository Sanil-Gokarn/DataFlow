"""Score the profiler against the planted problems in sample_data/ground_truth.json.

Recall    = planted bad rows the profiler flagged / planted bad rows.
Precision = flagged rows that were planted / flagged rows (for the matching issue types only).
Run: python evaluate.py
"""
import json
from pathlib import Path

from dataflow import load_csv, profile

HERE = Path(__file__).parent / "sample_data"

# Which issue types count as "finding" each kind of planted problem.
ACCEPT = {
    "missing_encodings": {"missing_values", "missing_encodings"},
    "invalid_value": {"invalid_value", "outlier"},
    "future_date": {"future_date"},
    "inconsistent_format": {"inconsistent_format"},
    "inconsistent_category": {"inconsistent_category", "possible_typo", "rare_values"},
    "outlier": {"outlier"},
    "mixed_types": {"mixed_types"},
    "relationship": {"date_order", "derived_mismatch"},
    "duplicate_rows": {"duplicate_rows"},
    "duplicate_key": {"duplicate_key"},
    "constant_column": {"constant_column"},
    "mostly_empty": {"mostly_empty"},
    "possible_merged_cells": {"possible_merged_cells"},
}


def evaluate(df=None, truth=None, report=None):
    df = df if df is not None else load_csv(HERE / "nhs_appointments_dirty.csv")
    truth = truth if truth is not None else json.loads((HERE / "ground_truth.json").read_text())
    report = report or profile(df)
    results = []
    for t in truth:
        kinds = ACCEPT[t["kind"]]
        hits = [i for i in report.issues if i.kind in kinds and (t["column"] == "*" or t["kind"] == "relationship" or i.column == t["column"])]
        flagged = set().union(*[set(i.rows) for i in hits]) if hits else set()
        planted = set(t["rows"])
        if planted:
            recall = len(planted & flagged) / len(planted)
            precision = len(planted & flagged) / len(flagged) if flagged else 0.0
        else:  # column-level problem: found or not
            recall = 1.0 if hits else 0.0
            precision = 1.0 if hits else 0.0
        results.append({**t, "recall": recall, "precision": precision, "found_by": sorted({i.kind for i in hits})})
    return results


if __name__ == "__main__":
    res = evaluate()
    print(f"{'problem':24}{'column':20}{'planted':>8}{'recall':>8}{'precision':>10}  found by")
    for r in res:
        n = len(r["rows"]) or "col"
        print(f"{r['kind']:24}{r['column']:20}{n!s:>8}{r['recall']:>8.0%}{r['precision']:>10.0%}  {', '.join(r['found_by']) or '— MISSED'}")
    row_based = [r for r in res if r["rows"]]
    total = sum(len(r["rows"]) for r in row_based)
    caught = sum(round(r["recall"] * len(r["rows"])) for r in row_based)
    print(f"\nPlanted bad cells/rows caught: {caught}/{total} ({caught / total:.0%}); "
          f"column-level problems found: {sum(1 for r in res if not r['rows'] and r['recall'])}/{sum(1 for r in res if not r['rows'])}")
