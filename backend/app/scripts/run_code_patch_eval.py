from __future__ import annotations

import argparse
from pathlib import Path

from app.services.code_patch_eval import generate_code_patch_cases, run_code_patch_eval, write_code_patch_eval_report


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "artifacts" / "code_patch_eval"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic code-patch generation evaluations.")
    parser.add_argument("--count", type=int, default=500, help="Number of generated cases to run.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT), help="Directory for latest.json and latest.md reports.")
    args = parser.parse_args()

    cases = generate_code_patch_cases(max(1, args.count))
    results = run_code_patch_eval(cases)
    summary = write_code_patch_eval_report(results, output_dir=Path(args.output_dir).resolve())
    print(
        "code_patch_eval "
        f"total={summary['total']} "
        f"passed={summary['passed']} "
        f"failed={summary['failed']} "
        f"pass_rate={summary['pass_rate']:.1%} "
        f"p95_ms={summary['p95_latency_ms']:.1f}"
    )
    if summary["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
