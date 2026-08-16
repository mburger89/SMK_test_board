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
import json
import math
import os
import re
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


# ============================================================ NETLIST ======
# Logical pad names, not footprint pad numbers -- "A"/"K" for diodes, "1"/"2"
# for switches, "VDD"/"GND"/"DIN"/"DOUT" for the LEDs. build_sch() translates
# through PAD_MAP on the way out. Most refs (XIAO pads, the Gateron switches,
# the EC11, the JST connector) already use numeric footprint pad numbers
# directly as their logical name, so PAD_MAP only needs entries for the
# footprints where that isn't true.
PAD_MAP = {
    # logical name -> footprint pad number, per the proven footprints
    "SK6812MINI_E": {"VDD": "1", "DOUT": "2", "GND": "3", "DIN": "4"},
    # D_SOD-123_Back: pad 1 = K, pad 2 = A. Settled from the sibling's own
    # fp_diode(ref, x, y, rot, n_k, n_a, ...) -- cathode net is its FIRST
    # net parameter, wired to pad 1. (generate_macropad.py:1485 records
    # this exact class of bug having shipped there once already.)
    "D_SOD-123_Back": {"K": "1", "A": "2"},
    # SOT-23-5: SN74AHCT1G125DBVR pinout (datasheet SCLS504E) --
    # 1 OE#(active-low) 2 A(in) 3 GND 4 Y(out) 5 VCC
    "SOT-23-5": {"OE#": "1", "A": "2", "GND": "3", "Y": "4", "VCC": "5"},
}


def build_nets():
    """net name -> [(ref, logical pad), ...]

    Diode anode to column *through the switch*, cathode to row: the only
    conducting path is COL -> SW -> D -> ROW, which is what colsAreDriven=1
    with pull-down row sensing requires.

    Position (0, 2) has no SW02 -- the EC11's integrated push switch
    occupies that matrix position instead (see the design spec's §2), wired
    at the bottom of this function alongside the rest of the encoder: ENC1
    pad 4 takes the COL2 side, pad 5 takes the SW02_N (diode-anode) side.
    D02 itself still exists like any other matrix diode.
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
            d = f"D{r}{c}"
            add(f"ROW{r}", d, "K")
            if (r, c) == (0, 2):
                continue          # EC11 push switch takes this position
            sw = f"SW{r}{c}"
            add(f"COL{c}", sw, "1")
            add(f"SW{r}{c}_N", sw, "2")           # switch -> diode anode
            add(f"SW{r}{c}_N", d, "A")

    # LED chain: level shifter (SN74AHCT1G125DBVR, SOT-23-5, single-gate
    # buffer -- same part the sibling keyboard project uses) drives RGB1,
    # then each DOUT feeds the next DIN. OE# tied to GND permanently
    # enables it; VCC from VSYS (not +3V3) so AHCT's 2.0V input threshold
    # keeps margin against the C6's 3.3V drive across VSYS's whole range.
    add("LEDD0", "U1", "10")                      # GPIO20 -> shifter in
    add("LEDD0", "U2", "A")                        # shifter input
    add("GND", "U2", "OE#")                        # permanently enabled
    add("GND", "U2", "GND")
    add("LEDD1", "U2", "Y")                         # shifter output -> RGB1 DIN
    add("VSYS", "U2", "VCC")
    for i in range(1, LED_COUNT + 1):
        add(f"LEDD{i}", f"RGB{i}", "DIN")
        if i < LED_COUNT:
            add(f"LEDD{i + 1}", f"RGB{i}", "DOUT")
        add("VSYS", f"RGB{i}", "VDD")             # NOT +3V3: VDD min is 3.7V
        add("GND", f"RGB{i}", "GND")
        # Local 100nF decoupling per LED (C1..C9, one per RGBi), matching
        # the SK6812MINI-E datasheet's own recommended application circuit
        # -- and the sibling keyboard project's C100-C158, added there for
        # the same reason (an earlier revision of that board had only one
        # bulk cap at the chain's start, LEDs away from the far end).
        # Controller review round 1 on Task 6: this board's build_nets()
        # originally wired none of these at all; fixed here.
        add("VSYS", f"C{i}", "1")
        add("GND", f"C{i}", "2")

    add("ENC_A", "U1", "8")
    add("ENC_A", "ENC1", "1")
    add("ENC_B", "U1", "9")
    add("ENC_B", "ENC1", "3")
    add("GND", "ENC1", "2")
    add("COL2", "ENC1", "4")                      # push switch: COL2 side
    add("SW02_N", "ENC1", "5")                    # push switch: diode side
    add("SW02_N", "D02", "A")                     # D02 anode meets the switch

    # Encoder debounce: 100nF A-to-GND and B-to-GND, per the design spec's
    # §2 ("each with a 100nF capacitor to ground for contact debounce").
    # Also missing from the original build_nets(); fixed alongside the LED
    # decoupling caps above.
    add("ENC_A", "C10", "1")
    add("GND", "C10", "2")
    add("ENC_B", "C11", "1")
    add("GND", "C11", "2")

    # U2's own local decoupling. Controller review (final wave): the level
    # shifter had nothing on VCC at all -- the nearest cap was C_BULK, 19mm
    # away down the bottom edge, which is a bulk reservoir, not local
    # decoupling for a part switching an 800kHz-ish WS2812 data line.
    add("VSYS", "C12", "1")
    add("GND", "C12", "2")

    add("VSYS", "J1", "1")
    add("GND", "J1", "2")
    # Bulk cap at the LED chain entry. Wired through build_nets() like every
    # other part rather than having its nets passed straight to fp_0603():
    # build_sch() places parts from this dict, so anything that skips it is
    # invisible to the schematic (and to any schematic-derived BOM or
    # netlist). C_BULK, C1-C11 and C10/C11 were all missing from the
    # schematic for exactly that reason until the final review wave.
    add("VSYS", "C_BULK", "1")
    add("GND", "C_BULK", "2")

    # ---- battery: JST -> VSYS -> two flying leads -> the XIAO ------------
    # J2 is a labelled 2-pin THROUGH-HOLE pad pair beside U1 (see
    # _fp_bat_pads()'s docstring for why no PCB pad can reach the XIAO's own
    # underside BAT+/BAT- terminals). Without it VSYS has no source and no
    # sink at the module: the board cannot run untethered, the XIAO's
    # onboard charger never sees the JST cell, and on USB with no cell
    # fitted the LED chain and level shifter are unpowered.
    add("VSYS", "J2", "1")                        # BAT+ flying lead
    add("GND", "J2", "2")                         # BAT- flying lead

    # ---- VBAT sense divider ---------------------------------------------
    # Two 200k 0603s: VSYS -> R1 -> VBAT_SENSE (midpoint) -> R2 -> GND, with
    # the midpoint on U1 pad 1 (D0 / GPIO0 / ADC1_CH0).
    #
    # The design spec's Sec.4 used to claim the XIAO ESP32-C6 "already
    # carries a 1:2 divider on A0" and that no external divider was needed.
    # That is false -- it is the XIAO ESP32-C3/S3 generation that carries an
    # on-module divider; Seeed's own ESP32-C6 battery-monitoring guidance
    # calls for an EXTERNAL 200k/200k pair from BAT to an ADC pin. The spec
    # has been corrected. Before this, PIN["VBAT_SENSE"] existed and drew a
    # schematic port, but build_nets() referenced it zero times: U1 pad 1
    # was a floating input that firmware read as a battery voltage.
    #
    # 200k/200k (not 100k or 10k): halves VSYS exactly, which is what
    # firmware's `vbatDividerRatio = 2` already assumes -- firmware is
    # correct as written and must not change -- while drawing only ~10uA at
    # 4.2V, which matters on the coin-sized cell this board is for.
    add("VSYS", "R1", "1")
    add("VBAT_SENSE", "R1", "2")
    add("VBAT_SENSE", "R2", "1")
    add("GND", "R2", "2")
    add("VBAT_SENSE", "U1", "1")                  # D0 / GPIO0 / ADC1_CH0

    # U1 pad 12 (+3V3, the XIAO's own regulated logic rail) is left
    # unwired: nothing on this board consumes regulated 3.3V -- the LEDs
    # are deliberately on VSYS (see above) and the level shifter is now a
    # single VSYS-rail part, so there is no +3V3 net at all.
    add("GND", "U1", "13")
    return nets


# Two-pin parts that have no hand-drawn block of their own in build_sch().
# ref -> (lib symbol, value, footprint, PCB side).
#
# This registry is the fix for a whole class of bug, not a convenience: the
# schematic used to be assembled purely from hand-written per-block code, so
# every part added to build_nets()/build_pcb() without someone also editing
# build_sch() simply never appeared in it. That is how C1-C9, C10, C11 and
# C_BULK -- 12 real, placed, netted parts -- ended up on the PCB and not in
# the schematic, making any schematic-derived BOM or netlist wrong by 12
# parts and `--schematic-parity` DRC unusable. build_sch() now auto-places
# everything listed here, build_pcb() reads its values/footprints from the
# same table, and test_schematic_has_every_part_the_pcb_has asserts the two
# documents carry the identical ref set.
AUX_PARTS = {}
for _i in range(1, LED_COUNT + 1):
    AUX_PARTS[f"C{_i}"] = ("C_kbd", "100n", "RC_0603", "B")   # per-LED decoupling
AUX_PARTS["C10"] = ("C_kbd", "100n", "RC_0603", "F")          # ENC_A debounce
AUX_PARTS["C11"] = ("C_kbd", "100n", "RC_0603", "F")          # ENC_B debounce
AUX_PARTS["C12"] = ("C_kbd", "100n", "RC_0603", "F")          # U2 VCC decoupling
AUX_PARTS["C_BULK"] = ("C_kbd", "100u", "RC_0603", "F")       # LED chain entry
AUX_PARTS["R1"] = ("R_kbd", "200k", "RC_0603", "F")           # VBAT divider high
AUX_PARTS["R2"] = ("R_kbd", "200k", "RC_0603", "F")           # VBAT divider low
AUX_PARTS["J2"] = ("Conn_BAT2_tb", "BAT+ / BAT- flying leads",
                   "BAT_WIRE_PADS", "F")
del _i


# ============================================================ SCHEMATIC ====
# Own lib_symbols, built from generate_macropad's exposed primitives
# (lib_header, sym_pin, sym_inst, sch_wire, sch_glabel, sch_nc, sch_text,
# sch_frame, power_inst, g, NU, U, FONT, POWER_SYMS/POWER_NETS) rather than
# gm.build_lib_symbols(), which would drag in RP2040/RM2/USB-C symbols this
# board has none of. `boxsym` and the per-net power-symbol block are small
# (~15 line) local re-derivations of code gm keeps nested inside its own
# build_lib_symbols() and therefore doesn't expose; everything else below is
# gm's own top-level helpers used directly.

FOOTPRINT_LIB = "smk_test_board"


def _fp(name):
    return f"{FOOTPRINT_LIB}:{name}"


def _boxsym(name, refpfx, value, w, pins):
    """A rectangular multi-pin symbol body. `pins` is a list of
    (electrical_type, x, y, rot, pin_name, pin_number). Mirrors the shape of
    gm's own (nested, unexported) boxsym()."""
    top = max(p[2] for p in pins) + 2.54
    bot = min(p[2] for p in pins) - 2.54
    s = gm.lib_header(name, refpfx, value, hide_pin_names=False)
    s += f'''      (symbol "{name}_0_1"
        (rectangle (start {gm.g(-w / 2)} {gm.g(top)}) (end {gm.g(w / 2)} {gm.g(bot)})
          (stroke (width 0.254) (type default)) (fill (type background)))
      )
      (symbol "{name}_1_1"
'''
    for (pt, x, y, rot, pn, num) in pins:
        s += gm.sym_pin(pt, x, y, rot, pn, str(num)) + "\n"
    s += "      )\n    )\n"
    return s


def _two_pin_named(name, refpfx, value, body, pin1, pin2, pin_x=3.81, length=1.27):
    """Like gm's two_pin_sym(), but with caller-chosen (name, number) pairs
    instead of two_pin_sym's hardcoded "1"/"2" -- needed wherever the
    logical pad name build_nets() uses isn't itself the footprint pad
    number (the level shifter's IN/OUT) or where a friendlier pin name is
    worth having alongside the real pad number (the diode's A/K)."""
    s = gm.lib_header(name, refpfx, value)
    s += f'      (symbol "{name}_0_1"\n{body}      )\n'
    s += f'      (symbol "{name}_1_1"\n'
    s += gm.sym_pin("passive", -pin_x, 0, 0, pin1[0], pin1[1], length=length) + "\n"
    s += gm.sym_pin("passive", pin_x, 0, 180, pin2[0], pin2[1], length=length) + "\n"
    s += "      )\n    )\n"
    return s


def _power_symbols():
    """GND/+3V3/VSYS power ports, in the shape gm.power_inst()'s hardcoded
    "kbd:{net}" lib_id expects. Copied from gm's own inline block (not a
    top-level function there) and trimmed to the three rails this board
    actually has."""
    L = []
    for pname, updown in gm.POWER_SYMS:
        if pname not in ("GND", "+3V3", "VSYS"):
            continue
        if updown == "up":
            body = ('        (polyline (pts (xy 0 0) (xy 0 2.54)) (stroke (width 0) (type default)) (fill (type none)))\n'
                    '        (polyline (pts (xy -0.762 1.27) (xy 0 2.54)) (stroke (width 0) (type default)) (fill (type none)))\n'
                    '        (polyline (pts (xy 0 2.54) (xy 0.762 1.27)) (stroke (width 0) (type default)) (fill (type none)))\n')
            prot, vy = 90, 3.81
        else:
            body = ('        (polyline (pts (xy 0 0) (xy 0 -1.27) (xy 1.27 -1.27) (xy 0 -2.54) '
                    '(xy -1.27 -1.27) (xy 0 -1.27)) (stroke (width 0) (type default)) (fill (type none)))\n')
            prot, vy = 270, -3.81
        L.append(
            f'    (symbol "kbd:{pname}" (power) (pin_names (offset 0)) (exclude_from_sim no) (in_bom no) (on_board yes)\n'
            f'      (property "Reference" "#PWR" (at 0 -6.35 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
            f'      (property "Value" "{pname}" (at 0 {vy:g} 0) {gm.FONT})\n'
            f'      (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
            f'      (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
            f'      (property "Description" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
            f'      (symbol "{pname}_0_1"\n{body}      )\n'
            f'      (symbol "{pname}_1_1"\n'
            f'        (pin power_in line (at 0 0 {prot}) (length 1.27) hide\n'
            f'          (name "{pname}" {gm.FONT})\n'
            f'          (number "1" {gm.FONT})\n'
            f'        )\n'
            f'      )\n    )\n')
    return "\n".join(L)


def build_lib_symbols():
    L = []

    # --- diode (pin "1"=K, pin "2"=A, per PAD_MAP) ---
    diode_body = (
        '        (polyline (pts (xy -1.27 1.27) (xy -1.27 -1.27)) (stroke (width 0.254) (type default)) (fill (type none)))\n'
        '        (polyline (pts (xy 1.27 1.27) (xy 1.27 -1.27) (xy -1.27 0) (xy 1.27 1.27)) (stroke (width 0.254) (type default)) (fill (type outline)))\n'
    )
    L.append(_two_pin_named("D_kbd", "D", "1N4148W", diode_body,
                             ("K", "1"), ("A", "2")))

    # --- Gateron hot-swap switch (no polarity; footprint pads already 1/2) ---
    sw_body = (
        '        (circle (center -1.27 0) (radius 0.508) (stroke (width 0) (type default)) (fill (type none)))\n'
        '        (circle (center 1.27 0) (radius 0.508) (stroke (width 0) (type default)) (fill (type none)))\n'
        '        (polyline (pts (xy -1.27 0.254) (xy 1.905 2.286)) (stroke (width 0) (type default)) (fill (type none)))\n'
    )
    L.append(_two_pin_named("SW_Push_tb", "SW", "Gateron KS-33", sw_body,
                             ("1", "1"), ("2", "2")))

    # --- 2-pin JST battery connector (footprint pads already 1/2) ---
    jst_body = '        (rectangle (start -2.54 2.54) (end 2.54 -2.54) (stroke (width 0.254) (type default)) (fill (type none)))\n'
    L.append(_two_pin_named("Conn_JST2_tb", "J", "JST-PH-2", jst_body,
                             ("1", "1"), ("2", "2")))

    # --- battery flying-lead pad pair (footprint pads already 1/2) ---
    # Drawn as the two bare pads it physically is, not a connector body:
    # nothing plugs into J2, two wires are soldered to it.
    bat_body = (
        '        (circle (center -1.27 0) (radius 0.635) (stroke (width 0.254) (type default)) (fill (type none)))\n'
        '        (circle (center 1.27 0) (radius 0.635) (stroke (width 0.254) (type default)) (fill (type none)))\n'
        '        (polyline (pts (xy -2.54 1.905) (xy -2.54 2.54) (xy -1.905 2.54)) (stroke (width 0.254) (type default)) (fill (type none)))\n'
        '        (polyline (pts (xy 1.905 2.54) (xy 3.175 2.54)) (stroke (width 0.254) (type default)) (fill (type none)))\n'
    )
    L.append(_two_pin_named("Conn_BAT2_tb", "J", "BAT+ / BAT- flying leads",
                             bat_body, ("BAT+", "1"), ("BAT-", "2")))

    # --- generic R / C, for the aux parts (AUX_PARTS) ---
    # Same bodies gm's own build_lib_symbols() draws for R_kbd/C_kbd; copied
    # rather than imported for the same reason _power_symbols() is (they are
    # nested inside gm's build_lib_symbols(), which this board can't call --
    # it would drag in RP2040/RM2/USB-C symbols this board has none of).
    r_body = ('        (rectangle (start -2.54 1.016) (end 2.54 -1.016) '
              '(stroke (width 0.254) (type default)) (fill (type none)))\n')
    L.append(_two_pin_named("R_kbd", "R", "R", r_body, ("1", "1"), ("2", "2")))
    c_body = (
        '        (polyline (pts (xy -0.508 1.905) (xy -0.508 -1.905)) (stroke (width 0.508) (type default)) (fill (type none)))\n'
        '        (polyline (pts (xy 0.508 1.905) (xy 0.508 -1.905)) (stroke (width 0.508) (type default)) (fill (type none)))\n'
    )
    L.append(_two_pin_named("C_kbd", "C", "C", c_body, ("1", "1"), ("2", "2")))

    # --- level shifter: SN74AHCT1G125DBVR, SOT-23-5 single-gate buffer --
    # the same part the sibling keyboard project uses (generate_kbd_rp2040.py,
    # chosen explicitly over same-numbered parts from other vendors that
    # don't come in SOT-23-5). 1 OE#(active-low) 2 A(in) 3 GND 4 Y(out) 5 VCC.
    lvl_pins = [
        ("input", -10.16, 2.54, 0, "OE#", "1"),
        ("input", -10.16, 0, 0, "A", "2"),
        ("power_in", -10.16, -2.54, 0, "GND", "3"),
        ("output", 10.16, 0, 180, "Y", "4"),
        ("power_in", 10.16, 2.54, 180, "VCC", "5"),
    ]
    L.append(_boxsym("LVL_SHIFT_tb", "U", "SN74AHCT1G125DBVR", 15.24, lvl_pins))

    # --- XIAO ESP32-C6, 14-pin header, pads matching XIAO_ESP32C6_HEADERS ---
    xiao_pins = [
        ("input", -15.24, 7.62, 0, "VBAT_SENSE", "1"),
        ("bidirectional", -15.24, 5.08, 0, "ROW0", "2"),
        ("bidirectional", -15.24, 2.54, 0, "ROW1", "3"),
        ("bidirectional", -15.24, 0, 0, "ROW2", "4"),
        ("bidirectional", -15.24, -2.54, 0, "COL0", "5"),
        ("bidirectional", -15.24, -5.08, 0, "COL1", "6"),
        ("bidirectional", -15.24, -7.62, 0, "COL2", "7"),
        ("bidirectional", 15.24, 7.62, 180, "ENC_A", "8"),
        ("bidirectional", 15.24, 5.08, 180, "ENC_B", "9"),
        ("output", 15.24, 2.54, 180, "LED_DATA", "10"),
        ("passive", 15.24, 0, 180, "SPARE", "11"),
        ("power_in", 15.24, -2.54, 180, "+3V3", "12"),
        ("power_in", 15.24, -5.08, 180, "GND", "13"),
        ("power_in", 15.24, -7.62, 180, "5V", "14"),
    ]
    L.append(_boxsym("XIAO_ESP32C6", "U", "Seeed XIAO ESP32-C6", 25.4, xiao_pins))

    # --- EC11 rotary encoder + integrated push switch ---
    ec11_pins = [
        ("passive", -6.35, 2.54, 0, "A", "1"),
        ("passive", -6.35, 0, 0, "C", "2"),
        ("passive", -6.35, -2.54, 0, "B", "3"),
        ("passive", 6.35, 1.27, 180, "SW1", "4"),
        ("passive", 6.35, -1.27, 180, "SW2", "5"),
    ]
    L.append(_boxsym("EC11_tb", "ENC", "EC11", 7.62, ec11_pins))

    # --- SK6812MINI-E RGB LED, pads matching PAD_MAP ---
    led_pins = [
        ("power_in", -6.35, 2.54, 0, "DIN", "4"),
        ("power_in", -6.35, -2.54, 0, "GND", "3"),
        ("output", 6.35, 2.54, 180, "DOUT", "2"),
        ("power_in", 6.35, -2.54, 180, "VDD", "1"),
    ]
    L.append(_boxsym("SK6812MINI_E_tb", "D", "SK6812MINI-E", 7.62, led_pins))

    L.append(_power_symbols())
    return "\n".join(L)


# Sheet floorplan.
SCH_BLOCKS = [
    ("KEY MATRIX  3x3  (one 1N4148 per key; R0C2 is the EC11 push switch)",
     15.24, 15.24, 149.86, 105.41),
    ("XIAO ESP32-C6  U1", 165.1, 62.23, 220.98, 142.24),
    ("ROTARY ENCODER  EC11 / ENC1", 165.1, 149.86, 220.98, 179.07),
    ("LED CHAIN  (9x SK6812MINI-E, level-shifted from GPIO20)",
     15.24, 187.96, 292.1, 215.9),
    ("POWER  (JST battery input + BAT flying leads to the XIAO)",
     15.24, 226.06, 96.52, 250.19),
    ("PASSIVES  (LED/encoder/shifter decoupling, bulk, VBAT sense divider)",
     104.14, 226.06, 292.1, 292.1),
]

# Where the AUX_PARTS grid lands inside the PASSIVES block above. All
# multiples of gm.GRID (1.27) -- gm.g() asserts on-grid and refuses anything
# else.
AUX_GRID_X0, AUX_GRID_DX, AUX_GRID_COLS = 114.3, 30.48, 6
AUX_GRID_Y0, AUX_GRID_DY = 238.76, 20.32


def build_sch():
    """Emit the schematic. Translates build_nets()'s logical pad names to
    real footprint pad numbers via PAD_MAP on the way out; every other ref
    already speaks in real pad numbers (see PAD_MAP's own comment)."""
    nets = build_nets()
    parts, labels, wires, ncs, texts, frames = [], [], [], [], [], []

    for name, x0, y0, x1, y1 in SCH_BLOCKS:
        frames.append(gm.sch_frame(name, x0, y0, x1, y1))
        texts.append(gm.sch_text(name, x0, y0 - 1.27, 2.0))

    def attach(net, px, py, side):
        if net in gm.POWER_NETS:
            dx, dy = {"L": (-2.54, 0), "R": (2.54, 0),
                      "U": (0, -2.54), "D": (0, 2.54)}[side]
            wires.append(gm.sch_wire(px, py, px + dx, py + dy))
            parts.append(gm.power_inst(net, px + dx, py + dy))
        else:
            labels.append(gm.sch_glabel(
                net, px, py, {"L": 180, "R": 0, "U": 270, "D": 90}[side]))

    # net -> {ref -> logical_pad}, so per-instance attach() calls can look
    # up which net (if any) is on a given real pad without re-scanning.
    pad_of = {}
    for net, members in nets.items():
        for ref, pad in members:
            pad_of.setdefault(ref, {})[pad] = net

    def real_pad(ref_footprint_key, logical_pad):
        table = PAD_MAP.get(ref_footprint_key)
        return table[logical_pad] if table else logical_pad

    def net_on(ref, logical_pad):
        return pad_of.get(ref, {}).get(logical_pad)

    # ================================================ XIAO U1 =========
    ux, uy = 193.04, 101.6
    xiao_pin_nums = [str(n) for n in range(1, 15)]
    parts.append(gm.sym_inst("XIAO_ESP32C6", "U1", "Seeed XIAO ESP32-C6",
                              ux, uy, 0, xiao_pin_nums, _fp("XIAO_ESP32C6_HEADERS")))
    left_y = [7.62, 5.08, 2.54, 0, -2.54, -5.08, -7.62]
    for i, ly in enumerate(left_y):
        pad = str(i + 1)
        net = net_on("U1", pad)
        if net is None:
            ncs.append(gm.sch_nc(ux - 15.24, uy - ly))
        else:
            attach(net, ux - 15.24, uy - ly, "L")
    for i, ly in enumerate(left_y):
        pad = str(i + 8)
        net = net_on("U1", pad)
        if net is None:
            ncs.append(gm.sch_nc(ux + 15.24, uy - ly))
        else:
            attach(net, ux + 15.24, uy - ly, "R")

    # ================================================ MATRIX ==========
    mx0, my0 = 20.32, 22.86
    col_dx, row_dy = 38.1, 20.32
    for r in range(ROWS):
        for c in range(COLS):
            xo = mx0 + c * col_dx
            yo = my0 + r * row_dy
            d = f"D{r}{c}"
            d_footprint = "D_SOD-123_Back"
            # D_kbd's pin "1" (K) and pin "2" (A) are authored at local
            # x=-3.81/+3.81 respectively; placing the instance at rot=180
            # swaps that to abs_x=dx+3.81/dx-3.81 -- i.e. A lands on the
            # LEFT (facing the switch/COL side) and K on the RIGHT (facing
            # ROW), which is the direction this matrix needs.
            if (r, c) == (0, 2):
                # No SW02: the diode's anode is fed straight from SW02_N
                # (the EC11 push switch, wired in the encoder block).
                dx = xo + col_dx / 2
                attach(net_on(d, "A"), dx - 3.81, yo, "L")
                a_pad = real_pad(d_footprint, "A")
                k_pad = real_pad(d_footprint, "K")
                parts.append(gm.sym_inst("D_kbd", d, "1N4148W", dx, yo, 180,
                                          [a_pad, k_pad], _fp(d_footprint)))
                attach(net_on(d, "K"), dx + 3.81, yo, "R")
                continue
            sw = f"SW{r}{c}"
            sw_footprint = "SW_Gateron_KS33_HS"
            sx = xo
            attach(net_on(sw, "1"), sx - 3.81, yo, "L")
            parts.append(gm.sym_inst("SW_Push_tb", sw, "Gateron KS-33 hot-swap",
                                      sx, yo, 0, ["1", "2"], _fp(sw_footprint),
                                      props={"BOM Comments": "Hot-swap socket; "
                                             "Gateron KS-33 switch ordered separately."}))
            dx = sx + 15.24
            wires.append(gm.sch_wire(sx + 3.81, yo, dx - 3.81, yo))
            a_pad = real_pad(d_footprint, "A")
            k_pad = real_pad(d_footprint, "K")
            parts.append(gm.sym_inst("D_kbd", d, "1N4148W", dx, yo, 180,
                                      [a_pad, k_pad], _fp(d_footprint)))
            attach(net_on(d, "K"), dx + 3.81, yo, "R")

    # ================================================ ENCODER =========
    ex, ey = 193.04, 163.83
    parts.append(gm.sym_inst("EC11_tb", "ENC1", "EC11 (VERIFY before fab)",
                              ex, ey, 0, ["1", "2", "3", "4", "5"], _fp("EC11_VERTICAL")))
    attach(net_on("ENC1", "1"), ex - 6.35, ey - 2.54, "L")
    attach(net_on("ENC1", "2"), ex - 6.35, ey, "L")
    attach(net_on("ENC1", "3"), ex - 6.35, ey + 2.54, "L")
    attach(net_on("ENC1", "4"), ex + 6.35, ey - 1.27, "R")
    attach(net_on("ENC1", "5"), ex + 6.35, ey + 1.27, "R")

    # ================================================ LED CHAIN ========
    ly0 = 195.58
    lx0 = 40.64
    lvl_footprint = "SOT-23-5"
    lvl_pin_nums = [real_pad(lvl_footprint, k) for k in ("OE#", "A", "GND", "Y", "VCC")]
    parts.append(gm.sym_inst("LVL_SHIFT_tb", "U2", "SN74AHCT1G125DBVR",
                              lx0, ly0, 0, lvl_pin_nums, _fp(lvl_footprint)))
    attach(net_on("U2", "OE#"), lx0 - 10.16, ly0 - 2.54, "L")
    attach(net_on("U2", "A"), lx0 - 10.16, ly0, "L")
    attach(net_on("U2", "GND"), lx0 - 10.16, ly0 + 2.54, "L")
    attach(net_on("U2", "Y"), lx0 + 10.16, ly0, "R")
    attach(net_on("U2", "VCC"), lx0 + 10.16, ly0 - 2.54, "R")

    led_footprint = "SK6812MINI_E"
    rx0 = lx0 + 25.4
    for i in range(1, LED_COUNT + 1):
        rx = rx0 + (i - 1) * 25.4
        ref = f"RGB{i}"
        pins = {k: real_pad(led_footprint, k) for k in ("VDD", "DOUT", "GND", "DIN")}
        parts.append(gm.sym_inst("SK6812MINI_E_tb", ref, "SK6812MINI-E",
                                  rx, ly0, 0,
                                  [pins["VDD"], pins["DOUT"], pins["GND"], pins["DIN"]],
                                  _fp(led_footprint)))
        attach(net_on(ref, "DIN"), rx - 6.35, ly0 - 2.54, "L")
        attach(net_on(ref, "GND"), rx - 6.35, ly0 + 2.54, "L")
        dout_net = net_on(ref, "DOUT")
        if dout_net is None:
            ncs.append(gm.sch_nc(rx + 6.35, ly0 - 2.54))
        else:
            attach(dout_net, rx + 6.35, ly0 - 2.54, "R")
        attach(net_on(ref, "VDD"), rx + 6.35, ly0 + 2.54, "R")

    texts.append(gm.sch_text(
        "RGB power budget: 12mA/channel x 3 x 9 LEDs = 324mA at full white. "
        "Fed from VSYS, NOT +3V3 -- SK6812MINI-E's own datasheet specs VDD "
        "3.7-5.5V, below what the 3.3V rail can supply. VSYS is the Li-ion "
        "cell/USB rail; it can sag below 3.7V well within normal discharge, "
        "so the LEDs may misbehave on a low battery even with brightness "
        "capped -- a limitation of the part choice, not a defect here.",
        17.78, 208.28, 1.8))

    # ================================================ POWER ============
    jx, jy = 40.64, 238.76
    parts.append(gm.sym_inst("Conn_JST2_tb", "J1", "JST-PH-2 (battery)",
                              jx, jy, 0, ["1", "2"], _fp("JST_SH_SM02B_2pin_Back")))
    attach(net_on("J1", "1"), jx - 3.81, jy, "L")
    attach(net_on("J1", "2"), jx + 3.81, jy, "R")

    texts.append(gm.sch_text(
        "J2 (in PASSIVES) is the pad pair for the two flying leads soldered "
        "to the XIAO module's UNDERSIDE BAT+/BAT- pads. The XIAO sits on "
        "female headers and its battery terminals are on its bottom face, so "
        "no PCB pad can mate with them; without J2 the VSYS rail J1 feeds "
        "never reaches the module at all.",
        17.78, 248.92, 1.6))

    # ================================================ AUX PARTS ========
    # Every two-pin part with no block of its own (AUX_PARTS): the per-LED
    # and encoder/level-shifter decoupling caps, the bulk cap, the VBAT
    # sense divider, and the battery flying-lead pads. Auto-placed from the
    # registry rather than hand-written per part -- see AUX_PARTS' own
    # comment for the 12-missing-parts bug that motivates this.
    for idx, (ref, (sym, val, fpname, _side)) in enumerate(AUX_PARTS.items()):
        px = AUX_GRID_X0 + (idx % AUX_GRID_COLS) * AUX_GRID_DX
        py = AUX_GRID_Y0 + (idx // AUX_GRID_COLS) * AUX_GRID_DY
        parts.append(gm.sym_inst(sym, ref, val, px, py, 0, ["1", "2"],
                                  _fp(fpname)))
        n1, n2 = net_on(ref, "1"), net_on(ref, "2")
        assert n1 and n2, f"{ref} has an unwired pin -- check build_nets()"
        attach(n1, px - 3.81, py, "L")
        attach(n2, px + 3.81, py, "R")

    body = "\n".join(texts + frames + [p for p in parts if p] + wires + labels + ncs)
    root_uuid = gm.U("smk-test-board-root-sheet")
    return f'''(kicad_sch (version 20231120) (generator "eeschema") (generator_version "8.0")
  (uuid "{root_uuid}")
  (paper "A3")
  (title_block
    (title "SMK Test Board -- 3x3 macropad, XIAO ESP32-C6 + EC11 + 9x SK6812MINI-E")
    (company "")
    (rev "A")
    (comment 1 "Bring-up board for SMK's matrix/RMT-LED/BatteryMonitor code paths on ESP32-C6")
  )
  (lib_symbols
{build_lib_symbols()}  )
{body}
  (sheet_instances (path "/" (page "1")))
)
'''


# ============================================================ PCB ==========
# Footprint-instantiation helpers for the four parts gm.py has no generator
# for (SK6812MINI_E, XIAO_ESP32C6_HEADERS, EC11_VERTICAL, BAT_WIRE_PADS).
# Built from gm's own low-level s-expression primitives (fp_header/pad/
# fpline/fprect/fparc/npth/model) -- "the geometry and s-expression helpers
# come from generate_macropad.py" per this project's own module docstring --
# rather than hand-rolling a parallel set.
#
# Each of these re-renders the SAME geometry as this project's own
# smk_test_board.pretty/<NAME>.kicad_mod library master, as a positioned PCB
# instance instead of an unplaced library master. It is NOT byte-for-byte
# identical to the master and never was -- the masters draw their rectangles
# as four separate fp_line segments where gm.fprect() emits a single fp_rect,
# and every uuid differs. An earlier revision of this comment claimed
# "byte-for-byte", which is both false and unfalsifiable-looking enough that
# it hid a real defect for several review rounds: _fp_sk6812mini_tb() dropped
# all 20 of the master's Edge.Cuts primitives (the milled light window this
# reverse-mount LED shines through) and its pin-1 silk triangle. Nine LEDs
# shipped with no window at all.
#
# What is actually guaranteed, and what test_footprints.py's
# test_inline_rerenders_match_their_library_master now enforces per
# element-class (pads / silk / courtyard / fab / Edge.Cuts), is EQUIVALENT
# GEOMETRY: same pads, same graphics on the same layers, with fp_rect and its
# four-fp_line spelling treated as the same rectangle. A layer that goes
# missing from a re-render fails that test loudly.
#
# Every part below is placed at rot=0 (or SK6812MINI_E's fixed rot=180,
# matching its own reverse-mount library file), so none of this needs to
# reason about how a rotated footprint's pad-local angle composes with its
# parent's -- gm.fp_gateron/fp_diode (called directly, unmodified, for the
# two footprints that already have generators) are the only parts of this
# board placed with rot != 0, and they carry their own proven rotation
# handling. Footprint graphics are stored in FOOTPRINT-LOCAL coordinates in
# both .kicad_mod and .kicad_pcb (KiCad applies the instance's own (at x y
# rot) when it draws them), so the Edge.Cuts window below is written once in
# local coordinates and lands correctly rotated at all nine placed positions
# -- exactly how the proven sibling board
# ~/esp/SMK_Keyboard/smk_kbd_rp2040/smk_kbd_rp2040.kicad_pcb stores its own
# 58 SK6812MINI_E instances (verified: identical local numbers, footprint
# (at ... 180)).

# ---- SK6812MINI-E light window (Edge.Cuts) -------------------------------
# The ~3.4 x 3.0mm rounded-rect cutout milled through the board so this
# REVERSE-MOUNT LED, soldered to the back, shines through into the switch's
# north window. Transcribed from smk_test_board.pretty/SK6812MINI_E.kicad_mod
# (8 fp_line + 12 fp_arc), not re-derived: these are the exact numbers the
# proven sibling board fabricated. Without them the LEDs are sealed behind
# solid FR4 and the defect is unreworkable after fab.
SK6812_WINDOW_LINES = [
    (1.7, 0, 1.7, 0.700353),
    (1.7, 0, 1.7, -0.700353),
    (0, 1.5, 0.900353, 1.5),
    (0, 1.5, -0.900353, 1.5),
    (0, -1.5, 0.900353, -1.5),
    (0, -1.5, -0.900353, -1.5),
    (-1.7, 0, -1.7, 0.700353),
    (-1.7, 0, -1.7, -0.700353),
]
SK6812_WINDOW_ARCS = [
    (1.74393, 0.856655, 1.71119, 0.781533, 1.7, 0.700353),
    (1.74393, 0.856655, 1.67071, 1.47071, 1.05665, 1.54393),
    (1.7, -0.700353, 1.71118, -0.781538, 1.74393, -0.856655),
    (1.05665, -1.54393, 1.67071, -1.47071, 1.74393, -0.856655),
    (1.05665, -1.54393, 0.981533, -1.51119, 0.900353, -1.5),
    (0.900353, 1.5, 0.981532, 1.51119, 1.05665, 1.54393),
    (-0.900353, -1.5, -0.981533, -1.51119, -1.05665, -1.54393),
    (-1.05665, 1.54393, -0.981533, 1.51119, -0.900353, 1.5),
    (-1.05665, 1.54393, -1.67071, 1.47071, -1.74393, 0.856655),
    (-1.7, 0.700353, -1.71119, 0.781533, -1.74393, 0.856655),
    (-1.74393, -0.856655, -1.67071, -1.47071, -1.05665, -1.54393),
    (-1.74393, -0.856655, -1.71119, -0.781533, -1.7, -0.700353),
]
# Filled silk triangle beside pad 1 -- the LED's polarity marker. Also
# missing from the pre-fix re-render.
SK6812_PIN1_TRIANGLE = [(-2.725, -1.45), (-2.575, -1.65), (-2.875, -1.65)]


def _fppoly(pts, layer, w=0.12, fill="yes"):
    """A filled footprint polygon. gm has no fp_poly helper (nothing on its
    own boards needs one); same shape as its fpline()/fprect()."""
    p = " ".join(f"(xy {x:g} {y:g})" for x, y in pts)
    key = ("poly", layer) + tuple(c for xy in pts for c in xy)
    return (f'    (fp_poly (pts {p}) (stroke (width {w}) (type solid)) '
            f'(fill {fill}) (layer "{layer}") (uuid "{gm.NU(*key)}"))')


def _fptext(kind, txt, x, y, layer, size=0.8, thickness=0.15, mirror=False):
    """A silkscreen/fab text item inside a footprint. gm emits footprint text
    only via fp_header()'s Reference/Value properties; these are extra,
    non-property labels (the BAT+/BAT- polarity marks)."""
    just = " (justify mirror)" if mirror else ""
    return (f'    (fp_text {kind} "{txt}" (at {x:g} {y:g}) (layer "{layer}") '
            f'(uuid "{gm.NU("txt", layer, txt, x, y)}")\n'
            f'      (effects (font (size {size:g} {size:g}) '
            f'(thickness {thickness:g})){just})\n    )')


def _rect_as_lines(x1, y1, x2, y2, layer, w):
    """A rectangle drawn as four fp_line segments rather than one fp_rect.

    Geometrically identical, and this project's parity test treats the two
    spellings as equal -- but KiCad's own "footprint does not match copy in
    library" check does NOT: it compares objects, so a board instance built
    from gm.fprect() reads as different from a library master that spells the
    same rectangle as four fp_lines, and every XIAO/EC11 instance drew a
    lib_footprint_mismatch warning the moment the library was registered and
    actually resolvable. The two hand-drawn masters are the authored source
    for those footprints (they are what the pre-order 1:1 print gate exists
    to check), so the re-render conforms to them, not the other way round.
    """
    corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    return [gm.fpline(*corners[i], *corners[(i + 1) % 4], layer, w)
            for i in range(4)]


def _fp_sk6812mini_tb(ref, x, y, path_uuid, pinnet):
    """SK6812MINI-E, reverse-mount, back side. pinnet keys are footprint pad
    numbers (1=VDD, 2=DOUT, 3=GND, 4=DIN, per PAD_MAP).

    Element order below matches the library master's: pads, silk, pin-1
    triangle, Edge.Cuts window, courtyard, fab, 3D model."""
    s = gm.fp_header(_fp("SK6812MINI_E"), ref, "SK6812MINI-E", x, y, 180,
                      layer="B.Cu", attr="smd", ref_at=(0, 2.6), val_at=(0, -2.54),
                      path_uuid=path_uuid)
    b = []
    for num, px, py in [(1, -2.725, -0.75), (2, -2.725, 0.75),
                        (3, 2.725, 0.75), (4, 2.725, -0.75)]:
        b.append(gm.pad(num, "smd", "roundrect", px, py, 1.35, 0.82,
                        '"B.Cu" "B.Mask" "B.Paste"', pinnet.get(num),
                        extra=" (roundrect_rratio 0.25)"))
    b.append(gm.fpline(3.65, 1.875, 3.65, -1.875, "B.SilkS"))
    b.append(gm.fpline(3.65, -1.875, -2.925, -1.875, "B.SilkS"))
    b.append(gm.fpline(-3.65, 1.875, 3.65, 1.875, "B.SilkS"))
    b.append(gm.fpline(-3.65, -1.15, -2.925, -1.875, "B.SilkS"))
    b.append(gm.fpline(-3.65, -1.15, -3.65, 1.875, "B.SilkS"))
    b.append(_fppoly(SK6812_PIN1_TRIANGLE, "B.SilkS"))
    for x1, y1, x2, y2 in SK6812_WINDOW_LINES:
        b.append(gm.fpline(x1, y1, x2, y2, "Edge.Cuts"))
    for sx, sy, mx, my, ex, ey in SK6812_WINDOW_ARCS:
        b.append(gm.fparc(sx, sy, mx, my, ex, ey, "Edge.Cuts"))
    b.append(gm.fprect(-3.65, 1.87, 3.65, -1.87, "B.CrtYd", 0.05))
    b.append(gm.fpline(-0.8, -1.4, -1.6, -0.6, "B.Fab"))
    b.append(gm.fprect(-1.6, 1.4, 1.6, -1.4, "B.Fab"))
    b.append(gm.model(f"{gm.KICAD3D}/LED_SMD.3dshapes/"
                      "LED_SK6812MINI-E_3.2x2.8mm_P1.5mm_ReverseMount.step"))
    return s + "\n".join(b) + "\n  )\n"


def _fp_xiao_headers(ref, x, y, path_uuid, pinnet):
    """XIAO_ESP32C6_HEADERS: two 1x7 through-hole rows, front side. pinnet
    keys are footprint pad numbers 1-14 (pad 1 = D0, matching XIAO silk)."""
    s = gm.fp_header(_fp("XIAO_ESP32C6_HEADERS"), ref, "XIAO_ESP32C6", x, y, 0,
                      layer="F.Cu", attr="through_hole",
                      ref_at=(0, -12), val_at=(0, 12), path_uuid=path_uuid)
    b = []
    b.extend(_rect_as_lines(-8.75, -10.5, 8.75, 10.5, "F.Fab", 0.1))
    b.extend(_rect_as_lines(-10.2, -10.5, 10.2, 10.5, "F.SilkS", 0.12))
    ys = [-7.62, -5.08, -2.54, 0, 2.54, 5.08, 7.62]
    for i, py in enumerate(ys):
        num = i + 1
        b.append(gm.pad(num, "thru_hole", "rect" if num == 1 else "circle",
                        -8.89, py, 1.7, 1.7, '"*.Cu" "*.Mask"', pinnet.get(num),
                        drill=1.0))
    for i, py in enumerate(ys):
        num = i + 8
        b.append(gm.pad(num, "thru_hole", "circle",
                        8.89, py, 1.7, 1.7, '"*.Cu" "*.Mask"', pinnet.get(num),
                        drill=1.0))
    return s + "\n".join(b) + "\n  )\n"


def _fp_ec11_vertical(ref, x, y, path_uuid, pinnet):
    """EC11_VERTICAL: 5 thru-hole signal pins + 2 NPTH mounting legs, front
    side. pinnet keys are footprint pad numbers 1-5 (1=A,2=C,3=B,4=SW1,5=SW2,
    per the schematic's EC11_tb pin order)."""
    s = gm.fp_header(_fp("EC11_VERTICAL"), ref, "EC11 (VERIFY before fab)", x, y, 0,
                      layer="F.Cu", attr="through_hole",
                      # ref at -9, not -8: at -8 the "ENC1" designator lands
                      # inside RGB3's Edge.Cuts light window (this key IS the
                      # encoder position, and its LED sits 6.025mm north), so
                      # it would be printed over a milled opening and not
                      # exist on the finished board. Text placement only --
                      # no pad, hole or courtyard geometry changes, so the
                      # pre-order 1:1 print gate is unaffected.
                      ref_at=(0, -9), val_at=(0, 8), path_uuid=path_uuid)
    b = []
    b.extend(_rect_as_lines(-6, -6, 6, 6, "F.Fab", 0.1))
    b.extend(_rect_as_lines(-7.7, -6.5, 7.7, 6.5, "F.SilkS", 0.12))
    for num, px, py, shape in [(1, -2.5, 3.25, "rect"), (2, 0, 3.25, "circle"),
                                (3, 2.5, 3.25, "circle"), (4, -2.5, -3.25, "circle"),
                                (5, 2.5, -3.25, "circle")]:
        b.append(gm.pad(num, "thru_hole", shape, px, py, 1.6, 1.6,
                        '"*.Cu" "*.Mask"', pinnet.get(num), drill=1.0))
    b.append(gm.npth(-5.6, 0, 3.2))
    b.append(gm.npth(5.6, 0, 3.2))
    return s + "\n".join(b) + "\n  )\n"


# Flying-lead battery pads. 5.08mm pitch (not 2.54) so the two silk labels
# "BAT+" / "BAT-" fit side by side at a legible 0.8mm without colliding.
BAT_PAD_PITCH = 5.08


def _fp_bat_pads(ref, x, y, path_uuid, pinnet):
    """BAT_WIRE_PADS: a labelled 2-pin THROUGH-HOLE pad pair for two short
    flying leads hand-soldered to the XIAO module's underside BAT+/BAT- pads.

    Why this exists: the XIAO ESP32-C6's battery terminals are solder pads on
    the BOTTOM of the module, and this board seats the module on female
    headers, so no PCB pad can ever mate with them -- XIAO_ESP32C6_HEADERS is
    14 pads with no BAT pad and that is correct. Without these two, VSYS (fed
    by J1, the JST battery connector, and consumed by all nine SK6812 VDD
    pins, C1-C9, C12, C_BULK and U2's VCC) never reaches the XIAO at all: the
    board cannot run untethered, the XIAO's own charger is not in circuit
    with the JST, and on USB with no cell fitted the whole LED chain and the
    level shifter are dead.

    THT, not SMD: these take hand-soldered wire, and an SMD pad tears off.

    Polarity is made unambiguous four ways, because getting it backwards puts
    a Li-ion cell into the XIAO reversed: pad 1 is the KiCad pin-1 square,
    the two pads carry their own "BAT+"/"BAT-" silk labels, a drawn silk "+"
    sits outboard of pad 1 and a drawn silk "-" outboard of pad 2, and the
    fab-layer body rect is annotated in docs/bring-up.md as the VSYS probe
    point. pinnet keys are footprint pad numbers (1 = BAT+ = VSYS, 2 = BAT- =
    GND)."""
    s = gm.fp_header(_fp("BAT_WIRE_PADS"), ref, "BAT+ / BAT- flying leads",
                      x, y, 0, layer="F.Cu", attr="through_hole",
                      ref_at=(0, -4.2), val_at=(0, 4.2), path_uuid=path_uuid)
    h = BAT_PAD_PITCH / 2
    b = []
    b.append(gm.pad(1, "thru_hole", "rect", -h, 0, 1.7, 1.7,
                    '"*.Cu" "*.Mask"', pinnet.get(1), drill=1.0))
    b.append(gm.pad(2, "thru_hole", "circle", h, 0, 1.7, 1.7,
                    '"*.Cu" "*.Mask"', pinnet.get(2), drill=1.0))
    # 1.0mm, not the 0.8mm this first shipped at: 0.8 is below the project's
    # own silk-text minimum (JLCPCB's floor) and DRC flags it as text_height.
    b.append(_fptext("user", "BAT+", -h, -2.3, "F.SilkS", size=1.0))
    b.append(_fptext("user", "BAT-", h, -2.3, "F.SilkS", size=1.0))
    # Drawn "+" outboard of pad 1 and "-" outboard of pad 2 -- redundant with
    # the text on purpose; a clipped or misread label must not be the only
    # thing standing between a Li-ion cell and a reversed XIAO.
    b.append(gm.fpline(-h - 2.6, 0, -h - 1.6, 0, "F.SilkS", 0.15))
    b.append(gm.fpline(-h - 2.1, -0.5, -h - 2.1, 0.5, "F.SilkS", 0.15))
    b.append(gm.fpline(h + 1.6, 0, h + 2.6, 0, "F.SilkS", 0.15))
    b.append(gm.fprect(-3.4, -1.0, 3.4, 1.0, "F.Fab"))
    b.append(gm.fprect(-5.4, -3.0, 5.4, 3.0, "F.CrtYd", 0.05))
    return s + "\n".join(b) + "\n  )\n"


# Half-extents of BAT_WIRE_PADS' F.CrtYd rectangle above, for _place().
BAT_PADS_HALF = (5.4, 3.0)


_SOCKET_CRTYD_RE = re.compile(
    r'\(fp_rect \(start ([-\d.]+) ([-\d.]+)\) \(end ([-\d.]+) ([-\d.]+)\) '
    r'\(stroke \(width [\d.]+\) \(type solid\)\) \(fill none\) \(layer "B.CrtYd"\)')


def _socket_back_courtyard():
    """The Gateron hot-swap socket's real back-side courtyard bounds
    (xlo, ylo, xhi, yhi), local to the footprint origin -- read out of
    gm.fp_gateron()'s own emitted B.CrtYd rectangle rather than hand-copied.
    generate_macropad_mini.py's socket_obstacles() docstring records what
    transcribing these by hand cost there once (the housing left out, 13
    pads ending up underneath it); same reasoning applies here.

    Probing costs nothing but a UUID-counter bump, restored so the real
    placement below gets the same UUIDs it would without this call.
    """
    ctr = gm._ctr[0]
    try:
        text = gm.fp_gateron("REF**", 0, 0, None, None, None)
    finally:
        gm._ctr[0] = ctr
    m = _SOCKET_CRTYD_RE.search(text)
    assert m, "fp_gateron emitted no B.CrtYd rectangle -- socket courtyard unmodelled"
    return tuple(float(g) for g in m.groups())


# ---- generic pad-obstacle reading + clearance search -----------------
# Controller review round 2 on Task 6: the per-LED decoupling cap's
# position was found by a one-off scratch script checked against the
# Gateron socket's obstacles only, and never re-checked at row0/col2,
# whose real neighbour is the EC11, not a socket -- C3 landed 0.05mm short
# of clearance against the EC11's own NPTH leg. The fix is not to nudge
# C3's number by hand (that fixes this board and leaves the same hole in
# the next encoder position) but to make the search itself read whichever
# footprint is actually there, the same way _socket_back_courtyard() reads
# the Gateron's courtyard instead of hand-copying it.
_PAD_OBSTACLE_RE = re.compile(
    r'\(pad "[^"]*" (?:np_)?(?:thru_hole|smd) (\S+) \(at ([-\d.]+) ([-\d.]+)'
    r'(?: [-\d.]+)?\) \(size ([\d.]+) ([\d.]+)\)')


def _pad_obstacles(text):
    """Every pad (SMD copper or NPTH/thru-hole) in a footprint's own
    emitted text, as local (kind, cx, cy, ...) obstacles: ("circle", cx,
    cy, r) for round pads/holes, ("rect", cx, cy, w, h) otherwise. Read
    from the footprint's own s-expression output, not hand-copied --
    works for anything built from gm's pad()/npth() (gm.fp_gateron, and
    this module's own _fp_ec11_vertical, since both emit that same pad
    line shape)."""
    out = []
    for shape, x, y, sx, sy in _PAD_OBSTACLE_RE.findall(text):
        x, y, sx, sy = float(x), float(y), float(sx), float(sy)
        if shape == "circle":
            out.append(("circle", x, y, sx / 2))
        else:
            out.append(("rect", x, y, sx, sy))
    return out


def _probe_obstacles(build_fn, *args, **kwargs):
    """_pad_obstacles(), against a fresh probe build of `build_fn` -- with
    gm's UUID counter snapshotted/restored around the call, so probing
    doesn't shift every UUID emitted by the real placement that follows
    (same technique generate_macropad_mini.py's own _probe() uses)."""
    ctr = gm._ctr[0]
    try:
        text = build_fn(*args, **kwargs)
    finally:
        gm._ctr[0] = ctr
    return _pad_obstacles(text)


def _rect_circle_clearance(rx, ry, rw, rh, cx, cy, r):
    nx = min(max(cx, rx - rw / 2), rx + rw / 2)
    ny = min(max(cy, ry - rh / 2), ry + rh / 2)
    return math.hypot(cx - nx, cy - ny) - r


def _rect_rect_clearance(ax, ay, aw, ah, bx, by, bw, bh):
    return max(abs(ax - bx) - (aw / 2 + bw / 2), abs(ay - by) - (ah / 2 + bh / 2))


def _worst_clearance(cx, cy, cw, ch, obstacles):
    worst = float("inf")
    for kind, *rest in obstacles:
        if kind == "circle":
            ox, oy, r = rest
            worst = min(worst, _rect_circle_clearance(cx, cy, cw, ch, ox, oy, r))
        else:
            ox, oy, ow, oh = rest
            worst = min(worst, _rect_rect_clearance(cx, cy, cw, ch, ox, oy, ow, oh))
    return worst


def _best_clear_offset(obstacles, near_x, near_y, w, h, max_dist=6.0, step=0.2,
                       min_clear=0.3):
    """Grid-search a w x h box within `max_dist` of (near_x, near_y) --
    typically the LED's own local position, since these parts go "beside
    their LED"/"beside the encoder" -- for the position CLOSEST to
    (near_x, near_y) that clears every obstacle (local coordinates, from
    _probe_obstacles()) by at least `min_clear` (0.3mm: comfortably above
    KiCad's default 0.25mm hole-clearance rule).

    Nearest-that-clears, not best-clearance-in-range: an earlier version
    of this function picked the single best-clearing point in the whole
    search box, which is a real bug, not a style choice -- it has no
    reason to stay near (near_x, near_y) at all, so it reliably runs to
    the search box's own far edge (wherever obstacles happen to be
    sparsest), which for a part meant to sit "beside" something is
    exactly backwards. Caught by test_no_unexpected_courtyard_overlaps:
    a per-LED cap at row1/col0, searched only against ITS OWN key's
    obstacles, drifted the full 6mm north and landed inside row0/col0's
    switch courtyard -- a real neighbour this function's obstacle list
    never knew about, because "maximize clearance" doesn't know to stop.

    Falls back to the best clearance found if nothing in range clears
    min_clear (so the caller always gets a point, and check_overlaps()
    still catches an unsafe fallback rather than this function hiding it)."""
    n = int(max_dist / step)
    best_safe = None       # (x, y, clearance, distance) -- nearest OK point
    best_overall = None    # (x, y, clearance) -- fallback if none clear
    for ix in range(-n, n + 1):
        for iy in range(-n, n + 1):
            dx, dy = ix * step, iy * step
            dist = math.hypot(dx, dy)
            if dist > max_dist:
                continue
            x, y = near_x + dx, near_y + dy
            c = _worst_clearance(x, y, w, h, obstacles)
            if best_overall is None or c > best_overall[2]:
                best_overall = (x, y, c)
            if c >= min_clear and (best_safe is None or dist < best_safe[3]):
                best_safe = (x, y, c, dist)
    return best_safe[:3] if best_safe is not None else best_overall


def _placed_obstacles(exclude=()):
    """Every already-placed footprint's real courtyard box as an obstacle, in
    ABSOLUTE board coordinates -- straight out of gm.FPBOX, which _place()/
    _place_box() have already filled with exactly the boxes check_overlaps()
    scans. Same principle as _socket_back_courtyard()/_probe_obstacles(): read
    the real geometry instead of hand-copying coordinates.

    _pad_obstacles()/_probe_obstacles() answer "where are this ONE footprint's
    pads, in its own local frame" -- the right question for a cap tucked under
    its own switch. This answers "what is already on the board, in board
    coordinates" -- the right question for a part like J2 or the VBAT divider,
    which has no owning footprint to sit inside and must simply miss
    everything placed so far."""
    return [("rect", x, y, 2 * hx, 2 * hy)
            for (ref, x, y, hx, hy) in gm.FPBOX if ref not in exclude]


def _cap_offsets_near(refs, obstacles, near_x, near_y, w=3.0, h=1.8, max_dist=6.0,
                      min_clear=0.3):
    """Local (x, y) for a run of RC_0603-sized caps near (near_x, near_y),
    each found by _best_clear_offset() against `obstacles` PLUS every
    offset already returned earlier in this same call -- so a second cap
    doesn't land on top of the first. Returns {ref: (x, y)}; the caller
    does the actual footprint emission/placement bookkeeping.

    `max_dist` must reach past whatever body obstacle surrounds
    (near_x, near_y), or every point in range reads as unsafe and the
    search falls back to whichever edge point overlaps it least -- the
    caller is responsible for sizing it (e.g. the EC11 body obstacle
    below is +-7.7 x +-6.5, so its caller passes max_dist=9.0)."""
    obs = list(obstacles)
    out = {}
    for ref in refs:
        x, y, _clearance = _best_clear_offset(obs, near_x, near_y, w, h,
                                              max_dist=max_dist,
                                              min_clear=min_clear)
        out[ref] = (x, y)
        obs = obs + [("rect", x, y, w, h)]
    return out


# ref -> (x, y, side, rot). What placed() returns; also what the overlap
# scan and the "everything inside the outline" check both read.
PLACED = {}
# ref -> (r, c) matrix position, for every matrix-position part (switch or
# its EC11 stand-in, diode, LED). Two parts sharing a position is the one
# kind of overlap this board's layout accepts on purpose (LED/diode tucked
# under their own switch; at row0/col2 the EC11 replaces the switch and
# shares the cell with its own diode and LED).
POS_OF_REF = {}


def _place(ref, side, x, y, halfx, halfy, rot=0):
    if rot in (90, 270):
        halfx, halfy = halfy, halfx
    gm.FPBOX.append((ref, x, y, halfx, halfy))
    PLACED[ref] = (x, y, side, rot)


def _place_box(ref, side, ox, oy, xlo, xhi, ylo, yhi):
    """Like _place(), but for a footprint whose real courtyard is not
    centred on its own origin (the Gateron socket's back courtyard is
    -9.7..+7.9 in local X, not +-9.7) -- (xlo, xhi, ylo, yhi) are LOCAL
    bounds relative to the footprint origin (ox, oy). PLACED still reports
    the origin (the key centre), matching every other ref; only the
    courtyard box used for overlap-scanning is off-centre."""
    gm.FPBOX.append((ref, ox + (xlo + xhi) / 2, oy + (ylo + yhi) / 2,
                     (xhi - xlo) / 2, (yhi - ylo) / 2))
    PLACED[ref] = (ox, oy, side, 0)


def _expected_overlap_tb(r1, r2):
    p1, p2 = POS_OF_REF.get(r1), POS_OF_REF.get(r2)
    return p1 is not None and p1 == p2


def build_pcb():
    """Places every footprint and returns the .kicad_pcb text. Also
    populates the module-level PLACED/POS_OF_REF registries (read by
    placed()/check_overlaps()) and BOARD_W/BOARD_H as a side effect, so
    tests can call placed() or check_overlaps() directly without a separate
    build step."""
    global BOARD_W, BOARD_H
    gm.FPBOX.clear()
    PLACED.clear()
    POS_OF_REF.clear()
    socket_crtyd = _socket_back_courtyard()
    # Real pad/hole obstacle sets, read from each footprint's own emitted
    # text (not hand-copied) -- one per kind of neighbour a decoupling cap
    # can land beside. Every normal key has a Gateron socket; row0/col2 has
    # an EC11 instead, and the search below picks whichever one is
    # actually there.
    sw_obstacles = _probe_obstacles(gm.fp_gateron, "REF**", 0, 0, None, None, None)
    enc_obstacles = _probe_obstacles(_fp_ec11_vertical, "REF**", 0, 0, None, {})
    # EC11's own BODY (its silk envelope, +-7.7 x +-6.5 -- same numbers
    # _place(enc, ...) below uses), not just its discrete pins/legs. The
    # switch doesn't need this: everything that shares its back courtyard
    # with a switch (LED, diode, cap) sits on the BACK, physically
    # separated from the switch's own housing on the FRONT. The EC11 and
    # its debounce caps are BOTH front-side, competing for the same real
    # space its body occupies -- without this, the search reads the
    # origin (which has no pin on it) as clear and places a cap directly
    # under the encoder's own package, the same class of bug the LED
    # courtyard fix below addresses for the switch/LED/cap side.
    enc_obstacles = enc_obstacles + [("rect", 0, 0, 7.7 * 2, 6.5 * 2)]

    nets = build_nets()
    # net name -> sequential id. This board's net names (ROW0, LEDD3, ...)
    # are nothing like gm's own hardcoded NETS/NETI (that dict is the
    # RP2040 wireless board's own net list), so gm.net() -- which every
    # gm.fp_*()/gm.pad() call below threads netnames through -- is
    # repointed at OUR dict for the duration of this build. Same technique
    # generate_macropad_mini.py uses for gm._expected_overlap.
    net_names = list(nets.keys())
    gm.NETI = {n: i + 1 for i, n in enumerate(net_names)}
    gm._expected_overlap = _expected_overlap_tb

    pad_of = {}
    for net, members in nets.items():
        for ref, pad in members:
            pad_of.setdefault(ref, {})[pad] = net

    def real_pad(fp_key, logical):
        table = PAD_MAP.get(fp_key)
        return table[logical] if table else logical

    def net_on(ref, pad):
        return pad_of.get(ref, {}).get(pad)

    fps = []

    # ---- 1. key field: switches, diodes, LEDs ----
    # Diode offset (-8.5, +1.0, rot=270) and courtyard tracking are the
    # exact numbers gm.build_pcb() itself uses for its own 4x4 matrix
    # (same KEY_PITCH=19.05, same footprints) -- proven safe against both
    # the neighbouring keys (>1.5mm clear at every pitch) and the owning
    # switch's real pads (0.29mm clear, per that module's own comment).
    # -6.025mm: the north-side window centre, derived in
    # generate_kbd_rp2040.py:2050 as -(5.75+6.30)/2 -- the position that
    # file's own build_pcb() ships, after trying (and abandoning, per its
    # comment there) PITCH/2 south and 5.9mm/5.4mm south. Controller review
    # rounds 1 and 2 on Task 6: round 1 quoted the file's *prose* changelog
    # entry (lines 163-170) for "5.9mm south", which turned out to describe
    # that earlier, superseded attempt; round 2 corrected it to the actual
    # shipped offset once the code (not just the comment) was checked.
    # South put the LED's own pads inside the switch's leg NPTH holes by up
    # to 1.31mm -- north is on the empty side, away from both leg holes.
    LED_OFFSET_Y = -6.025
    for r in range(ROWS):
        for c in range(COLS):
            kx, ky = key_xy(r, c)
            d = f"D{r}{c}"
            dx, dy = kx - 8.5, ky + 1.0
            fps.append(gm.fp_diode(d, dx, dy, 270, net_on(d, "K"), net_on(d, "A"),
                                   gm.U("sym", d)))
            _place(d, "B", dx, dy, 2.5, 1.15, rot=270)
            POS_OF_REF[d] = (r, c)

            is_encoder = (r, c) == (0, 2)
            if is_encoder:
                enc = "ENC1"
                enc_pinnet = {n: net_on(enc, str(n)) for n in range(1, 6)}
                fps.append(_fp_ec11_vertical(enc, kx, ky, gm.U("sym", enc), enc_pinnet))
                _place(enc, "F", kx, ky, 7.7, 6.5)
                POS_OF_REF[enc] = (r, c)
                neighbor_obstacles = enc_obstacles

                # Encoder debounce (C10/C11, build_nets() addition from
                # controller review round 1): 100nF A-to-GND, B-to-GND, per
                # the design spec's Sec.2. Positions read from EC11's own
                # real pin/leg obstacles via _cap_offsets_near(), not
                # hand-picked -- front side (same side as ENC1 and the
                # XIAO trace they decouple, no extra via).
                # ...plus this key's own LED courtyard. Found by DRC once the
                # Edge.Cuts light window existed: this search knew about the
                # EC11's pins and body but not about RGB3, and put C10's pad
                # exactly on top of RGB3's window -- 0.00mm copper-to-edge,
                # i.e. a pad that the router would have cut in half. The
                # generator's own overlap scan could not see it either,
                # because C10 and RGB3 share matrix position (0, 2) and
                # _expected_overlap_tb() declares same-position overlaps
                # expected (front-side cap over a back-side LED normally IS
                # fine -- it stops being fine when the LED brings a hole with
                # it). Same obstacle the per-LED cap search already used.
                debounce_xy = _cap_offsets_near(
                    ["C10", "C11"],
                    enc_obstacles + [("rect", 0, LED_OFFSET_Y, 3.65 * 2, 1.87 * 2)],
                    0, 0, max_dist=9.0)
                for debounce, (ddx, ddy) in debounce_xy.items():
                    dcx, dcy = kx + ddx, ky + ddy
                    _sym, _val, _fpn, _side = AUX_PARTS[debounce]
                    fps.append(gm.fp_0603(debounce, _val, dcx, dcy, 0,
                                          gm.U("sym", debounce),
                                          net_on(debounce, "1"), net_on(debounce, "2"),
                                          side=_side))
                    _place(debounce, "F", dcx, dcy, 1.5, 0.9)
                    POS_OF_REF[debounce] = (r, c)
            else:
                sw = f"SW{r}{c}"
                fps.append(gm.fp_gateron(sw, kx, ky, net_on(sw, "1"), net_on(sw, "2"),
                                         gm.U("sym", sw)))
                sw_xlo, sw_ylo, sw_xhi, sw_yhi = socket_crtyd
                _place_box(sw, "B", kx, ky, sw_xlo, sw_xhi, sw_ylo, sw_yhi)
                POS_OF_REF[sw] = (r, c)
                neighbor_obstacles = sw_obstacles

            # Chain position must match ~/esp/SMK's
            # Sources/SMKCore/LEDChainMapping.swift `ledChainIndex()` --
            # serpentine/boustrophedon, not raster: even rows run
            # col0->COLS-1, odd rows run COLS-1->0. That function is what
            # RGBLighting.swift actually indexes into at runtime, so the
            # physical RGB{i} landing at (r, c) has to be its 1-indexed
            # chain position, not r*COLS+c+1 (raster). On a 3x3 those two
            # formulas only disagree on the odd row (row 1), which is why
            # this shipped wrong and passed review for several rounds.
            i = (r * COLS + c if r % 2 == 0 else r * COLS + (COLS - 1 - c)) + 1
            rgb = f"RGB{i}"
            lx, ly = kx, ky + LED_OFFSET_Y
            pinnet = {int(real_pad("SK6812MINI_E", k)): net_on(rgb, k)
                     for k in ("VDD", "DOUT", "GND", "DIN")}
            fps.append(_fp_sk6812mini_tb(rgb, lx, ly, gm.U("sym", rgb), pinnet))
            _place(rgb, "B", lx, ly, 3.65, 1.87)
            POS_OF_REF[rgb] = (r, c)

            # Per-LED 100nF decoupling (C1..C9, build_nets() addition from
            # controller review round 1). Controller review round 2: the
            # position search now reads whichever footprint is actually at
            # this key (the Gateron socket for 8 of the 9 keys, the EC11
            # at row0/col2) plus the LED's own courtyard, rather than one
            # offset validated against the socket only and reused
            # unchecked at row0/col2 -- that's what left C3 (this key's
            # cap) 0.05mm short of clearance against ENC1's own leg last
            # round.
            #
            # The LED's real COURTYARD (its assembly keepout, same 3.65 x
            # 1.87 half-extent passed to _place() above), not just its
            # four pads: a cap centred exactly on the LED's own origin has
            # clear COPPER (the LED's own middle has none -- its pads sit
            # out at local x=+-2.725, which is what the light escapes
            # between) but that is still the LED's own package footprint,
            # and two components cannot occupy the same physical footprint
            # regardless of whether their copper happens to miss. An
            # earlier version of this search checked only the four pads
            # and put C1 exactly on top of RGB1's own origin for precisely
            # this reason.
            led_courtyard_obstacle = [("rect", 0, LED_OFFSET_Y, 3.65 * 2, 1.87 * 2)]
            cap = f"C{i}"
            cap_xy = _cap_offsets_near([cap], neighbor_obstacles + led_courtyard_obstacle,
                                       0, LED_OFFSET_Y)
            ccx, ccy = cap_xy[cap]
            cx, cy = kx + ccx, ky + ccy
            _sym, _val, _fpn, _side = AUX_PARTS[cap]
            fps.append(gm.fp_0603(cap, _val, cx, cy, 0, gm.U("sym", cap),
                                  net_on(cap, "1"), net_on(cap, "2"), side=_side))
            _place(cap, "B", cx, cy, 1.5, 0.9)
            POS_OF_REF[cap] = (r, c)

    # ---- 2. XIAO headers, below the key field ----
    field_x0, field_y0 = key_xy(0, 0)
    field_x1, _ = key_xy(0, COLS - 1)
    _, field_y1 = key_xy(ROWS - 1, 0)
    field_cx = (field_x0 + field_x1) / 2
    matrix_max_y = field_y1 + 7.5   # switch back-courtyard reach
    xiao_y = matrix_max_y + 5 + 10.5
    fps.append(_fp_xiao_headers("U1", field_cx, xiao_y, gm.U("sym", "U1"),
                                {i: net_on("U1", str(i)) for i in range(1, 15)}))
    _place("U1", "F", field_cx, xiao_y, 10.2, 10.5)

    # ---- 2b. battery flying-lead pads (J2), beside U1 ----
    # Position is SEARCHED against everything already on the board, the same
    # way the decoupling caps are -- not picked by hand. The obstacle set
    # here is _placed_obstacles() (real courtyards, absolute coordinates)
    # rather than one footprint's local pads, because J2 has no owning
    # footprint to sit inside; it just has to miss everything.
    #
    # min_clear=1.5 (not the caps' 0.3): a soldering iron has to reach these
    # two pads with the XIAO MODULE SEATED on its headers. U1's courtyard
    # (+-10.2 x +-10.5) already covers the module's 21 x 17.5mm body, so
    # 1.5mm of clearance to that courtyard is 1.5mm of open board beyond the
    # module's own outline -- enough for an iron tip and a wire, and the
    # search will refuse to place J2 anywhere that doesn't have it.
    #
    # Seeded to U1's LEFT (-19.0mm) rather than its right: the right side at
    # this y would push the board outline out past its current 76mm width,
    # and the left side at y = xiao_y is empty board (the nearest neighbours
    # are the key field's back courtyards, which stop at y~71, and H3 at the
    # bottom-left corner).
    bat_w, bat_h = BAT_PADS_HALF[0] * 2, BAT_PADS_HALF[1] * 2
    j2x, j2y, j2_clear = _best_clear_offset(
        _placed_obstacles(), field_cx - 19.0, xiao_y, bat_w, bat_h,
        max_dist=6.0, min_clear=1.5)
    assert j2_clear >= 1.5, (
        f"J2 (battery flying-lead pads) could only reach {j2_clear:.2f}mm "
        "clearance -- a soldering iron cannot reach it with the XIAO seated")
    fps.append(_fp_bat_pads("J2", j2x, j2y, gm.U("sym", "J2"),
                            {1: net_on("J2", "1"), 2: net_on("J2", "2")}))
    _place("J2", "F", j2x, j2y, *BAT_PADS_HALF)

    # ---- 2c. VBAT sense divider (R1/R2), beside U1's pad 1 ----
    # VSYS -> R1 -> VBAT_SENSE -> R2 -> GND, midpoint on U1 pad 1 (D0 /
    # GPIO0 / ADC1_CH0). Placed with the same obstacle-aware machinery as
    # everything else, seeded near U1's own pad 1 (local -8.89, -7.62) so
    # the sense trace is short; the search pushes them clear of U1's
    # courtyard on its own, since that courtyard is in the obstacle set.
    div_near_x = field_cx - 12.5
    div_near_y = xiao_y - 7.62
    div_xy = _cap_offsets_near(["R1", "R2"], _placed_obstacles(),
                               div_near_x, div_near_y, max_dist=8.0)
    for rref in ("R1", "R2"):
        rx, ry = div_xy[rref]
        _sym, _val, _fpn, _side = AUX_PARTS[rref]
        fps.append(gm.fp_0603(rref, _val, rx, ry, 0, gm.U("sym", rref),
                              net_on(rref, "1"), net_on(rref, "2"), side=_side))
        _place(rref, _side, rx, ry, 1.5, 0.9)

    # ---- 3. level shifter, bulk cap, JST -- bottom edge ----
    bottom_y = xiao_y + 10.5 + 5 + 3.28
    fps.append(gm.fp_jst_sh("J1", field_x0, bottom_y, 0, gm.U("sym", "J1"),
                            net_on("J1", "1"), net_on("J1", "2")))
    _place("J1", "B", field_x0, bottom_y, 2.9, 3.28)

    lvl_pinnet = {int(real_pad("SOT-23-5", k)): net_on("U2", k)
                 for k in ("OE#", "A", "GND", "Y", "VCC")}
    fps.append(gm.fp_sot23_5("U2", "SN74AHCT1G125DBVR", field_cx, bottom_y, 0,
                             gm.U("sym", "U2"), lvl_pinnet))
    _place("U2", "F", field_cx, bottom_y, 1.7, 2.0)

    # U2's local decoupling (C12). Controller review (final wave): the level
    # shifter had no decoupling at all -- nearest cap was C_BULK, 19mm away
    # at the far end of the bottom edge. Seeded at U2's own VCC pad (pad 5,
    # local (-0.95, -1.3) per gm.fp_sot23_5) so the loop is short; the
    # search then walks it out clear of U2's courtyard.
    u2_vcc_x, u2_vcc_y = field_cx - 0.95, bottom_y - 1.3
    dec_xy = _cap_offsets_near(["C12"], _placed_obstacles(),
                               u2_vcc_x, u2_vcc_y - 2.5, max_dist=6.0)
    c12x, c12y = dec_xy["C12"]
    _sym, _val, _fpn, _side = AUX_PARTS["C12"]
    fps.append(gm.fp_0603("C12", _val, c12x, c12y, 0, gm.U("sym", "C12"),
                          net_on("C12", "1"), net_on("C12", "2"), side=_side))
    _place("C12", _side, c12x, c12y, 1.5, 0.9)

    # Ref C_BULK, not C1 -- C1..C12 are the per-LED / encoder-debounce /
    # level-shifter decoupling caps, so a numbered ref here would shadow one.
    # Its nets come from build_nets() like every other part's: passing
    # "VSYS"/"GND" straight to fp_0603() (as this did) kept it out of the
    # netlist build_sch() renders from, which is exactly why it was one of
    # the 12 parts missing from the schematic.
    _sym, _val, _fpn, _side = AUX_PARTS["C_BULK"]
    fps.append(gm.fp_0603("C_BULK", _val, field_x1, bottom_y, 0,
                          gm.U("sym", "C_BULK"),
                          net_on("C_BULK", "1"), net_on("C_BULK", "2"),
                          side=_side))
    _place("C_BULK", _side, field_x1, bottom_y, 1.5, 0.9)

    # ---- 4. board outline + BOARD_W/BOARD_H ----
    # Derived from the extents of everything placed so far (mounting holes
    # excluded -- they are positioned FROM the board size, so including
    # them would be circular), plus a 5mm margin. Origin is (0,0); every
    # part above already has >5mm clearance to the origin corner on its
    # own (the nearest thing, a switch back-courtyard, sits at x=15.3,
    # y=17.5), so only the far/bottom margin needs to be added explicitly.
    max_x = max(x + hx for (_ref, x, y, hx, hy) in gm.FPBOX)
    max_y = max(y + hy for (_ref, x, y, hx, hy) in gm.FPBOX)
    MARGIN = 5.0
    BOARD_W = round(max_x + MARGIN, 2)
    BOARD_H = round(max_y + MARGIN, 2)

    # ---- 5. mounting holes, corners ----
    for hi, (hx, hy) in enumerate([(MARGIN, MARGIN), (BOARD_W - MARGIN, MARGIN),
                                   (MARGIN, BOARD_H - MARGIN),
                                   (BOARD_W - MARGIN, BOARD_H - MARGIN)], start=1):
        fps.append(gm.fp_hole(f"H{hi}", hx, hy))
        _place(f"H{hi}", "F", hx, hy, 2.4, 2.4)

    nets_decl = "\n".join(f'  (net {i} "{n}")' for i, n in enumerate([""] + net_names))
    edge = (f'  (gr_rect (start 0 0) (end {BOARD_W:g} {BOARD_H:g}) '
           f'(stroke (width 0.1) (type solid)) (fill none) (layer "Edge.Cuts") '
           f'(uuid "{gm.NU("edge")}"))')
    # Title text: the original (5,4) placement sat inside H1's silkscreen
    # circle (centered at (MARGIN, MARGIN)=(5,5), radius 2.3mm, spanning
    # x=2.7..7.3, y=2.7..7.7) and clipped the top board edge. Nudging it
    # sideways to clear H1 wasn't enough on its own -- the string is long
    # enough that its right end then reached H2's circle at
    # (BOARD_W-MARGIN, MARGIN). Dropping it to y=10.5 instead clears both
    # corner holes' circles (which end at y=7.7) by the same margin
    # regardless of board width, at the cost of a couple mm of headroom
    # before the first row of components (nearest is C1 at y~15.8).
    title = (f'  (gr_text "SMK TEST BOARD -- 3x3, XIAO ESP32-C6 + EC11  rev A" '
            f'(at 7 10.5) (layer "F.SilkS") (uuid "{gm.NU("gt")}")\n'
            f'    (effects (font (size 1.2 1.2) (thickness 0.18)) (justify left)))')

    return f'''(kicad_pcb (version 20240108) (generator "pcbnew") (generator_version "8.0")
  (general (thickness 1.6) (legacy_teardrops no))
  (paper "A4")
  (title_block
    (title "SMK Test Board -- 3x3 macropad, XIAO ESP32-C6 + EC11 + 9x SK6812MINI-E")
    (rev "A")
    (comment 1 "Bring-up board for SMK's matrix/RMT-LED/BatteryMonitor code paths on ESP32-C6")
  )
  (layers
    (0 "F.Cu" signal)
    (31 "B.Cu" signal)
    (32 "B.Adhes" user "B.Adhesive")
    (33 "F.Adhes" user "F.Adhesive")
    (34 "B.Paste" user)
    (35 "F.Paste" user)
    (36 "B.SilkS" user "B.Silkscreen")
    (37 "F.SilkS" user "F.Silkscreen")
    (38 "B.Mask" user)
    (39 "F.Mask" user)
    (40 "Dwgs.User" user "User.Drawings")
    (41 "Cmts.User" user "User.Comments")
    (42 "Eco1.User" user "User.Eco1")
    (43 "Eco2.User" user "User.Eco2")
    (44 "Edge.Cuts" user)
    (45 "Margin" user)
    (46 "B.CrtYd" user "B.Courtyard")
    (47 "F.CrtYd" user "F.Courtyard")
    (48 "B.Fab" user)
    (49 "F.Fab" user)
  )
  (setup
    (stackup
      (layer "F.Cu" (type "copper") (thickness 0.035))
      (layer "dielectric 1" (type "core") (thickness 1.51) (material "FR4")
        (epsilon_r 4.5) (loss_tangent 0.02))
      (layer "B.Cu" (type "copper") (thickness 0.035))
      (layer "F.SilkS" (type "Top Silk Screen"))
      (layer "F.Paste" (type "Top Solder Paste"))
      (layer "F.Mask" (type "Top Solder Mask") (thickness 0.01))
      (layer "B.Mask" (type "Bottom Solder Mask") (thickness 0.01))
      (layer "B.Paste" (type "Bottom Solder Paste"))
      (layer "B.SilkS" (type "Bottom Silk Screen"))
      (copper_finish "None")
      (dielectric_constraints no)
    )
    (pad_to_mask_clearance 0)
    (allow_soldermask_bridges_in_footprints no)
    (pcbplotparams
      (layerselection 0x00010fc_ffffffff)
      (plot_on_all_layers_selection 0x0000000_00000000)
      (disableapertmacros no)
      (usegerberextensions no)
      (usegerberattributes yes)
      (usegerberadvancedattributes yes)
      (creategerberjobfile yes)
      (dashed_line_dash_ratio 12.000000)
      (dashed_line_gap_ratio 3.000000)
      (svgprecision 4)
      (plotframeref no)
      (viasonmask no)
      (mode 1)
      (useauxorigin no)
      (hpglpennumber 1)
      (hpglpenspeed 20)
      (hpglpendiameter 15.000000)
      (pdf_front_fp_property_popups yes)
      (pdf_back_fp_property_popups yes)
      (dxfpolygonmode yes)
      (dxfimperialunits yes)
      (dxfusepcbnewfont yes)
      (psnegative no)
      (psa4output no)
      (plotreference yes)
      (plotvalue yes)
      (plotfptext yes)
      (plotinvisibletext no)
      (sketchpadsonfab no)
      (subtractmaskfromsilk no)
      (outputformat 1)
      (mirror no)
      (drillshape 1)
      (scaleselection 1)
      (outputdirectory "")
    )
  )
{nets_decl}
{"".join(fps)}
{edge}
{title}
)
'''


def placed():
    """ref -> (x, y, side, rot) for every footprint on the board."""
    build_pcb()
    return dict(PLACED)


def check_overlaps():
    """(unexpected, expected) courtyard bounding-box collisions -- a thin
    wrapper around gm's own scanning loop (FPBOX pairwise comparison), with
    this board's own _expected_overlap_tb (matrix-position matching, not
    gm's Dn/SWn ref-name pattern -- this board's LEDs don't fit that
    pattern) installed first."""
    build_pcb()
    gm._expected_overlap = _expected_overlap_tb
    return gm.check_overlaps()


BOARD_W = None
BOARD_H = None


# ============================================ PROJECT + LIBRARY TABLE ======
# Spec Sec.5 promises smk_test_board.kicad_{pro,sch,pcb}; only the last two
# were ever written, and no fp-lib-table was committed either. That second
# omission is the real cause of DRC's 46 `lib_footprint_issues` warnings --
# docs/fabrication.md used to blame "running kicad-cli outside the full KiCad
# project environment", which is plausible and wrong: kicad-cli reads the
# project directory perfectly well, there was simply no library registered in
# it for either `smk_test_board:` or `kbd:` to resolve against.
#
# `kbd:` is the harder half. gm.fp_gateron()/fp_diode()/fp_0603()/fp_jst_sh()/
# fp_sot23_5()/fp_hole() all hardcode the `kbd:` prefix, and the only
# kbd.pretty on this machine lives inside a SIBLING repo
# (~/esp/SMK_macro_pad/smk_macropad/kbd.pretty) -- an absolute path outside
# this project, which is not something to write into a committed lib table.
# So the six gm footprints this board actually uses are re-emitted into the
# project's own kbd.pretty from gm's own generators (the same export_libs()
# technique gm uses for its own project), and the lib table points at that.
# The board is then self-contained: both libraries resolve from ${KIPRJMOD}.
GM_LIB_FOOTPRINTS = [
    ("SW_Gateron_KS33_HS", lambda: gm.fp_gateron("REF**", 0, 0, None, None, None)),
    ("D_SOD-123_Back", lambda: gm.fp_diode("REF**", 0, 0, 0, None, None, None)),
    ("RC_0603", lambda: gm.fp_0603("REF**", "0603", 0, 0, 0, None, None, None)),
    ("JST_SH_SM02B_2pin_Back", lambda: gm.fp_jst_sh("REF**", 0, 0, 0, None, None, None)),
    ("SOT-23-5", lambda: gm.fp_sot23_5("REF**", "SOT-23-5", 0, 0, 0, None, {})),
    ("MountingHole_M2", lambda: gm.fp_hole("REF**", 0, 0)),
]


def write_project_libs():
    """Write the project's kbd.pretty, fp-lib-table and .kicad_pro."""
    pretty = os.path.join(PRJDIR, "kbd.pretty")
    os.makedirs(pretty, exist_ok=True)
    for name, build in GM_LIB_FOOTPRINTS:
        txt = build().strip()
        assert txt.startswith("(footprint"), name
        txt = txt.replace(f'(footprint "kbd:{name}"',
                          f'(footprint "{name}" (version 20240108) '
                          f'(generator "pcbnew")', 1)
        with open(os.path.join(pretty, f"{name}.kicad_mod"), "w") as f:
            f.write(txt + "\n")

    with open(os.path.join(PRJDIR, "fp-lib-table"), "w") as f:
        f.write(
            '(fp_lib_table\n'
            '  (version 7)\n'
            '  (lib (name "smk_test_board")(type "KiCad")'
            '(uri "${KIPRJMOD}/../smk_test_board.pretty")(options "")'
            '(descr "test board footprints drawn by this project"))\n'
            '  (lib (name "kbd")(type "KiCad")(uri "${KIPRJMOD}/kbd.pretty")'
            '(options "")(descr "footprints re-emitted from '
            'generate_macropad.py\'s own generators"))\n'
            ')\n')

    pro_path = os.path.join(PRJDIR, f"{PROJ}.kicad_pro")
    with open(pro_path, "w") as f:
        f.write(build_pro())
    return pro_path


def build_pro():
    """A minimal, valid KiCad 8 project file. Modelled on gm.build_pro() but
    written locally: gm's bakes its own PROJ name, root-sheet UUID and the
    4-layer/1oz JLCPCB rule set for the RP2040 wireless board into the JSON,
    none of which describe this 2-layer board."""
    return json.dumps({
        "board": {
            "3dviewports": [], "design_settings": {
                "defaults": {"text_height": 1.0, "text_width": 1.0,
                             "text_thickness": 0.15, "line_thickness": 0.15},
                # JLCPCB 2-layer/1oz floors; nothing on this board is close
                # to any of them (it ships unrouted -- no tracks or vias at
                # all), but leaving KiCad's looser defaults in place would
                # let a future routing pass pass DRC and fail the fab.
                "rules": {
                    "min_clearance": 0.127,
                    # 0.2, not KiCad's 0.5 default and not the 0.3 a fab
                    # usually "recommends". The tightest copper-to-edge on
                    # this board is 0.2467mm, and all 36 instances of it are
                    # an SK6812MINI-E pad against ITS OWN light window --
                    # geometry that comes with the stock KiCad
                    # LED_SK6812MINI-E_3.2x2.8mm_P1.5mm_ReverseMount
                    # footprint, used unmodified, and that the sibling board
                    # ~/esp/SMK_Keyboard/smk_kbd_rp2040 has already
                    # fabricated 58 times. Note KiCad measures to the OUTER
                    # EDGE of the 0.12mm-wide Edge.Cuts graphic; the gap to
                    # the nominal cut path (what the router actually
                    # follows) is 0.3067mm. Left at 0.5 or 0.3 this rule
                    # reports 36 errors that are inherent to a proven part
                    # and cannot be fixed without redrawing the footprint --
                    # which would break the light window it exists for.
                    # docs/fabrication.md's ordering checklist carries the
                    # matching instruction to confirm the fab's
                    # copper-to-slot capability covers 0.25mm.
                    "min_copper_edge_clearance": 0.2,
                    "min_hole_clearance": 0.20,
                    "min_hole_to_hole": 0.25,
                    "min_track_width": 0.127,
                    "min_through_hole_diameter": 0.3,
                    "min_via_diameter": 0.45,
                    "min_via_annular_width": 0.15,
                    "min_text_height": 1.0,
                    "min_text_thickness": 0.15,
                },
            },
            "layer_presets": [], "viewports": [],
        },
        "boards": [], "cvpcb": {"equivalence_files": []},
        "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
        "meta": {"filename": f"{PROJ}.kicad_pro", "version": 1},
        "net_settings": {
            "classes": [{
                "name": "Default", "priority": 2147483647,
                "clearance": 0.2, "track_width": 0.25,
                "via_diameter": 0.6, "via_drill": 0.3,
                "microvia_diameter": 0.3, "microvia_drill": 0.1,
                "diff_pair_width": 0.2, "diff_pair_gap": 0.25,
                "diff_pair_via_gap": 0.25,
                "bus_width": 12, "line_style": 0, "wire_width": 6,
                "pcb_color": "rgba(0, 0, 0, 0.000)",
                "schematic_color": "rgba(0, 0, 0, 0.000)",
            }],
            "meta": {"version": 3},
        },
        "pcbnew": {"last_paths": {}, "page_layout_descr_file": ""},
        "schematic": {"annotate_start_num": 0, "drawing": {},
                      "legacy_lib_dir": "", "legacy_lib_list": [],
                      "meta": {"version": 1}},
        "sheets": [[gm.U("smk-test-board-root-sheet"), "Root"]],
        "text_variables": {},
    }, indent=2) + "\n"


def main():
    os.makedirs(PRJDIR, exist_ok=True)
    sch_path = os.path.join(PRJDIR, f"{PROJ}.kicad_sch")
    # build_sch() ONCE. It was called twice here (the second only to compute
    # a size for the log line), and since gm.NU() bumps a module-global
    # counter, that second call shifted every UUID the PCB build then
    # emitted -- so every regeneration produced a wholly different-looking
    # .kicad_pcb and "did the board actually change?" was unanswerable by
    # diff. Regeneration is now byte-identical for an unchanged generator.
    sch = build_sch()
    with open(sch_path, "w") as f:
        f.write(sch)
    print(f"wrote {sch_path}  ({len(sch) // 1024} kB)")

    pcb = build_pcb()
    pcb_path = os.path.join(PRJDIR, f"{PROJ}.kicad_pcb")
    with open(pcb_path, "w") as f:
        f.write(pcb)
    print(f"wrote {pcb_path}  ({len(pcb) // 1024} kB)")
    print(gm.check_parens(pcb, f"{PROJ}.kicad_pcb"))

    print(f"wrote {write_project_libs()}, fp-lib-table, kbd.pretty "
          f"({len(GM_LIB_FOOTPRINTS)} footprints)")

    unexpected, expected = check_overlaps()
    print("overlap scan: {} expected (each key's diode/LED under its own "
          "switch, or the EC11 sharing row0/col2 with its own diode/LED), "
          "{} unexpected".format(len(expected), len(unexpected)))
    if unexpected:
        print("UNEXPECTED OVERLAPS -- investigate:")
        for r1, r2, amt in unexpected:
            print(f"  {r1} <-> {r2}: overlap ~{amt:.2f}mm (courtyard bounding boxes)")


if __name__ == "__main__":
    main()
