"""Generate a synthetic NHS-style appointments dataset and make it deliberately messy.

Everything here is fake. A ground-truth file records each planted problem so we can
measure how many of them the profiler finds.

Usage: python make_test_data.py
Outputs: sample_data/nhs_appointments_dirty.csv, sample_data/ground_truth.json
"""
import json
import random
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
N = 1000
OUT = Path(__file__).parent / "sample_data"

random.seed(SEED)
rng = np.random.default_rng(SEED)

DEPARTMENTS = ["Cardiology", "Orthopaedics", "Dermatology", "Neurology", "Oncology", "Paediatrics"]
SITES = ["Birmingham", "Manchester", "Leeds", "Bristol"]
STATUSES = ["Attended", "DNA", "Cancelled"]


def clean_frame() -> pd.DataFrame:
    base = date(2025, 1, 1)
    appt_dates = [base + timedelta(days=int(d)) for d in rng.integers(0, 600, N)]
    booked = [d - timedelta(days=int(x)) for d, x in zip(appt_dates, rng.integers(1, 60, N))]
    age = np.clip(rng.normal(52, 20, N).round(), 1, 95).astype(int)
    return pd.DataFrame(
        {
            "appointment_id": [f"A{100000 + i}" for i in range(N)],
            "patient_id": [f"P{rng.integers(1000, 1400)}" for _ in range(N)],
            "age": age,
            "sex": rng.choice(["Male", "Female"], N),
            "site": rng.choice(SITES, N),
            "department": rng.choice(DEPARTMENTS, N),
            "booked_date": [d.isoformat() for d in booked],
            "appointment_date": [d.isoformat() for d in appt_dates],
            "status": rng.choice(STATUSES, N, p=[0.78, 0.14, 0.08]),
            "wait_days": [(a - b).days for a, b in zip(appt_dates, booked)],
            "cost_gbp": np.clip(rng.normal(120, 35, N), 15, None).round(2),
        }
    )


def make_dirty(df: pd.DataFrame):
    df = df.copy()
    truth = []

    def pick(k, exclude=()):
        pool = [i for i in range(len(df)) if i not in exclude]
        return random.sample(pool, k)

    used: set[int] = set()

    def plant(kind, column, rows, note):
        used.update(rows)
        truth.append({"kind": kind, "column": column, "rows": sorted(rows), "note": note})

    # Everything below goes into object columns so mixed junk is possible.
    for col in ["age", "wait_days", "cost_gbp"]:
        df[col] = df[col].astype(object)

    # 1. Missing values in several encodings
    rows = pick(40, used)
    for r in rows[:15]:
        df.at[r, "age"] = None
    for r in rows[15:28]:
        df.at[r, "age"] = "N/A"
    for r in rows[28:]:
        df.at[r, "age"] = "unknown"
    plant("missing_encodings", "age", rows, "mix of blank, 'N/A' and 'unknown'")

    rows = pick(30, used)
    for r in rows:
        df.at[r, "sex"] = random.choice(["", " ", "-"])
    plant("missing_encodings", "sex", rows, "blank, space or dash")

    # 2. Invalid values
    rows = pick(8, used)
    for r in rows:
        df.at[r, "age"] = random.choice([-3, -12, 0, 150, 212, 999])
    plant("invalid_value", "age", rows, "negative, zero or impossible ages")

    rows = pick(8, used)
    for r in rows:
        df.at[r, "cost_gbp"] = -abs(float(df.at[r, "cost_gbp"]))
    plant("invalid_value", "cost_gbp", rows, "negative cost")

    rows = pick(10, used)
    for r in rows:
        df.at[r, "appointment_date"] = (date.today() + timedelta(days=random.randint(400, 3000))).isoformat()
    plant("future_date", "appointment_date", rows, "appointment dates years in the future")

    # 3. Inconsistent date formats
    rows = pick(60, used)
    for r in rows:
        d = date.fromisoformat(df.at[r, "booked_date"])
        df.at[r, "booked_date"] = random.choice([d.strftime("%d/%m/%Y"), d.strftime("%d-%b-%Y"), d.strftime("%m/%d/%y")])
    plant("inconsistent_format", "booked_date", rows, "dates in dd/mm/yyyy, dd-Mon-yyyy and mm/dd/yy")

    # 4. Casing / spelling variants of categories
    rows = pick(50, used)
    for r in rows:
        df.at[r, "department"] = random.choice(
            [df.at[r, "department"].upper(), df.at[r, "department"].lower(), " " + df.at[r, "department"] + " "]
        )
    plant("inconsistent_category", "department", rows, "case and whitespace variants")

    rows = pick(40, used)
    for r in rows:
        df.at[r, "site"] = random.choice(["B'ham", "Brum", "birmingham", "Mancester", "Bristl"])
    plant("inconsistent_category", "site", rows, "nicknames and typos for site names")

    # 5. Outliers
    rows = pick(6, used)
    for r in rows:
        df.at[r, "cost_gbp"] = round(random.uniform(2500, 9000), 2)
    plant("outlier", "cost_gbp", rows, "extreme cost values")

    # 6. Wrong type in numeric column
    rows = pick(10, used)
    for r in rows:
        df.at[r, "wait_days"] = random.choice(["twelve", "3 weeks", "approx 10"])
    plant("mixed_types", "wait_days", rows, "text inside numeric column")

    # 7. Relationship break: appointment before booking
    rows = pick(12, used)
    for r in rows:
        ad = date.fromisoformat(df.at[r, "appointment_date"]) if df.at[r, "appointment_date"][4] == "-" else date(2025, 6, 1)
        df.at[r, "booked_date"] = (ad + timedelta(days=random.randint(5, 40))).isoformat()
    plant("relationship", "booked_date", rows, "booked_date after appointment_date")

    # 9. Duplicate IDs with different content
    rows = pick(5, used)
    for r in rows:
        df.at[r, "appointment_id"] = df.at[(r + 1) % N, "appointment_id"]
    plant("duplicate_key", "appointment_id", rows, "appointment_id reused with different data")

    # 10. A constant column and a nearly-empty column
    df["data_source"] = "legacy_export"
    comments = [None] * len(df)
    for r in random.sample(range(len(df)), 12):
        comments[r] = "see notes"
    df["clinician_comment"] = comments
    # 11. Merged-cell look: ward shown once per block, blank for the rest of the block
    wards = ["Ward A", "Ward B", "Ward C", "Ward D", "Ward E", "Ward F", "Ward G", "Ward H"]
    ward_col, blank_rows, i = [], [], 0
    while i < len(df):
        size = random.randint(3, 12)
        for j in range(min(size, len(df) - i)):
            ward_col.append(wards[random.randrange(len(wards))] if j == 0 else "")
            if j:
                blank_rows.append(i + j)
        i += size
    df["ward"] = ward_col
    truth.append({"kind": "possible_merged_cells", "column": "ward", "rows": blank_rows, "note": "ward blank after first row of each block"})

    truth.append({"kind": "constant_column", "column": "data_source", "rows": [], "note": "single value everywhere"})
    truth.append({"kind": "mostly_empty", "column": "clinician_comment", "rows": [], "note": "~99% empty"})

    # 8. Exact duplicate rows
    dup_src = random.sample(range(len(df)), 25)
    dups = df.iloc[dup_src].copy()
    df = pd.concat([df, dups], ignore_index=True)
    plant("duplicate_rows", "*", list(range(N, N + 25)), "25 exact duplicate rows appended")

    return df, truth


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    dirty, truth = make_dirty(clean_frame())
    dirty.to_csv(OUT / "nhs_appointments_dirty.csv", index=False)
    (OUT / "ground_truth.json").write_text(json.dumps(truth, indent=2))
    print(f"Wrote {len(dirty)} rows, {len(truth)} planted problem groups -> {OUT}")
