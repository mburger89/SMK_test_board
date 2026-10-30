#!/usr/bin/env python3
"""Export JLCPCB-ready Gerbers + drill files for the SMK test board.

Structure copied from ~/esp/SMK_Keyboard/smk_kbd_rp2040/export_fab.py (the
zone-fill / plot-gerbers / write-drill / zip pipeline that ecosystem uses),
adapted to drive kicad-cli instead of KiCad's bundled pcbnew module -- this
board's DRC/export work already runs kicad-cli directly (see
docs/fabrication.md), so staying on one tool avoids needing a second Python
interpreter.

Zone fill: the board carries GND pours on both copper layers, and the
generated .kicad_pcb deliberately stores them as OUTLINES ONLY -- see
router.gnd_zones() for why (a baked-in fill is KiCad-version-dependent
derived geometry and would break the byte-identical regeneration
guarantee). The fill is therefore computed here, at export time, by
`--check-zones`. Without that flag the pours would plot as empty and the
board would ship with no ground plane at all.

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

# 1. Sanity-check the copper the board is supposed to have. This used to
# assert the OPPOSITE -- that the board carried no zones at all -- back
# when it shipped ratsnest-only. It is now routed, with a GND pour per
# copper layer, so the check is inverted: a board that has lost its pours
# or its tracks is the failure worth catching, because both would export
# without complaint and arrive as unusable bare copper.
with open(BOARD, "r", encoding="utf-8") as f:
    board_text = f.read()
for layer in ("F.Cu", "B.Cu"):
    if f'(net_name "GND") (layer "{layer}")' not in board_text:
        raise SystemExit(
            f"board has no GND pour on {layer} -- expected one per copper "
            "layer (see router.gnd_zones). Regenerate with "
            "generate_test_board.py before exporting."
        )
if "(segment " not in board_text:
    raise SystemExit(
        "board carries no tracks. It is meant to be fully routed; "
        "regenerate with generate_test_board.py before exporting."
    )
if "(filled_polygon" in board_text:
    raise SystemExit(
        "board carries baked-in zone fill. The generated board must hold "
        "zone OUTLINES only -- someone has saved it from the KiCad GUI "
        "over the generated file. Regenerate before exporting."
    )
n_seg = board_text.count("(segment ")
n_via = board_text.count("(via (at ")
print(f"routed board: {n_seg} tracks, {n_via} vias, GND pour on both layers")

# 2. Gerbers. Layer set matches the RP2040 sibling's export_fab.py minus
# the inner copper layers this board doesn't have (it's 2-layer, not 4).
GERBER_LAYERS = ",".join([
    "F.Cu", "B.Cu",
    "F.Mask", "B.Mask",
    "F.Silkscreen", "B.Silkscreen",
    "F.Paste", "B.Paste",
    "Edge.Cuts",
])
# --check-zones is load-bearing, not a nicety: the pours ship unfilled (see
# the module docstring), so without it both ground planes plot as nothing.
run(
    "pcb", "export", "gerbers",
    "--output", OUT + os.sep,
    "--layers", GERBER_LAYERS,
    "--subtract-soldermask",
    "--check-zones",
    BOARD,
)
print("gerbers plotted (zones refilled at export time)")

# 3. Drill files (Excellon, metric, PTH/NPTH split -- the board has both).
#
# PTH: the 14 XIAO header pads (U1), the EC11's 5 signal pins (ENC1), and the
# 2 battery flying-lead pads (J2) -- 21 plated holes. The switch, diode and
# LED pads are all SMD and drill nothing; an earlier version of this comment
# said "switch/diode/LED/header pads are PTH", which is wrong for three of
# those four.
#
# NPTH: 30 unplated holes -- the four M2 corner mounting holes (2.4mm,
# gm.fp_hole), the EC11's two 3.2mm mounting-post legs, and the Gateron
# hot-swap sockets' own mechanical holes (one 5.2mm centre plus two 3.0mm
# switch-leg holes per socket, x8 sockets = 24). Cross-check against
# gerbers/drill-report.txt after every export: 21 plated / 30 unplated.
#
# Neither count includes the nine SK6812MINI-E light windows: those are milled
# Edge.Cuts slots, not drilled holes, and they leave the board on the
# Edge_Cuts gerber rather than in either drill file. If a future revision ever
# shows an empty/near-empty Edge_Cuts layer, the LEDs have lost their windows.
#
# Also emit a map + report for JLCPCB's reviewers to cross-check.
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
