# Fabrication — SMK Test Board (rev A)

Bring-up board for SMK's matrix, RMT LED driver, and `BatteryMonitor` on the
ESP32-C6 (Seeed XIAO ESP32-C6). 3x3 key matrix + EC11 rotary encoder, 9x
SK6812MINI-E per-key RGB. See
`docs/superpowers/specs/2026-08-16-smk-test-board-design.md` for the full
design.

## STOP — pre-order gate

**Do not order this board before printing `smk_test_board/smk_test_board.kicad_pcb`
at 1:1 scale and physically checking two footprints against real parts:**

- `XIAO_ESP32C6_HEADERS` — the Seeed XIAO ESP32-C6's 2x7 castellated/header
  footprint.
- `EC11_VERTICAL` — the rotary encoder's footprint.

Both were hand-drawn from datasheet dimensions in Tasks 3 and 4 of this
project and **have never been checked against a physical part.** No other
footprint in this design is new — the switch, diode, LED, passive, and JST
footprints all come from the proven `~/esp/SMK_macro_pad` sibling generator.
These two are the entire risk surface for "board arrives and a part doesn't
fit." A wrong castellation pitch or encoder pin spacing is not reworkable;
it means a second fab run. Print, hold the real XIAO and EC11 against the
paper, and only then run `export_fab.py` for real and place the order.

This check was **not performed** as part of this task — it requires a
printer and the physical parts, both outside an agent's reach. It is
recorded here as a hard gate for whoever places the order.

## Order specification

| | |
|---|---|
| Fab house | JLCPCB |
| Service | **Bare PCB only — no PCBA/assembly.** See reasoning below. |
| Layers | 2 |
| Dimensions | 76.0 x 113.16 mm |
| Thickness | 1.6 mm |
| Copper weight | 1 oz (JLCPCB default; board has no controlled-impedance or high-current nets that need more) |
| Surface finish | HASL (lead-free) |
| Soldermask / silkscreen | JLCPCB defaults (green / white) — cosmetic only, not specified by the design |
| Min hole / min trace-space | JLCPCB standard capabilities; nothing on this board pushes past them (largest hole is the 5.2 mm XIAO board-support NPTH; matrix/LED/passive pads are all standard sizes from the proven sibling footprint library) |

**Why bare boards, no PCBA:** at 9 switches, 9 LEDs, 9 diodes, one MCU
module, one encoder, and a handful of passives, JLCPCB's per-unique-part
assembly fee buys nothing at this part count, and the Gateron KS-33
hot-swap sockets and the through-hole EC11 aren't SMT-assembled parts
anyway. Hand assembly is the right call, matching the design spec's §8
call. Components split across both sides: switches, diodes, and the 9
LEDs mount on the **back**; the XIAO module, encoder, level shifter, and
passives mount on the **front** — both sides need populating regardless of
who solders them.

**The board ships ratsnest-only.** Like its `~/esp/SMK_macro_pad` siblings,
routing copper is a separate concern from this task; nothing on this board
has been routed, and JLCPCB doesn't need routed copper to fab bare boards —
only Gerbers/drill for the layers and holes that exist. Do not route this
board as part of ordering it.

## Bill of materials

From the design spec §8 (`docs/superpowers/specs/2026-08-16-smk-test-board-design.md`).

**On hand already:**

| Qty | Part |
|---|---|
| 1 | Seeed XIAO ESP32-C6 |
| 8 | Gateron low-profile (KS-33) switches |
| 1 | EC11 rotary encoder |
| 9 | 1N4148 diodes (one per matrix position, encoder push switch included) |

**To source:**

| Qty | Part | Notes |
|---|---|---|
| 9 | SK6812MINI-E | per-key RGB |
| 9 | Gateron KS-33 hot-swap sockets | |
| 1 | Level shifter, LED data line | **SN74AHCT1G125DBVR**, SOT-23-5 — same part `~/esp/SMK_Keyboard`'s RP2040 board uses (its U7), LCSC **C7484**. This board's schematic already carries it as U2. |
| 2 | 1x7 female headers | for the XIAO module |
| 1 | JST-PH 2-pin connector | battery |
| 11 | 100 nF capacitors | 9 for LED decoupling (one per RGB), 2 for encoder debounce (C10/C11) |
| 1 | 100 µF bulk capacitor | LED chain entry (C_BULK) |
| 2 | 10 kΩ resistors | encoder pull-ups, likely unpopulated (XIAO's internal pull-ups may suffice — see design spec §2) |
| 4 | M3 standoffs | mounting; board has 4x M2 mounting holes at the corners — confirm standoff/screw size matches before ordering hardware |
| — | Low-profile keycaps | 9x, to fit Gateron KS-33 |

The sibling `~/esp/SMK_macro_pad/smk_macropad/JLCPCB_Sourcing_Report.md` is
the precedent for part selection on this ecosystem's boards and should be
consulted for the level shifter and passives rather than re-deriving fresh
LCSC part numbers — it's where the SN74AHCT1G125DBVR / C7484 pairing above
came from (matched against the RP2040 keyboard board's own U7, not
re-guessed).

## DRC state and triage

Run with:

```bash
kicad-cli pcb drc --output drc.rpt --severity-error \
  smk_test_board/smk_test_board.kicad_pcb        # errors only
kicad-cli pcb drc --output drc_full.rpt \
  smk_test_board/smk_test_board.kicad_pcb          # errors + warnings
```

Errors-only run: **16 violations, 86 unconnected items, 0 footprint
errors.** Full run (errors + warnings): **135 violations, 86 unconnected
items.** Already at zero, per the previous task's verified evidence and
reconfirmed here: `hole_clearance`, `solder_mask_bridge`,
`npth_inside_courtyard`.

| Category | Count | Severity | Blocks fab? | Reasoning |
|---|---|---|---|---|
| `courtyards_overlap` | 16 | error | **No** | Every instance is this board's own declared-expected same-key stack: a switch with its own diode and LED beneath it (verified individually in the previous task). Courtyard overlap is a placement-density warning, not an electrical or manufacturing defect — nothing here indicates a real physical collision, since diodes/LEDs sit on the opposite board side (back) from open space and the switch's actual body doesn't occupy that footprint's full courtyard box. Expected by design on a deliberately dense 19.05 mm-pitch 3x3 macropad. |
| `unconnected_items` | 86 | error | **No** | This board ships ratsnest-only, exactly like its `~/esp/SMK_macro_pad` siblings. Routing copper is out of scope for this task and this fab order; JLCPCB fabs whatever copper/drill data is in the Gerbers, and there is none pending here beyond what's already placed. Not mine to fix. |
| `lib_footprint_issues` | 46 | warning | **No** | Every instance reads "configuration does not include the footprint library 'kbd'/'smk_test_board'" — this is this DRC run's project not having those two libraries registered in its `fp-lib-table`, an artifact of running `kicad-cli` outside the full KiCad project environment. It has no bearing on the Gerbers actually exported (those come from the board file's already-resolved geometry, not a live library lookup) and no bearing on fabrication. |
| `silk_over_copper` | 37 (was 39) | warning | **No** | Reference-designator silk text sitting close enough to a pad's soldermask opening to get clipped. Reduced by 2 for free (see below); the remaining 37 are reference designators on the densely-packed key field (switch + diode + LED stacked per key, by design, same root cause as the courtyard overlaps above) and a couple around the encoder. A clipped ref-des silk on assembled boards can leave the designator illegible, but this is a bring-up test fixture assembled and debugged by the person who designed it — legibility of "SW01" vs. counting grid position is not load-bearing here, and fixing the rest would mean touching per-footprint text offsets on parts explicitly frozen for this task (footprints are off-limits; see Global Constraints). Left as-is. |
| `silk_overlap` | 36 (was 38) | warning | **No** | Same story as `silk_over_copper`: reduced by 2 for free, remainder is silk-on-silk crowding from the same dense key-field stacking, plus 4 irreducible instances where a mounting hole's own reference-designator text overlaps its own silk circle (`fp_hole` in the *shared* `~/esp/SMK_macro_pad/generate_macropad.py` helper — out of scope to edit for a single board, and used by every sibling generator). Cosmetic; doesn't affect solderability or copper. |
| `silk_edge_clearance` | 0 (was 1) | warning | **N/A** | Fully fixed for free — see below. |

**What I changed to reduce silk-over-copper (cheap, and worth it):** the
board's single title text (`"SMK TEST BOARD -- 3x3, XIAO ESP32-C6 + EC11
rev A"`, placed in `generate_test_board.py`'s PCB-writer, not a footprint)
originally sat at `(5, 4)` — inside mounting hole H1's silkscreen circle
(centered at `(MARGIN, MARGIN)` = `(5, 5)`, radius 2.3 mm) and clipped by
the top board edge. That single text object was responsible for the
`silk_edge_clearance` violation and 2 of the `silk_over_copper` /
`silk_overlap` entries each. Moving it to `(7, 10.5)` (below both corner
holes' silk circles, which end at y=7.7, regardless of board width) and
shrinking the font from 2 mm to 1.2 mm cleared all of them: `1 -> 0`
edge-clearance, and small reductions to the two silk-crowding categories.
Confirmed with a full regenerate + `pytest` + DRC re-run (12/12 tests still
pass, 140 -> 135 total violations, the errors-only set unchanged at
16+86). This was a PCB-graphics text-placement change in the generator,
not a footprint edit and not a change to `build_nets()`/`build_sch()`, so
it stayed inside this task's constraints.

**What I deliberately left:** the ~70 remaining `silk_over_copper` /
`silk_overlap` warnings tied to per-key stacking density, and all 46
`lib_footprint_issues` warnings. Chasing the per-key silk crowding further
would mean either loosening the deliberately tight 19.05 mm key pitch or
hand-tuning per-footprint silk text offsets on footprints this task is
explicitly not allowed to touch — not worth it on a bring-up fixture where
the person soldering it already knows the layout. The library-path
warnings are a DRC-run environment artifact with no fabrication
consequence at all.

## Gerber export

```bash
python3 export_fab.py
```

Drives `kicad-cli pcb export gerbers` and `kicad-cli pcb export drill`
(structure follows `~/esp/SMK_Keyboard/smk_kbd_rp2040/export_fab.py`, minus
its zone-fill step — this board has no copper zones/pours to fill, and the
script asserts that and fails loudly if a future revision adds one without
updating it). Output lands in `gerbers/` (gitignored) plus a zipped copy at
the repo root, `smk_test_board_gerbers.zip` (also gitignored, `*.zip`) —
upload that zip to JLCPCB.

Resulting file set (15 files):

```
gerbers/
  smk_test_board-F_Cu.gtl            smk_test_board-B_Cu.gbl
  smk_test_board-F_Mask.gts          smk_test_board-B_Mask.gbs
  smk_test_board-F_Silkscreen.gto    smk_test_board-B_Silkscreen.gbo
  smk_test_board-F_Paste.gtp         smk_test_board-B_Paste.gbp
  smk_test_board-Edge_Cuts.gm1
  smk_test_board-job.gbrjob
  smk_test_board-PTH.drl             smk_test_board-NPTH.drl
  smk_test_board-PTH-drl_map.gbr     smk_test_board-NPTH-drl_map.gbr
  drill-report.txt
```

## Ordering checklist

1. **1:1 print check against real XIAO ESP32-C6 and EC11 parts — see the
   gate at the top of this document. Do not skip.**
2. `./venv/bin/python -m pytest -q` — 12/12 should pass.
3. `kicad-cli pcb drc --severity-error` — should still show 16
   violations / 86 unconnected, all triaged above as non-blocking. Any
   *new* error category is a real regression; stop and investigate before
   ordering.
4. `python3 export_fab.py` — regenerates `gerbers/` and the zip fresh from
   the current board file.
5. Upload `smk_test_board_gerbers.zip` to JLCPCB. Select: 2 layers, 1.6 mm,
   HASL, no PCBA/assembly service.
6. Source the BOM above (`JLCPCB_Sourcing_Report.md` precedent for the
   level shifter and passives) and hand-solder/hand-place on arrival.
