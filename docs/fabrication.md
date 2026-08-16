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

(`BAT_WIRE_PADS`, added later for the battery flying leads, is also new to
this project, but it is two 1.0 mm-drill through-hole pads on a 5.08 mm
pitch with nothing to mate against — there is no part to check it against
and no way for it to not fit. It does not join the gate.)

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
| Min hole / min trace-space | 21 plated holes (all 1.0 mm) and 30 unplated (2.4/3.0/3.2/5.2 mm — the largest is the Gateron hot-swap socket's own centre hole, one per socket). Matrix/LED/passive pads are standard sizes from the proven sibling footprint library. |
| Milled internal cutouts | **9 SK6812MINI-E light windows**, ~3.63 × 3.23 mm rounded rectangles (the real milled opening — the arcs' control-point bounding box, ~3.49 × 3.09 mm, understates it by ~0.15 mm per axis), one per LED, on `Edge.Cuts`. They are not optional decoration: these are reverse-mount LEDs on the back that shine *through* the board. Tightest copper-to-cut on the board is here — see the DRC triage below and checklist item 5. |

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
| 1 | JST SH 2-pin connector, 1.0 mm pitch (SM02B-SRSS-TB or equivalent) | battery — **not JST-PH**, see note below |
| 12 | 100 nF capacitors | 9 for LED decoupling (one per RGB, C1–C9), 2 for encoder debounce (C10/C11), 1 for the level shifter U2's own VCC (C12) |
| 1 | 100 µF bulk capacitor | LED chain entry (C_BULK) |
| 2 | 200 kΩ resistors, 0603 | **R1/R2, the VBAT sense divider** — VSYS → R1 → midpoint → R2 → GND, midpoint on U1 pad 1 (D0 / GPIO0 / ADC1_CH0). Not optional: without them U1 pad 1 floats and firmware reads garbage as a battery voltage. 200 k (not 100 k/10 k) keeps the standing drain at ~10 µA on a 4.2 V cell. |
| — | 2 short lengths of insulated wire | **Battery flying leads.** Soldered from `J2` (the through-hole pad pair silkscreened `BAT+`/`BAT-` beside U1) to the XIAO module's **underside** BAT+/BAT− solder pads. `J2` itself needs no part — it is two plated holes — but the assembly step is mandatory and is the *only* path from the JST connector to the module. See `docs/bring-up.md` step 1b-ii. |
| 4 | **M2** standoffs/screws | mounting; the board's four corner holes are 2.4 mm NPTH (`MountingHole_M2`). This line said "M3" and the design spec's §5 said "4 × M3 at the corners"; both were wrong against the board and are corrected. |
| — | Low-profile keycaps | 9x, to fit Gateron KS-33 |

> **Battery connector pitch — read before ordering a cell.** The board's
> battery connector is **JST SH, 1.0 mm pitch**, not the more common
> JST-PH (2.0 mm). Single-cell Li-ion pouch cells are very commonly sold
> with a **JST-PH 2.0 mm** pigtail pre-attached — that pigtail will
> **physically not mate** with this board's SH connector; the two are
> different, incompatible parts, not a tolerance issue. Before ordering a
> cell, do one of: (a) source a cell with a JST-SH 1.0 mm pigtail, (b) buy
> a JST-PH-to-JST-SH adapter cable, or (c) buy a cell with flying leads (or
> a PH pigtail) and re-terminate it onto an SH connector yourself. Getting
> this wrong is a several-day reorder, not a rework.

**Not on this board:** the "2 × 10 kΩ resistors (encoder pull-ups)" this BOM
used to list, and the design spec §2 line calling them "footprinted but may
be left unpopulated". No such footprints were ever drawn. Both documents are
corrected rather than the parts added: the spec's own reasoning is that the
ESP32-C6's internal pull-ups suffice, firmware does not read the encoder's
A/B until phase 2, and two more footprints on a bring-up fixture is two more
things to get wrong for no benefit. If phase 2 finds the internal pull-ups
marginal, that is when to add them.

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

Errors-only run: **16 violations, 94 unconnected items, 0 footprint
errors.** Full run (errors + warnings): **102 violations, 94 unconnected
items.** At zero and staying there: `hole_clearance`, `solder_mask_bridge`,
`npth_inside_courtyard`, `copper_edge_clearance`, `text_height`,
`lib_footprint_issues`.

### Change against the previous state

The previous table read 16 `courtyards_overlap`, 86 `unconnected_items`, 46
`lib_footprint_issues`, 37 `silk_over_copper`, 36 `silk_overlap` (135 total; the full run is now 102).
Every moved number is accounted for below; none of it is rounding.

| Category | Was | Now | Severity | Blocks fab? | What moved, and why |
|---|---|---|---|---|---|
| `courtyards_overlap` | 16 | **16** | error | **No** | Unchanged. Every instance is this board's own declared-expected same-key stack: a switch with its own diode and LED beneath it. Courtyard overlap is a placement-density signal, not an electrical or manufacturing defect — the diodes/LEDs sit on the opposite board side from the switch bodies. Expected by design on a deliberately dense 19.05 mm-pitch 3x3 macropad. The four parts added this round (J2, R1, R2, C12) were all placed by the obstacle-aware search against real courtyards and add none. |
| `unconnected_items` | 86 | **94** | error | **No** | +8, all from the new parts, and every one of them is ratsnest on a board that ships deliberately unrouted (see below). Exactly: GND 25→28 (J2 pad 2, R2 pad 2, C12 pad 2), VSYS 20→23 (J2 pad 1, R1 pad 1, C12 pad 1), and a new `VBAT_SENSE` net at 2 (three nodes — U1 pad 1, R1 pad 2, R2 pad 1 — is two ratsnest links). Nothing that was connected became unconnected. |
| `lib_footprint_issues` | 46 | **0** | warning | **No** | Gone, and the old explanation for them was wrong. This document used to blame "running `kicad-cli` outside the full KiCad project environment". `kicad-cli` reads the project directory perfectly well; there was simply no `fp-lib-table` committed, so neither `smk_test_board:` nor `kbd:` resolved. Fixing it took three things: (1) the generator now writes `smk_test_board/fp-lib-table` and the `.kicad_pro` the design spec §5 always promised; (2) `kbd:` pointed at a `kbd.pretty` inside a *sibling repo*, so the six `generate_macropad.py` footprints this board uses are now re-emitted into the project's own `smk_test_board/kbd.pretty` and the board is self-contained; (3) `EC11_VERTICAL.kicad_mod` and `XIAO_ESP32C6_HEADERS.kicad_mod` contained `;;` comment lines — KiCad's s-expression parser has no comment syntax, rejects the file, and then refuses to load the **entire** library. That last one is why registering the library alone did not help, and it had been sitting in two committed files unnoticed; the rationale those comments carried now lives in each footprint's `(descr ...)`, which KiCad actually reads. |
| `lib_footprint_mismatch` | 0 | **9** | warning | **No** | New — and new only because the libraries now resolve at all; this check could not run before. All nine are C1–C9, the per-LED decoupling caps, the only parts on this board placed **back-side** via `gm.fp_0603(side="B")`. Cause: KiCad flips a footprint to the back by mirroring about the **X** axis (y → −y), while `generate_macropad.py`'s `_sx()` mirrors about the **Y** axis (x → −x). The two differ by a 180° rotation, so KiCad's comparison sees a mismatch. For an 0603 the copper, mask, paste, silk and fab geometry are all symmetric and **identical** either way — only which pad is numbered 1 changes, and C1–C9 are non-polar 100 nF ceramics, so nothing on this board is affected. It would matter for a *polarised* or pin-asymmetric part placed back-side through the same helper; `test_back_side_passives_are_all_nonpolar` guards that. Not fixed here because `generate_macropad.py` is a shared module four other generated boards depend on. |
| `silk_over_copper` | 37 | **38** | warning | **No** | +1 net: −2 (C10 moved off ENC1's reference field, see the `copper_edge_clearance` note) and +3 new (R1's designator over R2's two pads; U2's designator over C12's GND pad). Same root cause as the existing 35: reference-designator text on a dense board clipping a neighbour's soldermask opening. Cosmetic on a fixture assembled by the person who designed it. |
| `silk_overlap` | 36 | **38** | warning | **No** | +2 net: −2 (ENC1 ref vs C10's silk; ENC1's silk rect vs C11's ref — both cleared when C10/C11 moved) and +4 new (C10 and C11 designators against ENC1's silk envelope at their new position, U2's designator against C12's silk, R1's designator against R2's silk). Silk-on-silk crowding; no copper, mask or paste consequence. |
| `silk_edge_clearance` | 0 | **1** | warning | **No** | New, and a direct consequence of milling the LED light windows: at row 0 / col 2 the EC11 shares its matrix cell with RGB3, so ENC1's silkscreen envelope now crosses RGB3's window. Two instances were introduced; one was fixed by moving ENC1's reference designator from y=−8 to y=−9 in the footprint (text placement only — no pad, hole or courtyard change, so the 1:1 print gate is unaffected). The remaining one is ENC1's silk *rectangle* edge, which cannot move without shrinking the envelope below the encoder's real body-plus-posts extent. Silk printed over a milled opening simply isn't printed; nothing electrical. |
| `copper_edge_clearance` | 0 | **0** | error | **No** | Zero, but it did not start that way and the story matters. Adding the Edge.Cuts windows put 38 copper-to-edge violations on the board. **Two of them were a real defect**: C10, the encoder's debounce cap, had a pad sitting at 0.00 mm from RGB3's window — copper the router would have cut in half. The generator's cap-placement search knew about the EC11's pins and body but not about the LED, and the generator's own overlap scan could not see it either, because C10 and RGB3 share matrix position (0,2) and same-position overlaps are declared expected. Fixed by adding the LED's courtyard to that search. The other 36 are each SK6812MINI-E pad against **its own** light window at 0.2467 mm, which is what the stock KiCad `LED_SK6812MINI-E_3.2x2.8mm_P1.5mm_ReverseMount` footprint measures, used unmodified — the same footprint the sibling `~/esp/SMK_Keyboard/smk_kbd_rp2040` board carries **59** instances of, at this same clearance, and has fabricated successfully. The project's `.kicad_pro` sets `min_copper_edge_clearance = 0.2 mm`, below the real clearance, specifically so this reads as zero errors — that is a **relaxed rule, not a passing check**; it silences the report, it does not mean the clearance is generous. **See the ordering checklist for the number and the precedent an operator actually confirms before proceeding.** |
| `text_height` | 0 | **0** | warning | **N/A** | Appeared briefly (2) when J2's `BAT+`/`BAT-` silk was drawn at 0.8 mm, below the project's own silk-text floor; the labels are 1.0 mm and it is back to zero. |

**Why `unconnected_items` is not a blocker.** This board ships ratsnest-only,
exactly like its `~/esp/SMK_macro_pad` siblings. Routing copper is out of
scope for this fab order; JLCPCB fabs whatever copper/drill data is in the
Gerbers, and there is none pending beyond what's placed.

**On the copper-to-edge number.** This document used to claim KiCad measures
to the *outer edge* of the 0.12 mm-wide `Edge.Cuts` graphic, and that the gap
to the **nominal cut path** the router actually follows is **0.3067 mm** —
"the number to compare against a fab's published copper-to-slot capability."
That is false, and was disproved directly: widening every Edge.Cuts stroke on
the window from 0.12/0.15 mm to 0.4 mm changed the reported DRC clearances
**not at all** (still 3 × 0.2467, 1 × 0.2468, 3 × 0.3154, 29 × 0.3500 mm).
KiCad's copper-to-edge check ignores `Edge.Cuts` stroke width entirely —
**0.2467 mm, as KiCad reports it, is already the copper-to-centreline
number**, not a figure that needs a stroke-width correction added on top.
Reconstructing the corner arcs exactly (r = 0.5 mm, centres at footprint-local
±(1.3171, 1.1171) mm) puts the true minimum tighter still, at **≈0.2329 mm**:
pad 1's edge at local x = −2.05 mm against the arc's leftmost point at
x = −1.8171 mm.

The basis for proceeding is not "0.2467 mm (or 0.2329 mm exact) happens to
clear some fab's published number" — a fab spec is worth checking but isn't
what justifies this board. The basis is precedent: the sibling board
`~/esp/SMK_Keyboard/smk_kbd_rp2040` carries **59** instances of this exact
SK6812MINI-E footprint at this same 0.2467 mm clearance and was fabricated
successfully. That is what licenses fabricating this one too.

The project's `.kicad_pro` sets `min_copper_edge_clearance = 0.2 mm`, below
both numbers above, specifically so DRC reports zero `copper_edge_clearance`
errors here. That is a **relaxed rule, not a passing check**: it turns down
the check that would otherwise flag this clearance, it does not mean the
clearance is comfortable. A green DRC run must not be read as "no tight
clearance exists." None of this can be improved without redrawing the
SK6812MINI-E footprint, which would mean redrawing the light window it exists
for.

**Known cosmetic limitation, row 0 / col 2.** The EC11's 12 × 12 mm body sits
over roughly the southern half of RGB3's light window (the window spans
y = −7.57…−4.48 mm from the key centre; the encoder body reaches y = −6.0 mm).
No pin or mounting post falls inside the opening, so there is no mechanical or
electrical problem, but RGB3 will be visibly dimmer than the other eight. That
is inherent to putting a per-key LED under a rotary encoder at the same matrix
position — both positions are frozen cross-repo contracts.

**Earlier silk work, retained:** the board's single title text
(`"SMK TEST BOARD -- 3x3, XIAO ESP32-C6 + EC11 rev A"`, placed in
`generate_test_board.py`'s PCB writer, not a footprint) originally sat at
`(5, 4)` — inside mounting hole H1's silkscreen circle and clipped by the top
board edge. Moving it to `(7, 10.5)` and shrinking it from 2 mm to 1.2 mm
cleared a `silk_edge_clearance` violation and two entries each from the silk
categories. Still in place.

**What is deliberately left:** the ~76 `silk_over_copper` / `silk_overlap`
warnings tied to per-key stacking density, the single `silk_edge_clearance`
instance at the encoder, and the nine `lib_footprint_mismatch` warnings.
Chasing the silk crowding further would mean loosening the deliberately tight
19.05 mm key pitch or hand-tuning per-footprint text offsets; the mismatch
warnings are a shared-helper convention difference with no geometric
consequence for the non-polar parts involved (see the table).

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
2. `./venv/bin/python generate_test_board.py` — regenerating an unchanged
   generator must produce a **byte-identical** `.kicad_pcb`/`.kicad_sch`
   (`git status` clean). If it doesn't, something is non-deterministic and
   "did the board actually change?" stops being answerable.
3. `./venv/bin/python -m pytest -q` — **23/23** should pass. (It was
   12 tests when this document first claimed "12/12", 13 by the time the
   claim was last edited, and 23 now.)
4. `kicad-cli pcb drc --severity-error` — should show **16 violations / 94
   unconnected**, all triaged above as non-blocking. Any *new* error
   category is a real regression; stop and investigate before ordering.
5. **Confirm the tightest clearance on the board against precedent, not
   against "it happens to clear a fab spec."** The nine SK6812MINI-E light
   windows sit **0.2467 mm** from their own LED pads as KiCad measures it
   (**≈0.2329 mm** exact, reconstructing the corner arcs — KiCad's own
   figure is already the copper-to-centreline number; there is no separate
   "nominal cut path" figure to add on top, despite what an earlier
   revision of this document claimed). This is the single tightest
   clearance on the board, and the project's `.kicad_pro` relaxes
   `min_copper_edge_clearance` to 0.2 mm specifically so DRC doesn't flag
   it — that is a relaxed rule, not evidence the clearance is comfortable.
   What actually justifies proceeding: the sibling
   `~/esp/SMK_Keyboard/smk_kbd_rp2040` board carries **59** instances of
   this exact stock reverse-mount footprint at this same 0.2467 mm
   clearance and has been fabricated successfully. Confirm that precedent
   still holds (nothing about this footprint changed since) and, as a
   secondary check, that it's also within the fab's *current* published
   copper-to-slot capability.
6. **Confirm `gerbers/smk_test_board-Edge_Cuts.gm1` contains the nine LED
   windows**, not just the board outline: `grep -cE '^G0[23]\*$'
   gerbers/smk_test_board-Edge_Cuts.gm1` must be **108** (9 LEDs × 12 arcs
   per window). These are reverse-mount LEDs shining *through* the board;
   with no windows they do nothing, and it is not reworkable after fab.
   This is the exact defect that reached this checklist once already — an
   earlier revision of this step gave a command that grepped
   `smk_test_board.kicad_pcb` (the source file) rather than the gerber
   actually being confirmed, so it could pass without checking what the
   step claims to check.
7. `python3 export_fab.py` — regenerates `gerbers/` and the zip fresh from
   the current board file. Cross-check `gerbers/drill-report.txt`: **21
   plated / 30 unplated** holes.
8. Upload `smk_test_board_gerbers.zip` to JLCPCB. Select: 2 layers, 1.6 mm,
   HASL, no PCBA/assembly service.
9. Source the BOM above (`JLCPCB_Sourcing_Report.md` precedent for the
   level shifter and passives) and hand-solder/hand-place on arrival.
   **Do not skip the two battery flying leads** (`J2` → the XIAO's
   underside BAT+/BAT− pads): they are the board's only path from the JST
   cell connector to the module. See `docs/bring-up.md` step 1b-ii.
