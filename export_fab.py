#!/usr/bin/env python3
"""Export JLCPCB-ready Gerbers + drill files for the SMK test board.

Structure copied from ~/esp/SMK_Keyboard/smk_kbd_rp2040/export_fab.py (the
zone-fill / plot-gerbers / write-drill / zip pipeline that ecosystem uses),
adapted to drive kicad-cli instead of KiCad's bundled pcbnew module -- this
board's DRC/export work already runs kicad-cli directly (see
docs/fabrication.md), so staying on one tool avoids needing a second Python
interpreter. Also: this board has no copper pours, so there is nothing to
zone-fill; the check below exists so a future revision that adds a GND pour
doesn't silently ship unfilled zones.

Run with the system/venv Python (this only shells out to kicad-cli, no
pcbnew import needed):
  python3 export_fab.py

kicad-cli location:
  macOS default install: /Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli
  Override with the KICAD_CLI env var if it's elsewhere or already on PATH.

Output: gerbers/ (gitignored) + smk_test_board_gerbers.zip (gitignored,
*.zip) at the repo root -- upload the zip to JLCPCB.
"""
import os
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
BOARD = os.path.join(HERE, "smk_test_board", "smk_test_board.kicad_pcb")
OUT = os.path.join(HERE, "gerbers")
ZIP_PATH = os.path.join(HERE, "smk_test_board_gerbers.zip")

_DEFAULT_MAC_CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
KICAD_CLI = (
    os.environ.get("KICAD_CLI")
    or shutil.which("kicad-cli")
    or (_DEFAULT_MAC_CLI if os.path.exists(_DEFAULT_MAC_CLI) else None)
)
if not KICAD_CLI:
    raise SystemExit(
        "kicad-cli not found on PATH and KICAD_CLI is not set. "
        f"On macOS it's normally at {_DEFAULT_MAC_CLI}."
    )


def run(*args):
    cmd = [KICAD_CLI, *args]
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


if not os.path.isfile(BOARD):
    raise SystemExit(f"board not found: {BOARD}")

os.makedirs(OUT, exist_ok=True)

# 1. Zone-fill check. This is a bare 2-layer board shipped ratsnest-only
# (see docs/fabrication.md) -- there is no GND pour or any other copper
# zone to fill. Fail loudly rather than silently exporting unfilled
# copper if that ever changes; the sibling generator's zone-fill step
# would need porting here too if it does.
with open(BOARD, "r", encoding="utf-8") as f:
    board_text = f.read()
if "(zone " in board_text or "(zone\n" in board_text:
    raise SystemExit(
        "board now has one or more zones -- this script has no zone-fill "
        "step. Port the fill-zones-then-save step from "
        "~/esp/SMK_Keyboard/smk_kbd_rp2040/export_fab.py before exporting."
    )
print("no copper zones on this board -- zone-fill step is a no-op, as expected")

# 2. Gerbers. Layer set matches the RP2040 sibling's export_fab.py minus
# the inner copper layers this board doesn't have (it's 2-layer, not 4).
GERBER_LAYERS = ",".join([
    "F.Cu", "B.Cu",
    "F.Mask", "B.Mask",
    "F.Silkscreen", "B.Silkscreen",
    "F.Paste", "B.Paste",
    "Edge.Cuts",
])
run(
    "pcb", "export", "gerbers",
    "--output", OUT + os.sep,
    "--layers", GERBER_LAYERS,
    "--subtract-soldermask",
    BOARD,
)
print("gerbers plotted")

# 3. Drill files (Excellon, metric, PTH/NPTH split -- the board has both:
# switch/diode/LED/header pads are PTH, the four M2 mounting holes are
# NPTH). Also emit a map + report for JLCPCB's reviewers to cross-check.
run(
    "pcb", "export", "drill",
    "--output", OUT + os.sep,
    "--format", "excellon",
    "--drill-origin", "absolute",
    "--excellon-units", "mm",
    "--excellon-zeros-format", "decimal",
    "--excellon-separate-th",
    "--generate-map",
    "--map-format", "gerberx2",
    "--generate-report",
    "--report-path", os.path.join(OUT, "drill-report.txt"),
    BOARD,
)
print("drill files written")

# 4. Zip for JLCPCB upload.
with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as z:
    for name in sorted(os.listdir(OUT)):
        z.write(os.path.join(OUT, name), name)
print(f"wrote {ZIP_PATH} -- upload this to JLCPCB")
