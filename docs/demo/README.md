# Demo video (for human review)

`roboharness-fixes-demo.mp4` — 129 s, 1280×720, H.264. It shows the three fixes on
the `fix/trust-layer-hardening` branch **with the real MuJoCo simulation running**,
and ends with the quality gates.

**Nothing in the video is invented.**

- The simulation panels are frames rendered from MuJoCo with the same scripted
  actions the harness executes (`docs/demo/render_anim.py`), with a phase/step/sim-time
  overlay. The fault clip is the same motion with the fingers held open.
- The terminal panels are rendered from `docs/demo/capture.json`, produced by actually
  executing each command (`docs/demo/capture.py`).
- The report images are headless-Firefox screenshots of the real `report.html`.

## Timeline

| Time | Scene | What it shows |
|---|---|---|
| 0:00 | Title | branch + commit stamp |
| 0:04 | What this demo proves | the three gaps being fixed |
| **0:11** | **Simulation: deterministic grasp** | real MuJoCo: descend → grasp → lift, phase/step overlay |
| 0:22 | The run | harness output → PASS 10/10 |
| 0:30 | Visual evidence | 5 phases × 3 cameras captured by the harness |
| 0:38 | Gate PASS | `roboharness gate …` → exit 0 |
| 0:44 | Proof surface | the real `report.html` first screen (PASS) |
| **0:50** | **Simulation: fingers held open** | same motion, no pinch — cube stays on the table |
| 1:01 | Negative control | critical alarms, first failing phase |
| 1:08 | Proof surface | same report (FAIL) with the surfaced case |
| 1:15 | Gate FAIL | `roboharness gate …` → exit 1 |
| 1:20 | Bind provenance | 34 images hashed against the commit |
| 1:28 | Gate + provenance | verified → exit 0 |
| 1:34 | Tamper | one pixel changed, image re-exported |
| 1:40 | Gate + provenance | hash mismatch → `CONTRACT_INVALID`, exit 3 |
| 1:47 | Zero-image capture | `capture_failed` recorded; `strict_capture=True` raises |
| 1:55 | Quality gates | 653 passed, 91.23% coverage, ruff/format/mypy clean |
| 2:02 | What changed | the three commits |

## Regenerate

```bash
# from the repository root, with the demo extra installed
python docs/demo/capture.py          # runs the commands -> capture.json + report screenshots
MUJOCO_GL=egl python docs/demo/render_anim.py --out docs/demo/anim/pass
MUJOCO_GL=egl python docs/demo/render_anim.py --out docs/demo/anim/fault --defect open_gripper
python docs/demo/build_video.py      # frames -> ffmpeg -> mp4
```

Requires: `python -m pip install -e ".[demo]"` plus `pygame` (Gymnasium
classic-control), `ffmpeg`, and Firefox for the report screenshots. `anim/` holds
the rendered frame sequences (~47 MB) and is gitignored, so `build_video.py` can
be re-run without re-simulating; it is not needed to view the committed mp4.

## Files

- `docs/demo/render_anim.py` — renders the simulation frame sequences (`--defect open_gripper` for the fault clip)
- `docs/demo/capture.py` — executes the 12 terminal steps and records real stdout/exit codes
- `docs/demo/capture_probe.py` — zero-image checkpoint probe (before/after behaviour)
- `docs/demo/bind_provenance.py` — binds provenance to the real evidence via the public API
- `docs/demo/tamper.py` — changes one pixel of a bound image
- `docs/demo/fault_demo.py` — fault-injected twin of the shipped demo (gripper never closes)
- `docs/demo/build_video.py` — frame renderer (PIL) + ffmpeg encode
- `docs/demo/capture.json` — the recorded command outputs
- `anim/{pass,fault}/` — simulation frames + `meta.json` (phase ranges, step count)
- `shot_pass.png`, `shot_fail.png` — headless screenshots of the real reports
- `roboharness-fixes-demo-poster.png` — thumbnail
