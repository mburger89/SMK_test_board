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


# ============================================================ NETLIST ======
# Logical pad names, not footprint pad numbers -- "A"/"K" for diodes, "1"/"2"
# for switches, "VDD"/"GND"/"DIN"/"DOUT" for the LEDs. build_sch() translates
# through PAD_MAP on the way out. Most refs (XIAO pads, the Gateron switches,
# the EC11, the JST connector) already use numeric footprint pad numbers
# directly as their logical name, so PAD_MAP only needs entries for the two
# footprints where that isn't true.
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
    add("COL2", "ENC1", "4")                      # push switch: COL2 side
    add("SW02_N", "ENC1", "5")                    # push switch: diode side
    add("SW02_N", "D02", "A")                     # D02 anode meets the switch

    add("VSYS", "J1", "1")
    add("GND", "J1", "2")
    add("+3V3", "U1", "12")
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

    # --- diode (pin "1"=A, pin "2"=K, per PAD_MAP) ---
    diode_body = (
        '        (polyline (pts (xy 1.27 1.27) (xy 1.27 -1.27)) (stroke (width 0.254) (type default)) (fill (type none)))\n'
        '        (polyline (pts (xy -1.27 1.27) (xy -1.27 -1.27) (xy 1.27 0) (xy -1.27 1.27)) (stroke (width 0.254) (type default)) (fill (type outline)))\n'
    )
    L.append(_two_pin_named("D_kbd", "D", "1N4148W", diode_body,
                             ("A", "1"), ("K", "2")))

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

    # --- level shifter: schematic-only 2-terminal placeholder. build_nets()
    # only defines IN/OUT (no VCC/GND/OE#), so those real pins on whatever
    # part gets chosen (SN74AHCT1G125DBVR SOT-23-5 is the sibling keyboard
    # project's precedent, see generate_kbd_rp2040.py) are deliberately not
    # modeled here rather than left dangling/unwired in the schematic.
    lvl_body = '        (rectangle (start -3.81 2.54) (end 3.81 -2.54) (stroke (width 0.254) (type default)) (fill (type none)))\n'
    L.append(_two_pin_named("LVL_SHIFT_tb", "U",
                             "LEVEL SHIFTER (VCC/GND/OE# not modeled -- see note)",
                             lvl_body, ("IN", "IN"), ("OUT", "OUT"), pin_x=3.81))

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
            if (r, c) == (0, 2):
                # No SW02: the diode's anode is fed straight from SW02_N
                # (the EC11 push switch, wired in the encoder block).
                dx = xo + col_dx / 2
                attach(net_on(d, "A"), dx - 3.81, yo, "L")
                a_pad = real_pad(d_footprint, "A")
                k_pad = real_pad(d_footprint, "K")
                parts.append(gm.sym_inst("D_kbd", d, "1N4148W", dx, yo, 0,
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
            parts.append(gm.sym_inst("D_kbd", d, "1N4148W", dx, yo, 0,
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
    parts.append(gm.sym_inst("LVL_SHIFT_tb", "U2",
                              "LEVEL SHIFTER (part TBD; VCC/GND/OE# not modeled)",
                              lx0, ly0, 0, ["IN", "OUT"], ""))
    attach(net_on("U2", "IN"), lx0 - 3.81, ly0, "L")
    attach(net_on("U2", "OUT"), lx0 + 3.81, ly0, "R")

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


def main():
    os.makedirs(PRJDIR, exist_ok=True)
    sch_path = os.path.join(PRJDIR, f"{PROJ}.kicad_sch")
    with open(sch_path, "w") as f:
        f.write(build_sch())
    print(f"wrote {sch_path}")


if __name__ == "__main__":
    main()
