#!/usr/bin/env python3
"""Re-export one bound checkpoint image, changing its pixels.

Simulates the realistic failure the provenance binding exists to catch: the
evidence was edited (or regenerated) after the pack was assembled, so the report
still claims the old commit while the pixels are no longer from that run.

Usage:
    python docs/demo/tamper.py <case_dir>
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


def main() -> int:
    case_dir = Path(sys.argv[1]).resolve()
    targets = sorted(case_dir.rglob("lift/front_rgb.png")) or sorted(case_dir.rglob("*.png"))
    if not targets:
        raise SystemExit(f"no PNGs under {case_dir}")
    target = targets[0]

    before = target.stat().st_size
    image = Image.open(target).convert("RGB")
    pixels = image.load()
    red, green, blue = pixels[0, 0]
    pixels[0, 0] = (red ^ 0x01, green, blue)
    image.save(target)

    print(f"re-exported {target.relative_to(case_dir)}")
    print(f"  one pixel changed at (0, 0): {(red, green, blue)} -> {pixels[0, 0]}")
    print(f"  bytes {before} -> {target.stat().st_size} (same image, different sha256)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
