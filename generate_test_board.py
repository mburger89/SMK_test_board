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

    add("VSYS", "J1", "1")
    add("GND", "J1", "2")
    # U1 pad 12 (+3V3, the XIAO's own regulated logic rail) is left
    # unwired: nothing on this board consumes regulated 3.3V -- the LEDs
    # are deliberately on VSYS (see above) and the level shifter is now a
    # single VSYS-rail part, so there is no +3V3 net at all.
    add("GND", "U1", "13")
    return nets


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
    ("POWER  (JST battery input)", 15.24, 226.06, 96.52, 250.19),
]


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
# Footprint-instantiation helpers for the three parts gm.py has no generator
# for (SK6812MINI_E, XIAO_ESP32C6_HEADERS, EC11_VERTICAL). Built from gm's
# own low-level s-expression primitives (fp_header/pad/fpline/fprect/npth/
# model) -- "the geometry and s-expression helpers come from
# generate_macropad.py" per this project's own module docstring -- rather
# than hand-rolling a parallel set. Geometry matches this project's own
# smk_test_board.pretty/*.kicad_mod byte-for-byte (those files are what
# Tasks 1/3/4 already drew and proved); this just re-renders the same
# numbers as a positioned PCB instance instead of an unplaced library
# master. Every part below is placed at rot=0 (or SK6812MINI_E's fixed
# rot=180, matching its own reverse-mount library file), so none of this
# needs to reason about how a rotated footprint's pad-local angle composes
# with its parent's -- gm.fp_gateron/fp_diode (called directly, unmodified,
# for the two footprints that already have generators) are the only parts
# of this board placed with rot != 0, and they carry their own proven
# rotation handling.

def _fp_sk6812mini_tb(ref, x, y, path_uuid, pinnet):
    """SK6812MINI-E, reverse-mount, back side. pinnet keys are footprint pad
    numbers (1=VDD, 2=DOUT, 3=GND, 4=DIN, per PAD_MAP)."""
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
    b.append(gm.fprect(-8.75, -10.5, 8.75, 10.5, "F.Fab"))
    b.append(gm.fprect(-10.2, -10.5, 10.2, 10.5, "F.SilkS", 0.12))
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
                      ref_at=(0, -8), val_at=(0, 8), path_uuid=path_uuid)
    b = []
    b.append(gm.fprect(-6, -6, 6, 6, "F.Fab"))
    b.append(gm.fprect(-7.7, -6.5, 7.7, 6.5, "F.SilkS", 0.12))
    for num, px, py, shape in [(1, -2.5, 3.25, "rect"), (2, 0, 3.25, "circle"),
                                (3, 2.5, 3.25, "circle"), (4, -2.5, -3.25, "circle"),
                                (5, 2.5, -3.25, "circle")]:
        b.append(gm.pad(num, "thru_hole", shape, px, py, 1.6, 1.6,
                        '"*.Cu" "*.Mask"', pinnet.get(num), drill=1.0))
    b.append(gm.npth(-5.6, 0, 3.2))
    b.append(gm.npth(5.6, 0, 3.2))
    return s + "\n".join(b) + "\n  )\n"


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


def _cap_offsets_near(refs, obstacles, near_x, near_y, w=3.0, h=1.8, max_dist=6.0):
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
        x, y, _clearance = _best_clear_offset(obs, near_x, near_y, w, h, max_dist=max_dist)
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
                debounce_xy = _cap_offsets_near(["C10", "C11"], enc_obstacles, 0, 0,
                                                max_dist=9.0)
                for debounce, (ddx, ddy) in debounce_xy.items():
                    dcx, dcy = kx + ddx, ky + ddy
                    fps.append(gm.fp_0603(debounce, "100n", dcx, dcy, 0,
                                          gm.U("sym", debounce),
                                          net_on(debounce, "1"), net_on(debounce, "2")))
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

            i = r * COLS + c + 1
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
            fps.append(gm.fp_0603(cap, "100n", cx, cy, 0, gm.U("sym", cap),
                                  net_on(cap, "1"), net_on(cap, "2"), side="B"))
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

    # Ref C_BULK, not C1 -- C1..C9 are now the per-LED decoupling caps
    # (build_nets()) and C10/C11 the encoder debounce caps; this bulk cap
    # has no build_nets() entry of its own (VSYS/GND are passed directly),
    # so any non-colliding name works, but reusing "C1" here would shadow
    # a real, netted ref.
    fps.append(gm.fp_0603("C_BULK", "100u", field_x1, bottom_y, 0, gm.U("sym", "C_BULK"),
                          "VSYS", "GND"))
    _place("C_BULK", "F", field_x1, bottom_y, 1.5, 0.9)

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
    title = (f'  (gr_text "SMK TEST BOARD -- 3x3, XIAO ESP32-C6 + EC11  rev A" '
            f'(at 5 4) (layer "F.SilkS") (uuid "{gm.NU("gt")}")\n'
            f'    (effects (font (size 2 2) (thickness 0.3)) (justify left)))')

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


def main():
    os.makedirs(PRJDIR, exist_ok=True)
    sch_path = os.path.join(PRJDIR, f"{PROJ}.kicad_sch")
    with open(sch_path, "w") as f:
        f.write(build_sch())
    print(f"wrote {sch_path}  ({len(build_sch()) // 1024} kB)")

    pcb = build_pcb()
    pcb_path = os.path.join(PRJDIR, f"{PROJ}.kicad_pcb")
    with open(pcb_path, "w") as f:
        f.write(pcb)
    print(f"wrote {pcb_path}  ({len(pcb) // 1024} kB)")
    print(gm.check_parens(pcb, f"{PROJ}.kicad_pcb"))

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
