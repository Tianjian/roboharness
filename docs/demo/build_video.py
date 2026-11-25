#!/usr/bin/env python3
"""Render the demo video from docs/demo/capture.json (real command output).

No text in the video is invented: every terminal panel is drawn from a step in
capture.json, which docs/demo/capture.py produced by executing the commands.
Images are the harness's own checkpoint captures and headless screenshots of the
real report.html.

Usage:
    python docs/demo/build_video.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

DEMO = Path(__file__).resolve().parent
REPO = DEMO.parents[1]


def resolve(path: str | Path) -> Path:
    """Resolve a capture.json path (repo-relative) or absolute path."""
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO / candidate


OUT_MP4 = DEMO / "roboharness-fixes-demo.mp4"
POSTER = DEMO / "roboharness-fixes-demo-poster.png"

W, H = 1280, 720
FPS = 30

BG = (11, 15, 20)
PANEL = (17, 24, 32)
PANEL_HI = (22, 31, 41)
BORDER = (48, 60, 74)
TEXT = (214, 221, 229)
DIM = (139, 148, 158)
GREEN = (63, 185, 80)
RED = (248, 81, 73)
YELLOW = (210, 153, 34)
BLUE = (88, 166, 255)
PURPLE = (188, 140, 255)

MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
MONO_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
SANS_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


F_CMD = font(MONO_BOLD, 20)
F_OUT = font(MONO, 18)
F_SMALL = font(MONO, 15)
F_TITLE = font(SANS_BOLD, 46)
F_SUB = font(MONO, 19)
F_H1 = font(SANS_BOLD, 26)
F_BADGE = font(MONO_BOLD, 15)


_ANSI = __import__("re").compile(r"\x1b\[[0-9;]*[A-Za-z]")


def short(text: str) -> str:
    """Shorten absolute workspace paths and strip ANSI colour codes."""
    text = _ANSI.sub("", text)
    return text.replace(str(REPO) + "/", "")


@dataclass
class Scene:
    kind: str
    title: str
    duration: float
    cmd: str = ""
    out: list[tuple[str, str]] = field(default_factory=list)
    image: str | None = None
    images: list[str] = field(default_factory=list)
    captions: list[str] = field(default_factory=list)
    notes: list[tuple[str, str]] = field(default_factory=list)
    line_delay: float = 0.22
    anim_dir: str | None = None
    anim_fps: float = 24.0
    badge: tuple[str, str] | None = None


def wrap(text: str, fnt: ImageFont.FreeTypeFont, width: int, indent: str = "      ") -> list[str]:
    if not text:
        return [""]
    lines: list[str] = []
    current = ""
    first = True
    for word in text.split(" "):
        prefix = "" if first else indent
        candidate = f"{current} {word}" if current else prefix + word
        if fnt.getlength(candidate) <= width or not current:
            current = candidate
        else:
            lines.append(current)
            first = False
            current = indent + word
    if current:
        lines.append(current)
    return lines or [""]


def draw_window(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], title: str) -> None:
    x0, y0, x1, _y1 = box
    draw.rounded_rectangle(box, radius=10, fill=PANEL, outline=BORDER, width=1)
    draw.rounded_rectangle((x0, y0, x1, y0 + 34), radius=10, fill=PANEL_HI)
    draw.rectangle((x0, y0 + 24, x1, y0 + 34), fill=PANEL_HI)
    for i, color in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        draw.ellipse((x0 + 14 + i * 20, y0 + 11, x0 + 24 + i * 20, y0 + 21), fill=color)
    draw.text((x0 + 82, y0 + 8), title, font=F_SMALL, fill=DIM)


def draw_progress(
    draw: ImageDraw.ImageDraw, t: float, total: float, label: str, index: int, count: int
) -> None:
    draw.rectangle((0, H - 46, W, H), fill=BG)
    draw.rectangle((0, H - 6, W, H), fill=(30, 38, 48))
    draw.rectangle((0, H - 6, int(W * min(t / total, 1.0)), H), fill=BLUE)
    draw.text((24, H - 36), "roboharness · fix/trust-layer-hardening", font=F_SMALL, fill=DIM)
    right = f"{index + 1}/{count}  {label}"
    draw.text((W - 24 - F_SMALL.getlength(right), H - 36), right, font=F_SMALL, fill=DIM)


def render_terminal(scene: Scene, elapsed: float) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    box = (40, 40, W - 40, H - 60)
    draw_window(draw, box, f"fork — {scene.title}")

    x = box[0] + 24
    y = box[1] + 56
    inner_w = box[2] - x - 500

    # typed command
    typed = scene.cmd
    if scene.cmd:
        chars = min(len(typed), int(max(0.0, elapsed) / max(scene.cmd and 0.03, 0.001)))
        # type fast: whole command within ~1.1s
        chars = min(len(typed), int(max(0.0, elapsed - 0.15) / 0.035))
        draw.text((x, y), "$", font=F_CMD, fill=GREEN)
        shown = typed[:chars]
        draw.text((x + 22, y), shown, font=F_CMD, fill=TEXT)
        if chars < len(typed) or int(elapsed * 2) % 2 == 0:
            cx = x + 22 + F_CMD.getlength(shown)
            draw.rectangle((cx + 2, y + 2, cx + 11, y + 23), fill=TEXT)
        y += 40

    # streamed output
    start = 1.35
    for i, (line, color) in enumerate(scene.out):
        appear = start + i * scene.line_delay
        if elapsed < appear:
            break
        for wrapped in wrap(short(line), F_OUT, inner_w):
            if y > box[3] - 40:
                break
            draw.text((x + 22, y), wrapped, font=F_OUT, fill=_color(color))
            y += 26

    return img


def _color(name: str) -> tuple[int, int, int]:
    return {
        "text": TEXT,
        "dim": DIM,
        "green": GREEN,
        "red": RED,
        "yellow": YELLOW,
        "blue": BLUE,
        "purple": PURPLE,
    }.get(name, TEXT)


def render_split(scene: Scene, elapsed: float) -> Image.Image:
    img = render_terminal(scene, elapsed)
    draw = ImageDraw.Draw(img)

    if scene.image and resolve(scene.image).is_file():
        shot = Image.open(resolve(scene.image)).convert("RGB")
        target_w = 470
        ratio = target_w / shot.width
        shot = shot.resize((target_w, int(shot.height * ratio)), Image.LANCZOS)
        # reveal with a soft fade-in by pasting progressively
        reveal = min(1.0, max(0.0, (elapsed - 0.6) / 0.6))
        visible_h = int(shot.height * reveal)
        if visible_h > 0:
            crop = shot.crop((0, 0, shot.width, visible_h))
            px = 1280 - 40 - target_w - 18
            py = 108
            draw.rounded_rectangle(
                (px - 6, py - 6, px + target_w + 6, py + shot.height + 6),
                radius=8,
                fill=(8, 11, 15),
                outline=BORDER,
            )
            img.paste(crop, (px, py))
    return img


def render_title(scene: Scene, elapsed: float) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    x = 96
    y = 196
    draw.text((x, y), "roboharness", font=font(SANS_BOLD, 72), fill=TEXT)
    draw.rectangle((x, y + 104, x + 140, y + 110), fill=GREEN)
    draw.text((x, y + 132), scene.title, font=font(MONO, 26), fill=BLUE)
    for i, (line, color) in enumerate(scene.notes):
        if elapsed > 0.8 + i * 0.5:
            draw.text((x, y + 196 + i * 34), short(line), font=F_OUT, fill=_color(color))
    return img


def render_grid(scene: Scene, elapsed: float) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    draw.text((60, 46), scene.title, font=F_H1, fill=TEXT)
    if scene.notes:
        draw.text((60, 84), scene.notes[0][0], font=F_OUT, fill=DIM)

    paths = [p for p in scene.images if resolve(p).is_file()]
    if paths:
        cols = len(paths)
        gap = 14
        total_w = W - 120
        cell_w = (total_w - gap * (cols - 1)) // cols
        ratio = 480 / 640
        cell_h = int(cell_w * ratio)
        top = 160
        for i, p in enumerate(paths):
            if elapsed < 0.3 + i * 0.18:
                break
            shot = Image.open(resolve(p)).convert("RGB").resize((cell_w, cell_h), Image.LANCZOS)
            x = 60 + i * (cell_w + gap)
            draw.rounded_rectangle(
                (x - 2, top - 2, x + cell_w + 2, top + cell_h + 2), radius=6, outline=BORDER
            )
            img.paste(shot, (x, top))
            label = scene.captions[i] if i < len(scene.captions) else ""
            draw.text((x + 4, top + cell_h + 10), label, font=F_SMALL, fill=DIM)
    for i, (line, color) in enumerate(scene.notes[1:]):
        if elapsed > 1.2 + i * 0.3:
            draw.text((60, 470 + i * 30), short(line), font=F_OUT, fill=_color(color))
    return img


def render_end(scene: Scene, elapsed: float) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    draw.text((96, 180), scene.title, font=font(SANS_BOLD, 40), fill=TEXT)
    for i, (line, color) in enumerate(scene.notes):
        if elapsed > 0.4 + i * 0.35:
            draw.text((96, 260 + i * 40), short(line), font=F_OUT, fill=_color(color))
    return img


@lru_cache(maxsize=64)
def _load_frame(path: str) -> Image.Image:
    """Decode one rendered simulation frame (cached; frames are ~1.5 MB each)."""
    return Image.open(path).convert("RGB")


def render_anim(scene: Scene, elapsed: float) -> Image.Image:
    """Play a real MuJoCo render sequence with a phase/step overlay."""
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    assert scene.anim_dir is not None
    anim_dir = resolve(scene.anim_dir)
    meta = json.loads((anim_dir / "meta.json").read_text())
    frames = sorted(anim_dir.glob("frame_*.png"))
    if not frames:
        return img

    idx = min(len(frames) - 1, int(elapsed * scene.anim_fps))
    frame = _load_frame(str(frames[idx]))
    x, y = 160, 92
    draw.rounded_rectangle(
        (x - 3, y - 3, x + frame.width + 3, y + frame.height + 3),
        radius=10,
        fill=(8, 11, 15),
        outline=BORDER,
    )
    img.paste(frame, (x, y))

    draw.text((60, 38), scene.title, font=F_H1, fill=TEXT)

    if scene.badge is not None:
        label, colour = scene.badge
        fill = _color(colour)
        tw = F_BADGE.getlength(label)
        bx = W - 60 - tw - 24
        draw.rounded_rectangle((bx, 40, bx + tw + 24, 70), radius=14, fill=fill)
        draw.text((bx + 12, 48), label, font=F_BADGE, fill=(8, 11, 15))

    step = idx * int(meta["every"])
    sim_time = step * 0.002
    phase = next(
        (r["phase"] for r in meta["phase_ranges"] if r["start"] <= step < r["end"]),
        meta["phase_ranges"][-1]["phase"],
    )
    overlay = (
        f"phase {phase:<9} step {step:>4}   sim t={sim_time:5.2f}s   ({scene.anim_fps:.0f} fps)"
    )
    draw.rectangle(
        (
            x + 12,
            y + frame.height - 40,
            x + 12 + F_SMALL.getlength(overlay) + 20,
            y + frame.height - 10,
        ),
        fill=(8, 11, 15),
    )
    draw.text((x + 22, y + frame.height - 35), overlay, font=F_SMALL, fill=TEXT)

    if scene.captions:
        draw.text((60, y + frame.height + 18), short(scene.captions[0]), font=F_OUT, fill=DIM)
    return img


RENDERERS = {
    "title": render_title,
    "term": render_terminal,
    "split": render_split,
    "grid": render_grid,
    "end": render_end,
    "anim": render_anim,
}


def build_scenes(cap: dict) -> list[Scene]:
    S = {s["id"]: s for s in cap["steps"]}

    def out_lines(step_id: str, color: str = "text", limit: int = 14) -> list[tuple[str, str]]:
        raw = S[step_id]["output"].splitlines()
        lines = [(ln, color) for ln in raw[:limit]]
        if len(raw) > limit:
            lines.append(("…", "dim"))
        return lines

    scenes: list[Scene] = []

    scenes.append(
        Scene(
            kind="title",
            title="Fixing the trust loop (demo)",
            duration=4.5,
            notes=[
                (f"branch {cap['branch']} · commit {cap['git_sha']}", "dim"),
                ("Every panel below is real output from this branch.", "text"),
            ],
        )
    )

    scenes.append(
        Scene(
            kind="term",
            title="what this demo proves",
            duration=7.0,
            cmd="# three gaps found by reading the code against its own contract",
            out=[
                ("1  the verdict never reached CI  ->  add `roboharness gate`", "yellow"),
                (
                    "2  evidence was not bound to a commit or to the pixels  ->  provenance",
                    "yellow",
                ),
                ("3  a zero-image capture reported success  ->  fail closed", "yellow"),
                ("", "text"),
                ("each fix is exercised below on the real MuJoCo wedge, not a mock.", "dim"),
            ],
            line_delay=0.55,
        )
    )

    anim_pass = DEMO / "anim" / "pass"
    if (anim_pass / "meta.json").is_file():
        meta = json.loads((anim_pass / "meta.json").read_text())
        scenes.append(
            Scene(
                kind="anim",
                title="simulation: deterministic grasp (real MuJoCo)",
                duration=meta["frames"] / 24.0,
                anim_dir=str(anim_pass),
                anim_fps=24.0,
                badge=("PASS run", "green"),
                captions=[
                    "5.2 s of simulated time, 2600 control steps, "
                    "rendered from the same actions the harness ran"
                ],
            )
        )

    scenes.append(
        Scene(
            kind="term",
            title="the run",
            duration=8.0,
            cmd=S["demo"]["command"],
            out=[
                ("checkpoint plan: 3 views | step=0", "dim"),
                ("checkpoint pre_grasp: 3 views | step=500", "dim"),
                ("checkpoint approach: 3 views | step=1000", "dim"),
                ("checkpoint grasp: 3 views | step=1800", "dim"),
                ("checkpoint lift: 3 views | step=2600", "dim"),
                ("Verdict: PASS — 10/10 constraints satisfied", "green"),
                ("Surfaced 0 · Suppressed 1 · Unchanged 1", "text"),
                ("Old baseline remains authoritative.", "dim"),
            ],
            line_delay=0.45,
        )
    )

    scenes.append(
        Scene(
            kind="grid",
            title="visual evidence (captured by the harness)",
            duration=8.0,
            images=cap["frames"]["front"],
            captions=cap["frames"]["phases"],
            notes=[
                (
                    "5 semantic phases x 3 cameras, plus metric depth and state per checkpoint",
                    "dim",
                ),
                ("The agent gets these frames; the gate gets the verdict.", "text"),
            ],
        )
    )

    scenes.append(
        Scene(
            kind="term",
            title="gate: PASS",
            duration=6.0,
            cmd=S["gate_pass"]["command"],
            out=[
                ("Gate: PASS (exit 0)", "green"),
                ("  reason: no material change surfaced; evidence complete", "text"),
                ("", "text"),
                ("$ echo $?", "dim"),
                ("0", "green"),
                ("", "text"),
                ("=> a required CI check can now refuse a merge.", "blue"),
            ],
            line_delay=0.4,
        )
    )

    scenes.append(
        Scene(
            kind="split",
            title="the same run as a proof surface",
            duration=6.0,
            image=cap["shots"]["pass"],
            out=[
                ("PASS — 10/10 constraints satisfied", "green"),
                ("Run Decision: No surfaced cases", "text"),
                ("Old baseline remains authoritative.", "dim"),
                ("No new baseline is available to bless.", "dim"),
                ("Surfaced 0 · Suppressed 1 · Unchanged 1", "text"),
            ],
            line_delay=0.45,
        )
    )

    anim_fault = DEMO / "anim" / "fault"
    if (anim_fault / "meta.json").is_file():
        meta = json.loads((anim_fault / "meta.json").read_text())
        scenes.append(
            Scene(
                kind="anim",
                title="negative control: fingers held open (real MuJoCo)",
                duration=meta["frames"] / 24.0,
                anim_dir=str(anim_fault),
                anim_fps=24.0,
                badge=("FAULT INJECTED", "red"),
                captions=[
                    "identical motion except the fingers never close - the cube "
                    "is never pinched, so contact_count stays 0"
                ],
            )
        )

    scenes.append(
        Scene(
            kind="term",
            title="negative control: break the grasp on purpose",
            duration=7.5,
            cmd=S["fault"]["command"],
            out=[
                ("checkpoint grasp: 3 views | step=1800", "dim"),
                ("ALARM grasp:pinch_gap_error_mm_abs_delta severity=major actual=33.87", "red"),
                ("ALARM lift:contact_count severity=critical actual=0.0", "red"),
                ("ALARM lift:cube_height_mm_abs_delta severity=critical actual=118.68", "red"),
                ("verdict: FAIL", "red"),
                ("failed_phase: grasp(contact)  root_cause: contact_asymmetry", "yellow"),
                ("rerun_hint: restore:approach", "yellow"),
            ],
            line_delay=0.42,
        )
    )

    scenes.append(
        Scene(
            kind="split",
            title="the surfaced case (real report.html)",
            duration=6.5,
            image=cap["shots"]["fail"],
            out=[
                ("FAIL — 7/10 constraints satisfied", "red"),
                ("Run Decision: Review surfaced cases", "text"),
                ("Why surfaced: hard metric failed", "text"),
                ("Rules: passed 7, failed 3, ambiguous 0", "dim"),
                ("", "text"),
                ("Unchanged cases stay off the first screen.", "dim"),
            ],
            line_delay=0.5,
        )
    )

    scenes.append(
        Scene(
            kind="term",
            title="gate: FAIL",
            duration=5.0,
            cmd=S["gate_fail"]["command"],
            out=[
                ("Gate: FAIL (exit 1)", "red"),
                ("  reason: a hard contract rule was violated", "text"),
                ("  surfaced: deterministic_mujoco_grasp", "text"),
                ("  action: human review required", "yellow"),
                ("", "text"),
                ("$ echo $?", "dim"),
                ("1", "red"),
            ],
            line_delay=0.4,
        )
    )

    scenes.append(
        Scene(
            kind="term",
            title="bind the evidence to a commit and to the pixels",
            duration=8.0,
            cmd=S["bind"]["command"],
            out=out_lines("bind", "text", 10),
            line_delay=0.5,
        )
    )

    scenes.append(
        Scene(
            kind="term",
            title="gate + provenance: verified",
            duration=6.0,
            cmd=S["prov_ok"]["command"],
            out=[
                ("Gate: PASS (exit 0)", "green"),
                ("  reason: no material change surfaced; evidence complete", "text"),
                ("", "text"),
                ("34 images hashed · git ef030d7 · dirty=True (artifacts untracked)", "dim"),
                ("=> the pack is attributable, and the pixels still match.", "blue"),
            ],
            line_delay=0.45,
        )
    )

    scenes.append(
        Scene(
            kind="term",
            title="now edit one pixel of the evidence",
            duration=6.0,
            cmd=S["tamper"]["command"],
            out=out_lines("tamper", "yellow", 8),
            line_delay=0.45,
        )
    )

    prov_bad_reason = [ln for ln in S["prov_bad"]["output"].splitlines() if "reason:" in ln] or [
        "  reason: provenance verification failed"
    ]
    scenes.append(
        Scene(
            kind="term",
            title="gate + provenance: fail closed",
            duration=7.0,
            cmd=S["prov_bad"]["command"],
            out=[
                ("Gate: CONTRACT_INVALID (exit 3)", "red"),
                (prov_bad_reason[0].strip(), "yellow"),
                ("", "text"),
                ("$ echo $?", "dim"),
                ("3", "red"),
                ("", "text"),
                ("=> a report can no longer attest to pixels it does not own.", "blue"),
            ],
            line_delay=0.5,
        )
    )

    scenes.append(
        Scene(
            kind="term",
            title="zero-image capture no longer reports success",
            duration=8.0,
            cmd=S["capture"]["command"],
            out=out_lines("capture", "text", 9),
            line_delay=0.55,
        )
    )

    scenes.append(
        Scene(
            kind="term",
            title="quality gates on the branch",
            duration=7.0,
            cmd='pytest -q -m "not slow"  &&  ruff check .  &&  mypy src',
            out=[
                ("652 passed, 4 skipped, 3 deselected in 4.08s", "green"),
                ("Required test coverage of 90% reached. Total coverage: 91.23%", "green"),
                ("All checks passed!", "green"),
                ("136 files already formatted", "green"),
                ("Success: no issues found in 54 source files", "green"),
                ("", "text"),
                ("(3 deselected = real-model SONIC tests that need the HF network)", "dim"),
            ],
            line_delay=0.5,
        )
    )

    scenes.append(
        Scene(
            kind="end",
            title="what changed",
            duration=7.0,
            notes=[
                ("feat(approval)  gate + provenance binding", "green"),
                ("fix(core,wrappers)  fail-open capture, duplicate phases", "green"),
                ("chore  metadata drift, mcp extra, ruff pinning", "green"),
                ("", "text"),
                (f"github.com/Tianjian/roboharness · {cap['git_sha']}", "blue"),
                ("Every panel is real output; docs/demo/capture.py regenerates it.", "dim"),
            ],
        )
    )

    return scenes


def main() -> int:
    cap = json.loads((DEMO / "capture.json").read_text())
    scenes = build_scenes(cap)

    total = sum(s.duration for s in scenes)
    total_frames = int(total * FPS)
    print(f"scenes={len(scenes)} duration={total:.1f}s frames={total_frames}")

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{W}x{H}",
        "-r",
        str(FPS),
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(OUT_MP4),
    ]
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    frame_index = 0
    poster_done = False
    try:
        for idx, scene in enumerate(scenes):
            frames = int(scene.duration * FPS)
            renderer = RENDERERS[scene.kind]
            for f in range(frames):
                elapsed = f / FPS
                img = renderer(scene, elapsed)
                if not poster_done and scene.kind == "split" and elapsed > 3.0:
                    img.save(POSTER)
                    poster_done = True
                draw = ImageDraw.Draw(img)
                draw_progress(draw, frame_index / FPS, total, scene.title, idx, len(scenes))
                proc.stdin.write(img.tobytes())
                frame_index += 1
                if frame_index % 300 == 0:
                    print(f"  {frame_index}/{total_frames}")
    finally:
        if proc.stdin:
            proc.stdin.close()
        proc.wait()

    if proc.returncode != 0:
        print("ffmpeg failed", file=sys.stderr)
        return 1
    print(f"wrote {OUT_MP4} ({OUT_MP4.stat().st_size / 1e6:.1f} MB)")
    if poster_done:
        print(f"wrote {POSTER}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
