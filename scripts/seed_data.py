"""Generate the synthetic dataset, the document set and the evaluation cases.

Run from the repository root:

    python scripts/seed_data.py

Everything is deterministic (random.Random(42)), so a fresh clone reproduces the
same numbers, the same documents and the same 20 evaluation cases.
"""
from __future__ import annotations

import json
import random
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import DATA_DIR, DB_PATH, DOCS_DIR, EVAL_CASES_PATH  # noqa: E402
from app.rules import decide  # noqa: E402
from scripts.documents import DOCUMENTS  # noqa: E402

SEED = 42
TODAY = date(2026, 10, 24)

SUPPLIERS = [
    ("SUP-01", "Northwind Components", "DE", 4.6, 0.97),
    ("SUP-02", "Acme Manufacturing", "US", 4.1, 0.93),
    ("SUP-03", "Vertex Precision", "CN", 3.8, 0.89),
    ("SUP-04", "BlueHarbor Metals", "AU", 4.4, 0.95),
    ("SUP-05", "Kestrel Plastics", "GB", 3.5, 0.81),
    ("SUP-06", "Orbital Fasteners", "IN", 2.9, 0.76),
]

PARTS = [
    ("NX-1042", "Hydraulic Manifold", "SUP-01", 24),
    ("NX-1043", "Hydraulic Manifold, small", "SUP-01", 18),
    ("AC-2201", "Control Housing", "SUP-02", 24),
    ("AC-2202", "Control Housing, sealed", "SUP-02", 18),
    ("VX-3310", "Precision Bracket", "SUP-03", 12),
    ("VX-3311", "Precision Bracket, reinforced", "SUP-03", 18),
    ("BH-4408", "Marine Coupling", "SUP-04", 24),
    ("BH-4409", "Marine Coupling, coated", "SUP-04", 24),
    ("KP-5512", "Cable Gland Body", "SUP-05", 12),
    ("KP-5513", "Cable Gland Body, brass", "SUP-05", 18),
    ("OF-6620", "Threaded Insert", "SUP-06", 12),
    ("OF-6621", "Threaded Insert, stainless", "SUP-06", 18),
]

DEFECT_CODES = [
    "CORROSION", "SURFACE", "DIM_OUT", "CRACK", "LEAK", "DELAM", "THREAD", "ELECTRICAL",
]
DEFECT_WEIGHTS = [18, 24, 20, 8, 10, 6, 8, 6]

FEATURES = [
    ("wall_thickness", 12.00, 0.30, 0.10),   # name, target, +tol, -tol
    ("diameter", 48.00, 0.15, 0.15),
    ("length", 120.00, 0.50, 0.50),
    ("thread_pitch", 2.00, 0.02, 0.02),
]

REPORTERS = ["A. Iversen", "M. Duarte", "S. Kumar", "L. Novak", "R. Hayes", "T. Okafor"]
SHIFTS = ["A", "B", "C"]
LINES = ["L1", "L2", "L3", "L4"]


def build_documents() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    for doc in DOCUMENTS:
        lines = [f"# {doc['title']}", "", f"_Document ID: `{doc['doc_id']}` — synthetic demo content._", ""]
        for heading, paragraphs in doc["sections"]:
            lines.append(f"## {heading}")
            lines.append("")
            for para in paragraphs:
                lines.append(para)
                lines.append("")
        (DOCS_DIR / f"{doc['doc_id']}.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def build_db() -> dict:
    if DB_PATH.exists():
        DB_PATH.unlink()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.executescript(
        """
        DROP TABLE IF EXISTS suppliers;
        DROP TABLE IF EXISTS parts;
        DROP TABLE IF EXISTS work_orders;
        DROP TABLE IF EXISTS defect_reports;
        DROP TABLE IF EXISTS spc_measurements;
        DROP TABLE IF EXISTS warranty_policies;

        CREATE TABLE suppliers (
            id TEXT PRIMARY KEY, name TEXT, country TEXT, rating REAL, on_time_rate REAL
        );
        CREATE TABLE parts (
            part_number TEXT PRIMARY KEY, name TEXT, supplier_id TEXT, warranty_months INTEGER
        );
        CREATE TABLE work_orders (
            id TEXT PRIMARY KEY, part_number TEXT, line TEXT, started_at TEXT,
            quantity INTEGER, shift TEXT
        );
        CREATE TABLE defect_reports (
            id TEXT PRIMARY KEY, work_order_id TEXT, defect_code TEXT, severity TEXT,
            description TEXT, reported_at TEXT, reporter TEXT
        );
        CREATE TABLE spc_measurements (
            id TEXT PRIMARY KEY, work_order_id TEXT, feature TEXT, measured_value REAL,
            target REAL, usl REAL, lsl REAL, measured_at TEXT
        );
        CREATE TABLE warranty_policies (
            id TEXT PRIMARY KEY, part_number_pattern TEXT, rule_type TEXT, threshold REAL,
            action TEXT, notes TEXT
        );
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        """
    )

    cur.executemany("INSERT INTO suppliers VALUES (?,?,?,?,?)", SUPPLIERS)
    cur.executemany("INSERT INTO parts VALUES (?,?,?,?)", PARTS)

    # --- work orders -------------------------------------------------------
    work_orders: list[dict] = []
    for i in range(40):
        part = PARTS[i % len(PARTS)]
        # Age spread: recent orders for q"fresh" cases, older ones for expired cases.
        age_days = rng.choice([12, 25, 40, 68, 95, 140, 210, 300, 420, 560, 700, 810])
        started = TODAY - timedelta(days=age_days)
        wo = {
            "id": f"WO-{1001 + i}",
            "part_number": part[0],
            "line": LINES[i % len(LINES)],
            "started_at": started.isoformat(),
            "quantity": rng.choice([50, 120, 200, 350, 500, 800]),
            "shift": SHIFTS[i % len(SHIFTS)],
            "age_days": age_days,
        }
        work_orders.append(wo)
        cur.execute(
            "INSERT INTO work_orders VALUES (?,?,?,?,?,?)",
            (wo["id"], wo["part_number"], wo["line"], wo["started_at"], wo["quantity"], wo["shift"]),
        )

    # --- SPC measurements --------------------------------------------------
    # A deliberate gap: every 7th work order has NO measurement data, which is what
    # produces the "insufficient evidence" cases in the evaluation set.
    no_spc = {wo["id"] for idx, wo in enumerate(work_orders) if idx % 7 == 3}
    meas_id = 0
    for wo in work_orders:
        if wo["id"] in no_spc:
            continue
        feature = rng.choice(FEATURES)
        name, target, plus, minus = feature
        # Some orders are deliberately off-centre to produce low Cpk.
        drift = rng.choice([0.0, 0.0, 0.0, plus * 0.55, -minus * 0.55, plus * 0.9])
        spread = plus * rng.choice([0.10, 0.14, 0.18, 0.26])
        for _ in range(15):
            meas_id += 1
            value = round(target + drift + rng.gauss(0, spread), 3)
            cur.execute(
                "INSERT INTO spc_measurements VALUES (?,?,?,?,?,?,?,?)",
                (
                    f"SPC-{meas_id:04d}", wo["id"], name, value, target,
                    round(target + plus, 3), round(target - minus, 3), wo["started_at"],
                ),
            )

    # --- defect reports ----------------------------------------------------
    report_id = 0
    for wo in work_orders:
        for _ in range(rng.randint(2, 4)):
            report_id += 1
            code = rng.choices(DEFECT_CODES, weights=DEFECT_WEIGHTS, k=1)[0]
            severity = {
                "CRACK": "critical", "LEAK": "high", "CORROSION": "medium",
                "DIM_OUT": "medium", "ELECTRICAL": "high", "DELAM": "medium",
                "THREAD": "low", "SURFACE": "low",
            }[code]
            reported = datetime.fromisoformat(wo["started_at"]) + timedelta(days=rng.randint(0, 9))
            cur.execute(
                "INSERT INTO defect_reports VALUES (?,?,?,?,?,?,?)",
                (
                    f"DR-{report_id:04d}", wo["id"], code, severity,
                    f"{code.title().replace('_', ' ')} found during {rng.choice(['in-process inspection', 'final inspection', 'customer return']) }.",
                    reported.date().isoformat(), rng.choice(REPORTERS),
                ),
            )

    # --- warranty policies -------------------------------------------------
    policies = [
        ("WP-01", "NX-*", "corrosion_coverage", 18, "approve_warranty", "18+ month parts: corrosion covered inside 12 months"),
        ("WP-02", "*", "coverage_window", 0, "evaluate", "Coverage measured from work order completion date"),
        ("WP-03", "*", "cpk_threshold_marginal", 1.33, "rework", "Cpk below 1.33 is marginal: STD-SPC-01"),
        ("WP-04", "*", "cpk_threshold_acceptable", 1.00, "reject", "Cpk below 1.00 not releasable"),
        ("WP-05", "AC-*", "electrical_exclusion", 0, "escalate", "Electrical covered only for manufacturing defects"),
        ("WP-06", "BH-*", "corrosion_coverage", 24, "approve_warranty", "Marine parts: 24 month coverage"),
        ("WP-07", "*", "supplier_defect_rate", 2.0, "escalate", "Above 2 per thousand triggers SCAR"),
        ("WP-08", "VX-*", "warranty_period", 12, "reject", "12 month coverage only"),
    ]
    cur.executemany("INSERT INTO warranty_policies VALUES (?,?,?,?,?,?)", policies)

    # The dataset's reference date. Claim ages are computed against this value so
    # the demo stays reproducible instead of drifting as real time passes.
    cur.execute("INSERT INTO meta VALUES ('as_of', ?)", (TODAY.isoformat(),))

    conn.commit()
    conn.close()

    return {
        "work_orders": work_orders,
        "no_spc": no_spc,
        "counts": {
            "suppliers": len(SUPPLIERS),
            "parts": len(PARTS),
            "work_orders": len(work_orders),
            "defect_reports": report_id,
            "spc_measurements": meas_id,
            "warranty_policies": len(policies),
        },
    }


def cpk_for(work_order_id: str) -> float | None:
    """Recompute capability exactly the way the app does, for expectation building."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT measured_value, usl, lsl FROM spc_measurements WHERE work_order_id = ?",
        (work_order_id,),
    ).fetchall()
    conn.close()
    if not rows:
        return None
    values = [r[0] for r in rows]
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    std = variance ** 0.5
    usl, lsl = rows[0][1], rows[0][2]
    from app.rules import cpk

    return cpk(mean, std, usl, lsl)


def build_eval_cases(info: dict) -> list[dict]:
    """Build 20 cases whose expected outcome is computed by the rule engine itself.

    That is intentional: the evaluation measures whether the *pipeline* reaches the
    decision the policies dictate, not whether it can invent a different one.
    """
    parts = {p[0]: {"warranty_months": p[3], "supplier_id": p[2], "name": p[1]} for p in PARTS}
    suppliers = {s[0]: {"name": s[1], "rating": s[3], "on_time": s[4]} for s in SUPPLIERS}

    plans = [
        # (defect_code, preferred age filter, count)
        ("CORROSION", "fresh", 4),
        ("CORROSION", "boundary", 3),
        ("DIM_OUT", "fresh", 4),
        ("DIM_OUT", "nospc", 3),
        ("CRACK", "fresh", 2),
        ("DIM_OUT", "expired", 2),
        ("SURFACE", "fresh", 1),
        ("ELECTRICAL", "fresh", 1),
    ]

    cases: list[dict] = []
    used: set[str] = set()
    case_no = 0
    rng = random.Random(SEED + 1)

    for code, bucket, count in plans:
        made = 0
        for wo in info["work_orders"]:
            if made >= count or wo["id"] in used:
                continue
            age = wo["age_days"]
            part = parts[wo["part_number"]]
            warranty_days = part["warranty_months"] * 30
            has_spc = wo["id"] not in info["no_spc"]

            ok = False
            if bucket == "fresh":
                ok = has_spc and 10 <= age <= 330
            elif bucket == "boundary":
                ok = has_spc and 100 <= age <= 300 and part["warranty_months"] >= 18
            elif bucket == "nospc":
                ok = not has_spc
            elif bucket == "expired":
                ok = age > warranty_days
            if not ok:
                continue

            cpk_value = None if not has_spc else cpk_for(wo["id"])
            result = decide(
                part_number=wo["part_number"],
                defect_code=code,
                warranty_months=part["warranty_months"],
                age_days=age,
                cpk_value=cpk_value,
            )
            # Skip cases whose expected outcome duplicates a bucket already covered.
            if any(c["expected_outcome"] == result.decision and c["defect_code"] == code for c in cases) and count == 1:
                continue

            case_no += 1
            used.add(wo["id"])
            made += 1
            cases.append(
                {
                    "case_id": f"CASE-{case_no:03d}",
                    "work_order_id": wo["id"],
                    "part_number": wo["part_number"],
                    "defect_code": code,
                    "question": (
                        f"Customer claim on {wo['part_number']} ({part['name']}) from work order "
                        f"{wo['id']} shipped {wo['started_at']}. Claimed defect mode: {code.replace('_', ' ').lower()}. "
                        f"Quantity {rng.choice([1, 2, 5, 12])}, reported against "
                        f"{suppliers[part['supplier_id']]['name']}. What should we do?"
                    ),
                    "expected_outcome": result.decision,
                    "expected_rule": result.rule_id,
                    "expected_evidence": ["POL-WAR-01"] if code != "DIM_OUT" else ["POL-WAR-01", "STD-SPC-01"],
                    "has_spc": has_spc,
                    "age_days": age,
                    "warranty_months": part["warranty_months"],
                    "cpk": cpk_value,
                }
            )
            if made >= count:
                break

    return cases


def main() -> None:
    build_documents()
    info = build_db()
    cases = build_eval_cases(info)
    EVAL_CASES_PATH.write_text(json.dumps(cases, indent=2), encoding="utf-8")

    print("Seeded synthetic dataset")
    for key, value in info["counts"].items():
        print(f"  {key:>18}: {value}")
    print(f"  {'documents':>18}: {len(DOCUMENTS)}")
    print(f"  {'eval cases':>18}: {len(cases)}")
    print(f"  {'work orders w/o SPC':>18}: {len(info['no_spc'])}")
    outcomes: dict[str, int] = {}
    for case in cases:
        outcomes[case["expected_outcome"]] = outcomes.get(case["expected_outcome"], 0) + 1
    print("  expected outcomes:", outcomes)
    print(f"\nDatabase: {DB_PATH}")
    print(f"Docs:     {DOCS_DIR}")
    print(f"Cases:    {EVAL_CASES_PATH}")


if __name__ == "__main__":
    main()
