"""
Regenerates the Markdown report from the most recent (or a specified)
JSON eval result, without re-running ingestion or the pipelines.

Use this whenever run_eval.py's JSON output saved successfully but the
Markdown write step failed (e.g. an encoding error) - no need to burn
another full run (model downloads + ingestion + 2 pipelines x N
questions) just to regenerate a report format.

Usage:
    python eval/regenerate_report.py                # uses the latest report_*.json
    python eval/regenerate_report.py path/to/report_20260920-123456.json
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_eval import RESULTS_DIR, render_markdown  # noqa: E402


def main():
    if len(sys.argv) > 1:
        json_path = Path(sys.argv[1])
    else:
        candidates = sorted(RESULTS_DIR.glob("report_*.json"))
        if not candidates:
            print(f"No report_*.json files found in {RESULTS_DIR}")
            sys.exit(1)
        json_path = candidates[-1]

    print(f"Reading: {json_path}")
    results = json.loads(json_path.read_text(encoding="utf-8"))

    md_path = json_path.with_suffix(".md")
    md_path.write_text(render_markdown(results), encoding="utf-8")
    print(f"Wrote: {md_path}")


if __name__ == "__main__":
    main()