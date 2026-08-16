#!/usr/bin/env python3
"""SMK Test Board -- 3x3 macropad on a Seeed XIAO ESP32-C6.

Hardware for validating the parts of SMK that have never met a board: the
matrix path on a C6, the RMT LED driver, and BatteryMonitor. See
docs/superpowers/specs/2026-08-16-smk-test-board-design.md.

Like its siblings in ~/esp/SMK_macro_pad, the .kicad_sch/.kicad_pcb this
writes are BUILD ARTIFACTS. Edit this file and re-run; never hand-edit the
outputs. Never run KiCad's "Update Footprints from Library" on the result.

The geometry and s-expression helpers come from generate_macropad.py in the
sibling repo rather than being forked -- that module's own docstring records
what forking cost the last time.

WHAT IS UNVERIFIED
  The XIAO ESP32-C6 and EC11 footprints are drawn here for the first time
  (Tasks 3 and 4) and have never been fabricated. Print at 1:1 and check
  against physical parts before ordering.
  SK6812MINI-E runs from VSYS (3.0-4.2V on battery); its datasheet minimum
  is 3.7V, so the LEDs may misbehave on a low cell. Inherited from the part
  choice, not a defect here.
"""
import os
import sys

_SIBLING = os.path.expanduser("~/esp/SMK_macro_pad")
if not os.path.isdir(_SIBLING):
    raise SystemExit(
        f"sibling generator not found at {_SIBLING}\n"
        "This project reuses generate_macropad.py's helpers rather than "
        "forking them; clone ~/esp/SMK_macro_pad next to this repo."
    )
sys.path.insert(0, _SIBLING)
import generate_macropad as gm  # noqa: E402

PROJ = "smk_test_board"
PRJDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), PROJ)

ROWS = 3
COLS = 3
LED_COUNT = ROWS * COLS
KEY_PITCH = 19.05

# Origin of the key field on the board, in mm.
KEY_X0 = 25.0
KEY_Y0 = 25.0

# The contract with ~/esp/SMK's board config and the configurator's
# KeyboardDesign. All three must agree; see the spec's section 1.
PIN = {
    "ROW0": 1, "ROW1": 2, "ROW2": 21,
    "COL0": 22, "COL1": 23, "COL2": 16,
    "ENC_A": 17, "ENC_B": 19,
    "LED_DATA": 20,
    "VBAT_SENSE": 0,
    "SPARE": 18,
}


def key_xy(r, c):
    """Centre of the key at (row, col), in board mm."""
    return (KEY_X0 + c * KEY_PITCH, KEY_Y0 + r * KEY_PITCH)


def main():
    os.makedirs(PRJDIR, exist_ok=True)
    raise SystemExit("build_sch()/build_pcb() not implemented yet")


if __name__ == "__main__":
    main()
