#!/usr/bin/env python3
"""Bind provenance to a real approval report and its checkpoint images.

Demonstrates the public API. `roboharness proof-pack --provenance` performs the
same binding during pack assembly; this script is used because the wedge trial
directory does not carry a renderer manifest for the pack builder to discover.

Usage:
    python docs/demo/bind_provenance.py <case_dir> <out.json>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from roboharness.approval.provenance import attach_provenance, collect_provenance


def main() -> int:
    case_dir = Path(sys.argv[1]).resolve()
    out_path = Path(sys.argv[2]).resolve()
    report_path = case_dir / "approval_report.json"
    if not report_path.is_file():
        raise SystemExit(f"no approval_report.json in {case_dir}")

    document = json.loads(report_path.read_text())
    images = sorted(case_dir.rglob("*.png"))
    provenance = collect_provenance(case_dir, images)
    bound = attach_provenance(document, provenance)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(bound, indent=2))

    git = provenance.get("git") or {}
    print(f"bound {len(provenance['artifacts'])} image(s) to git {git.get('sha', 'n/a')[:12]}")
    print(
        f"branch={git.get('branch', 'n/a')} dirty={git.get('dirty', 'n/a')} "
        "(run artifacts are untracked)"
    )
    first = provenance["artifacts"][0]
    print(f"hash[0]={first['path']} sha256={first['sha256'][:16]}...")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
