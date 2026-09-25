"""Regression gate: compare a benchmark JSON against a baseline with
thresholds; non-zero exit fails CI. Usage:

    python -m researchops.evals.regression results/current.json --baseline results/baseline.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# metric -> maximum allowed absolute regression vs baseline
THRESHOLDS = {
    "task_success_rate": 0.05,
    "tool_selection_accuracy": 0.05,
    "tool_execution_success": 0.05,
    "citation_precision": 0.05,
    "recovery_rate": 0.10,
}


def compare(current: dict, baseline: dict) -> list[str]:
    failures: list[str] = []
    cur, base = current["summary"], baseline["summary"]
    for metric, threshold in THRESHOLDS.items():
        drop = base.get(metric, 0) - cur.get(metric, 0)
        if drop > threshold:
            failures.append(f"{metric}: {base.get(metric, 0):.3f} → {cur.get(metric, 0):.3f} (regression {drop:.3f} > {threshold})")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("current")
    parser.add_argument("--baseline", required=True)
    args = parser.parse_args()
    current = json.loads(Path(args.current).read_text())
    baseline = json.loads(Path(args.baseline).read_text())
    failures = compare(current, baseline)
    if failures:
        print("REGRESSION DETECTED:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("no regression beyond thresholds ✓")


if __name__ == "__main__":
    main()
