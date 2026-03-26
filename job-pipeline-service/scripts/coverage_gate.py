import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: python scripts/coverage_gate.py <coverage-json-path> <min-branch-percent>")
        return 2

    report_path = Path(sys.argv[1])
    min_branch = float(sys.argv[2])

    if not report_path.exists():
        print(f"Coverage report not found: {report_path}")
        return 2

    payload = json.loads(report_path.read_text())
    totals = payload.get("totals", {})
    num_branches = totals.get("num_branches", 0) or 0
    covered_branches = totals.get("covered_branches", 0) or 0

    if num_branches == 0:
        print("No branches were recorded in coverage report.")
        return 1

    branch_percent = (covered_branches / num_branches) * 100
    print(f"Branch coverage: {branch_percent:.2f}% ({covered_branches}/{num_branches})")

    if branch_percent < min_branch:
        print(f"Branch coverage gate failed: {branch_percent:.2f}% < {min_branch:.2f}%")
        return 1

    print(f"Branch coverage gate passed: {branch_percent:.2f}% >= {min_branch:.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
