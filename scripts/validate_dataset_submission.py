#!/usr/bin/env python3
"""Validate dataset PR data without executing any code from the candidate branch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rcabench_leaderboard.submission import validate_submissions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True, help="candidate repository checkout")
    parser.add_argument("--base-root", type=Path, required=True, help="trusted base checkout")
    parser.add_argument("--sample-size", type=int, default=3)
    args = parser.parse_args()
    if args.sample_size <= 0 or args.sample_size > 20:
        parser.error("sample-size must be between 1 and 20")
    report = validate_submissions(
        args.root.resolve(), args.base_root.resolve(), sample_size=args.sample_size
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
