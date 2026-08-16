# SMK Test Board Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a fabricable 3×3 macropad PCB around the Seeed XIAO ESP32-C6, plus the firmware board config and configurator design it needs, so the untested parts of SMK (matrix on C6, RMT LED driver, BatteryMonitor) can finally be exercised on hardware.

**Architecture:** The board is *generated*, not drawn: a Python script emits KiCad s-expressions, following `~/esp/SMK_macro_pad/generate_macropad.py`, which this project imports for its geometry and s-expression helpers rather than forking. Footprints are copied from the sibling `kbd.pretty` into a local library, with only the XIAO and EC11 drawn fresh. A pytest suite asserts geometric properties (clearance, overlap, connectivity) the way `test_macropad_mini.py` does.

**Tech Stack:** Python 3, KiCad 8 file format (read natively by KiCad 9/10), `kicad-cli` for DRC and fabrication output, pytest. Firmware side: ESP-IDF + Embedded Swift. App side: Swift 6 / SwiftPM.

**Spec:** `docs/superpowers/specs/2026-08-16-smk-test-board-design.md`

## Global Constraints

- **Three repos.** Hardware: `~/esp/SMK_test_board`. Firmware: `~/esp/SMK`. App: `~/esp/smk_configurator`. Every task names its repo; never run one repo's tooling in another.
- **Pin map is fixed by the spec and must be used verbatim.** ROW0–2 = GPIO 1, 2, 21. COL0–2 = GPIO 22, 23, 16. Encoder A/B = GPIO 17, 19. LED data = GPIO 20. VBAT sense = GPIO 0 (ADC1_CH0). Spare = GPIO 18.
- **`colsAreDriven = 1`** — columns strobed push-pull, rows sensed with pull-downs. Diodes **anode to column, cathode to row**.
- **9 matrix positions, 9 LEDs.** `RGBLighting(gpioNum:rowCount:colCount:)` allocates exactly `rowCount × colCount` LEDs, so the chain length and the matrix size are the same number and must not drift apart.
- **LEDs run from VSYS (the XIAO BAT pad), never from 3.3 V.** SK6812MINI-E specifies VDD 3.7–5.5 V. A level shifter drives DIN.
- **The `.kicad_sch`/`.kicad_pcb` are build artifacts.** Never hand-edit them; change the generator and re-run. Never run KiCad's "Update Footprints from Library" on this project — the sibling's docstring explains why it silently un-flips back-side parts.
- **KiCad 8 output format**, matching the sibling projects.
- Python: run generator and tests from the repo root so `import generate_macropad` resolves via the sibling path shim in Task 2.
- Commit messages follow each repo's existing style and end with the `Co-Authored-By:` trailer that repo's history uses.

---

## Part A — Hardware (`~/esp/SMK_test_board`)

### Task 1: Local footprint library from the proven set

**Files:**
- Create: `smk_test_board.pretty/` (copies of 6 footprints)
- Create: `test_footprints.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a local footprint library at `smk_test_board.pretty/` containing `SW_Gateron_KS33_HS`, `SK6812MINI_E`, `D_SOD-123_Back`, `RC_0603`, `MountingHole_M2`, `JST_SH_SM02B_2pin_Back`, each referenced later as `smk_test_board:<name>`.

- [ ] **Step 1: Write the failing test**

Create `test_footprints.py`:

```python
#!/usr/bin/env python3
"""Every footprint this board uses must parse and carry the pads we expect.

A footprint that silently loses pads (a bad copy, a truncated file) produces
a board that fabricates fine and cannot be assembled, so this asserts pad
counts rather than mere existence.
"""
import os
import re

LIB = os.path.join(os.path.dirname(__file__), "smk_test_board.pretty")

# name -> minimum pad count
EXPECTED = {
    "SW_Gateron_KS33_HS": 2,   # hot-swap socket: two switch contacts
    "SK6812MINI_E": 4,         # VDD, GND, DIN, DOUT
    "D_SOD-123_Back": 2,
    "RC_0603": 2,
    "MountingHole_M2": 0,
    "JST_SH_SM02B_2pin_Back": 2,
}


def _balanced(text):
    depth = 0
    in_str = False
    for ch in text:
        if ch == '"':
            in_str = not in_str
        elif not in_str:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                assert depth >= 0, "negative paren depth"
    return depth


def test_every_footprint_parses_and_has_pads():
    for name, min_pads in EXPECTED.items():
        path = os.path.join(LIB, f"{name}.kicad_mod")
        assert os.path.exists(path), f"missing footprint: {path}"
        text = open(path).read()
        assert _balanced(text) == 0, f"unbalanced parens in {name}"
        pads = len(re.findall(r"\(pad ", text))
        assert pads >= min_pads, f"{name}: {pads} pads, expected >= {min_pads}"
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd ~/esp/SMK_test_board && python3 -m pytest test_footprints.py -q
```

Expected: FAIL — `missing footprint: .../smk_test_board.pretty/SW_Gateron_KS33_HS.kicad_mod`.

- [ ] **Step 3: Copy the proven footprints**

```bash
cd ~/esp/SMK_test_board && mkdir -p smk_test_board.pretty
SRC=~/esp/SMK_macro_pad/smk_macropad_mini/kbd.pretty
for f in SW_Gateron_KS33_HS D_SOD-123_Back RC_0603 MountingHole_M2 JST_SH_SM02B_2pin_Back; do
  cp "$SRC/$f.kicad_mod" smk_test_board.pretty/
done
cp ~/esp/SMK_Keyboard/smk_kbd_rp2040/kbd.pretty/SK6812MINI_E.kicad_mod smk_test_board.pretty/
ls smk_test_board.pretty/
```

If `SK6812MINI_E.kicad_mod` is not at that path, find it with
`find ~/esp -name 'SK6812MINI_E.kicad_mod'` and copy from there — it is used
by the keyboard project, so it exists somewhere in these repos.

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd ~/esp/SMK_test_board && python3 -m pytest test_footprints.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/esp/SMK_test_board
git add smk_test_board.pretty test_footprints.py
git commit -m "Copy the proven footprints into a local library"
```

---

### Task 2: Generator skeleton importing the sibling helpers

**Files:**
- Create: `generate_test_board.py`
- Create: `test_test_board.py`

**Interfaces:**
- Consumes: `~/esp/SMK_macro_pad/generate_macropad.py`, imported as `gm`.
- Produces: module-level constants `PROJ = "smk_test_board"`, `PRJDIR`, `ROWS = 3`, `COLS = 3`, `KEY_PITCH = 19.05`, `PIN` (dict of net name → GPIO number), and `key_xy(r, c) -> (x, y)`.

- [ ] **Step 1: Write the failing test**

Create `test_test_board.py`:

```python
#!/usr/bin/env python3
import generate_test_board as tb


def test_pin_map_matches_spec():
    # These GPIO numbers are the contract with the firmware's board config
    # and the configurator's KeyboardDesign. Changing one without the others
    # produces a board that scans the wrong pins.
    assert tb.PIN["ROW0"] == 1
    assert tb.PIN["ROW1"] == 2
    assert tb.PIN["ROW2"] == 21
    assert tb.PIN["COL0"] == 22
    assert tb.PIN["COL1"] == 23
    assert tb.PIN["COL2"] == 16
    assert tb.PIN["ENC_A"] == 17
    assert tb.PIN["ENC_B"] == 19
    assert tb.PIN["LED_DATA"] == 20
    assert tb.PIN["VBAT_SENSE"] == 0


def test_matrix_is_square_and_matches_led_count():
    # RGBLighting allocates rowCount * colCount LEDs; the chain length and
    # the matrix size are the same number by construction.
    assert tb.ROWS == 3 and tb.COLS == 3
    assert tb.LED_COUNT == tb.ROWS * tb.COLS


def test_key_grid_pitch():
    x0, y0 = tb.key_xy(0, 0)
    x1, _ = tb.key_xy(0, 1)
    _, y1 = tb.key_xy(1, 0)
    assert abs((x1 - x0) - tb.KEY_PITCH) < 1e-6
    assert abs((y1 - y0) - tb.KEY_PITCH) < 1e-6
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd ~/esp/SMK_test_board && python3 -m pytest test_test_board.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'generate_test_board'`.

- [ ] **Step 3: Write the skeleton**

Create `generate_test_board.py`:

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd ~/esp/SMK_test_board && python3 -m pytest test_test_board.py -q
```

Expected: PASS, 3 tests.

- [ ] **Step 5: Commit**

```bash
cd ~/esp/SMK_test_board
git add generate_test_board.py test_test_board.py
git commit -m "Add the generator skeleton and pin-map contract tests"
```

---

### Task 3: XIAO ESP32-C6 footprint

**Files:**
- Create: `smk_test_board.pretty/XIAO_ESP32C6_HEADERS.kicad_mod`
- Modify: `test_footprints.py` (add the new entry to `EXPECTED`)

**Interfaces:**
- Consumes: nothing.
- Produces: footprint `smk_test_board:XIAO_ESP32C6_HEADERS` — two 1×7 through-hole rows, 2.54 mm pitch, rows 17.78 mm apart, pads numbered 1–14 with pad 1 = D0 and pad 14 = 5V, matching the XIAO silkscreen order.

- [ ] **Step 1: Add the failing expectation**

In `test_footprints.py`, add to `EXPECTED`:

```python
    "XIAO_ESP32C6_HEADERS": 14,   # 2 x 1x7, 2.54mm pitch
```

and add this test to the same file:

```python
def test_xiao_header_geometry():
    """Two 1x7 rows on a 2.54mm pitch, 17.78mm apart.

    Wrong pitch or row spacing means the XIAO does not seat, which is only
    discoverable after fabrication -- hence checking it here.
    """
    text = open(os.path.join(LIB, "XIAO_ESP32C6_HEADERS.kicad_mod")).read()
    ats = [(float(m.group(1)), float(m.group(2)))
           for m in re.finditer(r"\(at (-?[\d.]+) (-?[\d.]+)\)", text)]
    xs = sorted({round(x, 2) for x, _ in ats})
    ys = sorted({round(y, 2) for _, y in ats})
    assert len(xs) == 2, f"expected 2 pad columns, got {xs}"
    assert abs((xs[1] - xs[0]) - 17.78) < 0.01, f"row spacing {xs[1] - xs[0]}"
    pitches = {round(b - a, 2) for a, b in zip(ys, ys[1:])}
    assert pitches == {2.54}, f"pad pitch not 2.54: {pitches}"
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd ~/esp/SMK_test_board && python3 -m pytest test_footprints.py -q
```

Expected: FAIL — missing `XIAO_ESP32C6_HEADERS.kicad_mod`.

- [ ] **Step 3: Draw the footprint**

Create `smk_test_board.pretty/XIAO_ESP32C6_HEADERS.kicad_mod`. Dimensions from the XIAO form factor: board 21 × 17.5 mm, two 1×7 headers on 2.54 mm pitch, rows 17.78 mm (700 mil) apart, pad 1 at the USB end.

Pad order, left column top-to-bottom then right column top-to-bottom, matching the XIAO silkscreen: `D0, D1, D2, D3, D4, D5, D6` then `D7, D8, D9, D10, 3V3, GND, 5V`.

```
(footprint "XIAO_ESP32C6_HEADERS"
  (version 20221018) (generator "smk_test_board")
  (layer "F.Cu")
  (attr through_hole)
  (fp_text reference "REF**" (at 0 -12) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))
  (fp_text value "XIAO_ESP32C6" (at 0 12) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))
  ;; body outline 21 x 17.5mm
  (fp_line (start -8.89 -10.5) (end 8.89 -10.5) (stroke (width 0.12) (type solid)) (layer "F.SilkS"))
  (fp_line (start 8.89 -10.5) (end 8.89 10.5) (stroke (width 0.12) (type solid)) (layer "F.SilkS"))
  (fp_line (start 8.89 10.5) (end -8.89 10.5) (stroke (width 0.12) (type solid)) (layer "F.SilkS"))
  (fp_line (start -8.89 10.5) (end -8.89 -10.5) (stroke (width 0.12) (type solid)) (layer "F.SilkS"))
  ;; pads: left column x=-8.89, right column x=+8.89, y from -7.62 in 2.54 steps
  (pad "1" thru_hole rect (at -8.89 -7.62) (size 1.7 1.7) (drill 1.0) (layers "*.Cu" "*.Mask"))
  (pad "2" thru_hole circle (at -8.89 -5.08) (size 1.7 1.7) (drill 1.0) (layers "*.Cu" "*.Mask"))
  (pad "3" thru_hole circle (at -8.89 -2.54) (size 1.7 1.7) (drill 1.0) (layers "*.Cu" "*.Mask"))
  (pad "4" thru_hole circle (at -8.89 0) (size 1.7 1.7) (drill 1.0) (layers "*.Cu" "*.Mask"))
  (pad "5" thru_hole circle (at -8.89 2.54) (size 1.7 1.7) (drill 1.0) (layers "*.Cu" "*.Mask"))
  (pad "6" thru_hole circle (at -8.89 5.08) (size 1.7 1.7) (drill 1.0) (layers "*.Cu" "*.Mask"))
  (pad "7" thru_hole circle (at -8.89 7.62) (size 1.7 1.7) (drill 1.0) (layers "*.Cu" "*.Mask"))
  (pad "8" thru_hole circle (at 8.89 -7.62) (size 1.7 1.7) (drill 1.0) (layers "*.Cu" "*.Mask"))
  (pad "9" thru_hole circle (at 8.89 -5.08) (size 1.7 1.7) (drill 1.0) (layers "*.Cu" "*.Mask"))
  (pad "10" thru_hole circle (at 8.89 -2.54) (size 1.7 1.7) (drill 1.0) (layers "*.Cu" "*.Mask"))
  (pad "11" thru_hole circle (at 8.89 0) (size 1.7 1.7) (drill 1.0) (layers "*.Cu" "*.Mask"))
  (pad "12" thru_hole circle (at 8.89 2.54) (size 1.7 1.7) (drill 1.0) (layers "*.Cu" "*.Mask"))
  (pad "13" thru_hole circle (at 8.89 5.08) (size 1.7 1.7) (drill 1.0) (layers "*.Cu" "*.Mask"))
  (pad "14" thru_hole circle (at 8.89 7.62) (size 1.7 1.7) (drill 1.0) (layers "*.Cu" "*.Mask"))
)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd ~/esp/SMK_test_board && python3 -m pytest test_footprints.py -q
```

Expected: PASS.

- [ ] **Step 5: Print at 1:1 and check against a physical XIAO**

This is the step that prevents an unusable board and it cannot be automated. Open the footprint in KiCad, print at exactly 100% scale, and seat a real XIAO on the paper: the two header rows must line up with its castellated pads.

Record the result in the report. If it does not fit, fix the footprint before proceeding — every later task builds on it.

- [ ] **Step 6: Commit**

```bash
cd ~/esp/SMK_test_board
git add smk_test_board.pretty/XIAO_ESP32C6_HEADERS.kicad_mod test_footprints.py
git commit -m "Add the XIAO ESP32-C6 header footprint"
```

---

### Task 4: EC11 encoder footprint

**Files:**
- Create: `smk_test_board.pretty/EC11_VERTICAL.kicad_mod`
- Modify: `test_footprints.py`

**Interfaces:**
- Consumes: nothing.
- Produces: footprint `smk_test_board:EC11_VERTICAL` — 5 electrical pads (A, C, B on the encoder side; two switch pads) plus two mounting posts.

- [ ] **Step 1: Add the failing expectation**

In `test_footprints.py`'s `EXPECTED`:

```python
    "EC11_VERTICAL": 5,   # A, C, B + 2 switch terminals
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd ~/esp/SMK_test_board && python3 -m pytest test_footprints.py -q
```

Expected: FAIL — missing `EC11_VERTICAL.kicad_mod`.

- [ ] **Step 3: Draw the footprint**

Standard EC11 vertical: encoder pins A/C/B on 2.5 mm pitch along one edge, switch pins on the opposite edge 6.5 mm away, two Ø3.2 mm mounting posts either side. Pad numbering: 1 = A, 2 = C (common), 3 = B, 4 and 5 = switch.

```
(footprint "EC11_VERTICAL"
  (version 20221018) (generator "smk_test_board")
  (layer "F.Cu")
  (attr through_hole)
  (fp_text reference "REF**" (at 0 -8) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))
  (fp_text value "EC11" (at 0 8) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))
  (fp_line (start -6 -6.5) (end 6 -6.5) (stroke (width 0.12) (type solid)) (layer "F.SilkS"))
  (fp_line (start 6 -6.5) (end 6 6.5) (stroke (width 0.12) (type solid)) (layer "F.SilkS"))
  (fp_line (start 6 6.5) (end -6 6.5) (stroke (width 0.12) (type solid)) (layer "F.SilkS"))
  (fp_line (start -6 6.5) (end -6 -6.5) (stroke (width 0.12) (type solid)) (layer "F.SilkS"))
  (pad "1" thru_hole rect (at -2.5 3.25) (size 1.6 1.6) (drill 1.0) (layers "*.Cu" "*.Mask"))
  (pad "2" thru_hole circle (at 0 3.25) (size 1.6 1.6) (drill 1.0) (layers "*.Cu" "*.Mask"))
  (pad "3" thru_hole circle (at 2.5 3.25) (size 1.6 1.6) (drill 1.0) (layers "*.Cu" "*.Mask"))
  (pad "4" thru_hole circle (at -2.5 -3.25) (size 1.6 1.6) (drill 1.0) (layers "*.Cu" "*.Mask"))
  (pad "5" thru_hole circle (at 2.5 -3.25) (size 1.6 1.6) (drill 1.0) (layers "*.Cu" "*.Mask"))
  (pad "" np_thru_hole circle (at -5.6 0) (size 3.2 3.2) (drill 3.2) (layers "*.Cu" "*.Mask"))
  (pad "" np_thru_hole circle (at 5.6 0) (size 3.2 3.2) (drill 3.2) (layers "*.Cu" "*.Mask"))
)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd ~/esp/SMK_test_board && python3 -m pytest test_footprints.py -q
```

Expected: PASS.

- [ ] **Step 5: Print at 1:1 and check against the physical EC11**

Same procedure as Task 3 Step 5. EC11 variants differ in mounting-post spacing; check yours rather than trusting the drawing. Record the result.

- [ ] **Step 6: Commit**

```bash
cd ~/esp/SMK_test_board
git add smk_test_board.pretty/EC11_VERTICAL.kicad_mod test_footprints.py
git commit -m "Add the EC11 encoder footprint"
```

---

### Task 5: Schematic generation

**Files:**
- Modify: `generate_test_board.py` (add `build_sch()`)
- Modify: `test_test_board.py`

**Interfaces:**
- Consumes: `PIN`, `key_xy` (Task 2); footprints from Tasks 1, 3, 4.
- Produces: `smk_test_board/smk_test_board.kicad_sch`, and
  `build_nets() -> dict[str, list[tuple[str, str]]]` mapping net name to
  `(ref, logical_pad)` pairs, which Task 6 places against.

**Logical pad names, not footprint pad numbers.** `build_nets()` speaks in
`"A"`/`"K"` for diodes, `"1"`/`"2"` for switches, and
`"VDD"`/`"GND"`/`"DIN"`/`"DOUT"` for the LEDs. The proven `SK6812MINI_E`
footprint numbers its pads `1`–`4`, so `build_sch()` translates through a
`PAD_MAP` on the way out. Tests assert against the logical names, which is
what makes them readable; the translation is one table in one place.

Net list, which is the whole circuit:

| Net | Members |
|---|---|
| `ROW0`–`ROW2` | XIAO pads 2, 3, 4; cathode of each diode in that row |
| `COL0`–`COL2` | XIAO pads 5, 6, 7; one side of each switch in that column |
| `ENC_A`, `ENC_B` | XIAO pads 8, 9; EC11 pads 1, 3 |
| `LEDD0` | XIAO pad 10 → level-shifter input |
| `LEDD1`..`LEDD9` | level-shifter output → RGB1 DIN, then RGB*n* DOUT → RGB*n+1* DIN |
| `VSYS` | XIAO BAT pad, JST pin 1, all SK6812 VDD, level-shifter VCC, C_bulk + |
| `+3V3` | XIAO pad 12, level-shifter low-side reference |
| `GND` | XIAO pads 13, JST pin 2, all SK6812 GND, all decoupling caps |

- [ ] **Step 1: Write the failing test**

Add to `test_test_board.py`:

```python
def test_every_matrix_position_has_a_diode_in_the_right_direction():
    """Diode anode to column, cathode to row -- the direction current flows
    when a driven column goes high. Reversed diodes give a matrix that reads
    nothing, and it is invisible until the board is assembled."""
    nets = tb.build_nets()
    for r in range(tb.ROWS):
        for c in range(tb.COLS):
            d = f"D{r}{c}"
            assert (d, "K") in nets[f"ROW{r}"], f"{d} cathode not on ROW{r}"
            sw = f"SW{r}{c}"
            assert (sw, "1") in nets[f"COL{c}"], f"{sw} not on COL{c}"
            # anode meets the switch, so the only path is col -> sw -> D -> row
            assert (d, "A") in nets[f"SW{r}{c}_N"], f"{d} anode not on {sw}"


def test_led_chain_is_serial_and_nine_long():
    nets = tb.build_nets()
    assert ("RGB1", "DIN") in nets["LEDD1"]
    for i in range(1, tb.LED_COUNT):
        net = f"LEDD{i + 1}"
        assert (f"RGB{i}", "DOUT") in nets[net], f"RGB{i} DOUT missing from {net}"
        assert (f"RGB{i + 1}", "DIN") in nets[net], f"RGB{i+1} DIN missing from {net}"
    assert f"LEDD{tb.LED_COUNT + 1}" not in nets, "chain longer than the matrix"


def test_leds_are_on_vsys_not_3v3():
    """SK6812MINI-E specifies VDD 3.7-5.5V; +3V3 is below its minimum."""
    nets = tb.build_nets()
    for i in range(1, tb.LED_COUNT + 1):
        assert (f"RGB{i}", "VDD") in nets["VSYS"], f"RGB{i} not on VSYS"
        assert (f"RGB{i}", "VDD") not in nets.get("+3V3", []), f"RGB{i} on +3V3"
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd ~/esp/SMK_test_board && python3 -m pytest test_test_board.py -q
```

Expected: FAIL — `AttributeError: module 'generate_test_board' has no attribute 'build_nets'`.

- [ ] **Step 3: Implement `build_nets()`**

Built from `ROWS`/`COLS` rather than transcribed, so the matrix and the LED
chain cannot drift apart:

```python
PAD_MAP = {
    # logical name -> footprint pad number, per the proven footprints
    "SK6812MINI_E": {"VDD": "1", "DOUT": "2", "GND": "3", "DIN": "4"},
    "D_SOD-123_Back": {"A": "1", "K": "2"},
}


def build_nets():
    """net name -> [(ref, logical pad), ...]

    Diode anode to column *through the switch*, cathode to row: the only
    conducting path is COL -> SW -> D -> ROW, which is what colsAreDriven=1
    with pull-down row sensing requires.
    """
    nets = {}

    def add(net, ref, pad):
        nets.setdefault(net, []).append((ref, pad))

    for r in range(ROWS):
        add(f"ROW{r}", "U1", str(2 + r))          # XIAO pads 2,3,4
    for c in range(COLS):
        add(f"COL{c}", "U1", str(5 + c))          # XIAO pads 5,6,7

    for r in range(ROWS):
        for c in range(COLS):
            sw, d = f"SW{r}{c}", f"D{r}{c}"
            add(f"COL{c}", sw, "1")
            add(f"SW{r}{c}_N", sw, "2")           # switch -> diode anode
            add(f"SW{r}{c}_N", d, "A")
            add(f"ROW{r}", d, "K")

    # LED chain: level shifter drives RGB1, then each DOUT feeds the next DIN.
    add("LEDD0", "U1", "10")                      # GPIO20 -> shifter in
    add("LEDD0", "U2", "IN")
    add("LEDD1", "U2", "OUT")
    for i in range(1, LED_COUNT + 1):
        add(f"LEDD{i}", f"RGB{i}", "DIN")
        if i < LED_COUNT:
            add(f"LEDD{i + 1}", f"RGB{i}", "DOUT")
        add("VSYS", f"RGB{i}", "VDD")             # NOT +3V3: VDD min is 3.7V
        add("GND", f"RGB{i}", "GND")

    add("ENC_A", "U1", "8")
    add("ENC_A", "ENC1", "1")
    add("ENC_B", "U1", "9")
    add("ENC_B", "ENC1", "3")
    add("GND", "ENC1", "2")

    add("VSYS", "J1", "1")
    add("GND", "J1", "2")
    add("+3V3", "U1", "12")
    add("GND", "U1", "13")
    return nets
```

Note the encoder's *push switch* (ENC1 pads 4 and 5) is wired as the matrix
position at row 0 / col 2 in place of `SW02`, so the loop above skips creating
`SW02`; wire ENC1 pad 4 to `COL2` and pad 5 to `SW02_N` instead.

- [ ] **Step 4: Implement `build_sch()`**

Emit the schematic s-expression, translating logical pads through `PAD_MAP`.
Follow `generate_macropad.py`'s `two_pin()` and `sch_text()` for the shape of
a component entry. Include a `sch_text()` block recording the spec's §3 power
note verbatim — VSYS not 3V3, 324 mA at full white, and the low-battery
caveat — the way the keyboard project records its own RGB budget on the
schematic where an assembler will see it.

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd ~/esp/SMK_test_board && python3 -m pytest test_test_board.py -q
```

Expected: PASS, 6 tests.

- [ ] **Step 6: Verify the schematic parses**

```bash
cd ~/esp/SMK_test_board && python3 generate_test_board.py && \
  python3 -c "
import generate_macropad as gm, sys
sys.path.insert(0, '.')
print(gm.check_parens(open('smk_test_board/smk_test_board.kicad_sch').read(), 'sch'))"
```

Expected: `end=0`.

- [ ] **Step 7: Commit**

```bash
cd ~/esp/SMK_test_board
git add generate_test_board.py test_test_board.py smk_test_board/
git commit -m "Generate the schematic: matrix, encoder, LED chain, power"
```

---

### Task 6: PCB placement

**Files:**
- Modify: `generate_test_board.py` (add `build_pcb()`)
- Modify: `test_test_board.py`

**Interfaces:**
- Consumes: `build_nets()` (Task 5), `key_xy` (Task 2), all footprints.
- Produces: `smk_test_board/smk_test_board.kicad_pcb`, ratsnest-only (no routing — the siblings route in a separate script), and `placed()` returning `{ref: (x, y, side, rot)}`.

- [ ] **Step 1: Write the failing test**

Add to `test_test_board.py`:

```python
def test_leds_sit_under_their_keys():
    p = tb.placed()
    for r in range(tb.ROWS):
        for c in range(tb.COLS):
            kx, ky = tb.key_xy(r, c)
            lx, ly, side, _ = p[f"RGB{r * tb.COLS + c + 1}"]
            assert side == "B", "SK6812MINI-E is reverse-mount: back side"
            assert abs(lx - kx) < 1.0 and abs(ly - ky) < 1.0, \
                f"RGB under key {r},{c} is {lx-kx:.2f},{ly-ky:.2f} off centre"


def test_everything_is_inside_the_board_outline():
    p = tb.placed()
    w, h = tb.BOARD_W, tb.BOARD_H
    for ref, (x, y, _, _) in p.items():
        assert 0 < x < w and 0 < y < h, f"{ref} at {x},{y} outside {w}x{h}"


def test_no_unexpected_courtyard_overlaps():
    """Diodes and LEDs under their own switch are expected; anything else
    overlapping means two parts cannot both be assembled."""
    unexpected, _expected = tb.check_overlaps()
    assert unexpected == [], f"unexpected overlaps: {unexpected}"
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd ~/esp/SMK_test_board && python3 -m pytest test_test_board.py -q
```

Expected: FAIL — no `placed`.

- [ ] **Step 3: Implement `build_pcb()`**

Place, in this order:

1. The 3×3 key field on `key_xy()` — `SW_Gateron_KS33_HS` front side, one `SK6812MINI_E` on the **back** under each key centre, one `D_SOD-123_Back` per key on the back inside the socket courtyard (the pattern `generate_macropad_mini.py` uses; read `socket_obstacles()` there rather than transcribing keepouts by hand — its docstring records what transcribing them by hand cost).
2. The EC11 at the row 0 / col 2 position, replacing that switch.
3. The XIAO headers below the key field.
4. Level shifter, bulk cap and JST along the bottom edge.
5. Four `MountingHole_M2` at the corners.

Set `BOARD_W`/`BOARD_H` from the resulting extents plus a 5 mm margin, and reuse `gm`'s `check_overlaps()` via a thin `check_overlaps()` wrapper.

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd ~/esp/SMK_test_board && python3 -m pytest test_test_board.py -q && python3 generate_test_board.py
```

Expected: tests PASS; generator prints the written file sizes and `overlap scan: N expected, 0 unexpected`.

- [ ] **Step 5: Open it in KiCad and look at it**

```bash
open smk_test_board/smk_test_board.kicad_pro
```

A generated board that passes its own geometry tests can still be visibly wrong — parts on the wrong side, a key field off-centre, silkscreen over pads. Look before proceeding, and record what you saw.

- [ ] **Step 6: Commit**

```bash
cd ~/esp/SMK_test_board
git add generate_test_board.py test_test_board.py smk_test_board/
git commit -m "Place the board: key field, per-key LEDs, XIAO, encoder"
```

---

### Task 7: DRC and fabrication output

**Files:**
- Create: `export_fab.py`
- Create: `docs/fabrication.md`

**Interfaces:**
- Consumes: the generated `.kicad_pcb`.
- Produces: `gerbers/` (gitignored) and a documented ordering procedure.

- [ ] **Step 1: Run DRC**

```bash
cd ~/esp/SMK_test_board && \
  /Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli pcb drc \
  --output drc.rpt --severity-error smk_test_board/smk_test_board.kicad_pcb && \
  tail -20 drc.rpt
```

Expected: zero errors. Unrouted-net warnings are expected — the board ships ratsnest-only, like its siblings, so routing is a separate concern.

- [ ] **Step 2: Write the fab export script**

Create `export_fab.py` invoking `kicad-cli pcb export gerbers` and `drill` into `gerbers/`, then zipping. **Copy the structure from `~/esp/SMK_Keyboard/smk_kbd_rp2040/export_fab.py`** — it exists (inside the project directory, not the repo root) and already encodes this ecosystem's layer set and zone-fill step. Read it before writing a fresh one.

- [ ] **Step 3: Run it**

```bash
cd ~/esp/SMK_test_board && python3 export_fab.py && ls gerbers/
```

Expected: a gerber set plus drill files.

- [ ] **Step 4: Write the ordering notes**

`docs/fabrication.md`: JLCPCB, 2-layer, 1.6 mm, HASL, bare boards (no PCBA), plus the 1:1 footprint checks from Tasks 3 and 5 as a hard pre-order gate, and the BOM from the spec's §8.

- [ ] **Step 5: Commit**

```bash
cd ~/esp/SMK_test_board
git add export_fab.py docs/fabrication.md .gitignore
git commit -m "Add DRC-clean fabrication output and ordering notes"
```

---

## Part B — Firmware (`~/esp/SMK`)

### Task 8: Board configuration for the test board

**Files:**
- Modify: `Sources/smk/Main.swift` (the `configJson` board branches)
- Modify: `Sources/components/battery_adc.c`
- Modify: `Kconfig.projbuild` (whichever file declares the board choice)

**Interfaces:**
- Consumes: the pin map (Global Constraints).
- Produces: a `SMK_BOARD_TEST_BOARD` build that scans the 3×3 matrix, drives 9 LEDs on GPIO20 and reads VBAT on GPIO0.

- [ ] **Step 1: Find the existing board-selection pattern**

```bash
cd ~/esp/SMK && grep -rn "SMK_BOARD_" --include=*.swift --include=Kconfig* | head -20
```

Read what an existing branch looks like before adding one; match it exactly.

- [ ] **Step 2: Add the Kconfig option and the config branch**

Add `SMK_BOARD_TEST_BOARD` alongside the existing choices, and a `configJson` branch with `matrix.rows = [1, 2, 21]`, `matrix.cols = [22, 23, 16]`, `colsAreDriven = 1`, and a 3×3 keymap of plain `key:` actions so the board types something recognisable on first boot.

- [ ] **Step 3: Make the battery ADC channel per-board**

`Sources/components/battery_adc.c` hardcodes IO4 / ADC1_CH4. This board senses on GPIO0 / ADC1_CH0. Make the channel a compile-time constant selected by the board choice — do not add a second copy of the file.

- [ ] **Step 4: Build for the new board**

```bash
cd ~/esp/SMK && idf.py fullclean && idf.py build 2>&1 | tail -5
```

Expected: builds. Do not flash yet — there is no board to flash it to until Part A returns from fabrication.

- [ ] **Step 5: Run the host tests**

```bash
cd ~/esp/SMK && SMK_HOST_TESTS_ONLY=1 swift test 2>&1 | tail -3
```

Expected: 62 tests passing, unchanged.

- [ ] **Step 6: Commit**

```bash
cd ~/esp/SMK
git add -A
git commit -m "Add the SMK test board's configuration"
```

---

## Part C — Configurator (`~/esp/smk_configurator`)

### Task 9: `KeyboardDesign` for the test board

**Files:**
- Modify: `Sources/SMKConfigurator/Model/KeyboardDesign.swift`
- Test: `Tests/SMKConfiguratorTests/KeyboardDesignTests.swift`

**Interfaces:**
- Consumes: the pin map.
- Produces: `KeyboardDesign.smkTestBoard` — 3 rows × 3 cols, `matrix.rows = [1, 2, 21]`, `matrix.cols = [22, 23, 16]`, `colsAreDriven = 1`.

- [ ] **Step 1: Write the failing test**

Add to `Tests/SMKConfiguratorTests/KeyboardDesignTests.swift`:

```swift
    @Test("smkTestBoard matches the board's GPIO map")
    func testBoardMatrix() {
        // These GPIO numbers are a hand-synced contract with the firmware's
        // board config and the PCB generator's PIN table. See
        // ~/esp/SMK_test_board/docs/superpowers/specs/2026-08-16-smk-test-board-design.md
        let design = KeyboardDesign.smkTestBoard
        #expect(design.rowCount == 3)
        #expect(design.colCount == 3)
        #expect(design.matrix.rows == [1, 2, 21])
        #expect(design.matrix.cols == [22, 23, 16])
        #expect(design.matrix.colsAreDriven == 1)
    }
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd ~/esp/smk_configurator && swift test --build-system native --filter testBoardMatrix
```

Expected: FAIL to compile — no `smkTestBoard`.

- [ ] **Step 3: Add the design**

Add a `static let smkTestBoard` to `KeyboardDesign`, following `gateronLPKBD`'s shape exactly (same key-width and gap conventions), with a 3×3 layout.

- [ ] **Step 4: Run the suite**

```bash
cd ~/esp/smk_configurator && swift test --build-system native 2>&1 | tail -2
```

Expected: all tests pass, one more than before.

- [ ] **Step 5: Write the board's `keymap.json`**

The spec's §7 calls for one alongside the design. Create
`~/esp/SMK_test_board/keymap.json` — living with the board, not the app, since
it describes this hardware — with the matrix block matching the design exactly
and a single layer of 9 recognisable actions:

```json
{
  "matrix": { "rows": [1, 2, 21], "cols": [22, 23, 16], "colsAreDriven": 1 },
  "layers": [
    [["key:1", "key:2", "key:3"],
     ["key:4", "key:5", "key:6"],
     ["key:7", "key:8", "mo:1"]],
    [["key:f1", "key:f2", "key:f3"],
     ["key:f4", "key:f5", "key:f6"],
     ["key:f7", "key:f8", "trans"]]
  ]
}
```

Two layers with an `mo:1` on the encoder press make the bring-up checklist's
layer test (Task 10, step 5) possible without editing anything first.

- [ ] **Step 6: Verify it loads in the app**

```bash
cd ~/esp/smk_configurator && swift run --build-system native SMKConfigurator
```

Open `~/esp/SMK_test_board/keymap.json` via the titlebar's Open action and
confirm a 3×3 board renders with both layers listed. Then quit.

- [ ] **Step 7: Commit (both repos)**

```bash
cd ~/esp/smk_configurator
git add Sources/SMKConfigurator/Model/KeyboardDesign.swift Tests/SMKConfiguratorTests/KeyboardDesignTests.swift
git commit -m "Add the SMK test board design"

cd ~/esp/SMK_test_board
git add keymap.json
git commit -m "Add the test board's reference keymap"
```

---

## Part D — Bring-up

### Task 10: Bring-up checklist

**Files:**
- Create: `~/esp/SMK_test_board/docs/bring-up.md`

**Interfaces:**
- Consumes: everything above.
- Produces: the procedure that turns a delivered PCB into a validated one.

- [ ] **Step 1: Write the checklist**

Transcribe the spec's §9 acceptance checks into an ordered procedure with a place to record each result, in this order — **power before anything else**:

1. Visual inspection and continuity: VSYS–GND and 3V3–GND not shorted, *before* seating the XIAO.
2. Seat the XIAO, power over USB, confirm it enumerates.
3. Flash the `SMK_BOARD_TEST_BOARD` build.
4. Matrix: every one of the 9 positions, including the encoder press; three-key L for ghosting.
5. Layers: `mo:` while held, `tg:` latching.
6. BLE HID typing into a Mac.
7. Keymap upload from the configurator's DEV pane, then confirm a remapped key.
8. Power cycle; confirm the remap persisted.
9. RGB: chain lights and animates. **First hardware validation of the RMT driver.**
10. Battery: run untethered, confirm a plausible falling percentage. **First hardware validation of `BatteryMonitor`.**
11. Two-Mac bonding.

- [ ] **Step 2: Commit**

```bash
cd ~/esp/SMK_test_board
git add docs/bring-up.md
git commit -m "Add the bring-up checklist"
```

---

## Not in this plan

Encoder firmware — quadrature decoding, a keymap action, and configurator UI — is the spec's §10 and gets its own spec and plan once this board exists. GPIO17/19 are wired and idle until then.
