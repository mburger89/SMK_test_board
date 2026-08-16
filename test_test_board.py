#!/usr/bin/env python3
import math
import re

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
    assert tb.KEY_PITCH == 19.05, "19.05mm is the keycap pitch, not a tunable"
    x0, y0 = tb.key_xy(0, 0)
    x1, _ = tb.key_xy(0, 1)
    _, y1 = tb.key_xy(1, 0)
    assert abs((x1 - x0) - tb.KEY_PITCH) < 1e-6
    assert abs((y1 - y0) - tb.KEY_PITCH) < 1e-6


def test_every_matrix_position_has_a_diode_in_the_right_direction():
    """Diode anode to column, cathode to row -- the direction current flows
    when a driven column goes high. Reversed diodes give a matrix that reads
    nothing, and it is invisible until the board is assembled.

    Position (0, 2) is excluded from the SWxx/COL assertions: the EC11's
    integrated push switch occupies that matrix position instead of an
    ordinary SWxx (see the design spec and build_nets()'s own note), so
    there is no SW02 to assert against. Its diode (D02) and the encoder's
    press wiring are asserted separately below.
    """
    nets = tb.build_nets()
    for r in range(tb.ROWS):
        for c in range(tb.COLS):
            d = f"D{r}{c}"
            assert (d, "K") in nets[f"ROW{r}"], f"{d} cathode not on ROW{r}"
            if (r, c) == (0, 2):
                continue          # the EC11's push switch takes this position
            sw = f"SW{r}{c}"
            assert (sw, "1") in nets[f"COL{c}"], f"{sw} not on COL{c}"
            assert (d, "A") in nets[f"SW{r}{c}_N"], f"{d} anode not on {sw}"

    # the encoder press is an ordinary matrix key: COL2 -> ENC1 -> D02 -> ROW0
    assert ("ENC1", "4") in nets["COL2"]
    assert ("ENC1", "5") in nets["SW02_N"]
    assert ("D02", "A") in nets["SW02_N"]


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


def test_no_net_has_fewer_than_two_members():
    """A one-member net is a floating pin -- the general form of the +3V3
    bug a controller review caught here: build_nets() used to add U1 pad 12
    to a "+3V3" net with nothing else ever on it. The fix was to stop
    creating that net at all (nothing on this board consumes regulated
    3.3V), not to pad it out with an invented consumer. This test is the
    guard against that class of bug recurring, for +3V3 or any other net."""
    nets = tb.build_nets()
    floating = {net: members for net, members in nets.items() if len(members) < 2}
    assert not floating, f"floating (single-member) nets: {floating}"


def test_leds_sit_at_the_north_led_window():
    """-6.025mm: the north-side window centre, derived in
    generate_kbd_rp2040.py:2050 as -(5.75+6.30)/2. South was tried on the
    shipped board and abandoned -- that is the side the leg holes are on.

    Looks each RGB ref up by its recorded (r, c) in POS_OF_REF rather than
    computing a ref name from (r, c) inline, so this test doesn't itself
    depend on which chain-numbering scheme is in use (raster vs
    serpentine) -- that's covered separately, below."""
    p = tb.placed()
    for ref, (r, c) in tb.POS_OF_REF.items():
        if not ref.startswith("RGB"):
            continue
        kx, ky = tb.key_xy(r, c)
        lx, ly, side, _ = p[ref]
        assert side == "B", "SK6812MINI-E is reverse-mount: back side"
        assert abs(lx - kx) < 0.1, f"{ref} under key {r},{c} off-axis by {lx-kx:.2f}"
        assert abs(ly - (ky - 6.025)) < 0.1, f"{ref} y offset {ly-ky:.2f}, want -6.025"


def test_led_chain_order_matches_firmwares_serpentine_mapping():
    """The physical RGB{i} at key (r, c) must be that key's 1-indexed
    chain position per ~/esp/SMK's Sources/SMKCore/LEDChainMapping.swift
    `ledChainIndex()` -- the function RGBLighting.swift actually indexes
    into at runtime (Sources/smk/RGBLighting.swift). That function is
    serpentine/boustrophedon: even rows run col0->COLS-1, odd rows run
    COLS-1->0, transcribed here since it's Swift and this suite is
    Python. A raster formula (r*COLS+c+1) instead of this one shipped
    once and passed review for several rounds, because raster and
    serpentine only disagree on odd rows -- ROWS=3 has exactly one (row
    1), so checking a couple of positions would have missed it too, this
    checks all nine."""
    tb.placed()  # populates POS_OF_REF as a side effect
    for r in range(tb.ROWS):
        for c in range(tb.COLS):
            if r % 2 == 0:
                chain_index = r * tb.COLS + c
            else:
                chain_index = r * tb.COLS + (tb.COLS - 1 - c)
            rgb = f"RGB{chain_index + 1}"
            assert tb.POS_OF_REF[rgb] == (r, c), (
                f"{rgb} is ledChainIndex's LED for key ({r},{c}), but the "
                f"generator placed it at {tb.POS_OF_REF[rgb]}"
            )


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


def test_schematic_has_every_part_the_pcb_has():
    """The schematic and the PCB must carry the identical ref set.

    They did not. build_sch() assembled the sheet purely from hand-written
    per-block code, so C1-C9, C10, C11 and C_BULK -- 12 parts that build_nets()
    wired and build_pcb() placed -- existed on the board and nowhere in the
    schematic. Boards were unaffected (the PCB is the fab source), but any
    schematic-derived BOM or netlist was wrong by 12 parts and
    `kicad-cli pcb drc --schematic-parity` could not be used at all.

    Checking the two documents against each other, rather than checking the
    schematic against a hand-maintained list, is the point: a part added to
    build_nets()/build_pcb() and forgotten in build_sch() fails here.
    """
    sch = tb.build_sch()
    # Symbol INSTANCES only -- `(symbol (lib_id "kbd:X") ... )`. The
    # lib_symbols block above them carries its own "Reference" properties
    # holding ref PREFIXES ("C", "D", "SW"), which are not parts.
    sch_refs = set(re.findall(
        r'\(symbol \(lib_id "[^"]+"\)[^()]*(?:\([^()]*\)[^()]*)*?'
        r'\(property "Reference" "([^"]+)"', sch))
    sch_refs = {r for r in sch_refs if not r.startswith("#")}   # power ports
    pcb_refs = set(tb.placed())
    # Mounting holes are PCB-only mechanical items by design -- they have no
    # electrical existence and gm.fp_hole() marks them exclude_from_bom.
    pcb_refs -= {r for r in pcb_refs if re.fullmatch(r"H\d+", r)}
    assert sch_refs == pcb_refs, (
        f"only in schematic: {sorted(sch_refs - pcb_refs)}; "
        f"only on PCB: {sorted(pcb_refs - sch_refs)}")


def test_every_netted_ref_is_placed_on_the_pcb():
    """The other direction: a ref that build_nets() wires but build_pcb()
    never places is a net that cannot exist on a physical board."""
    nets = tb.build_nets()
    netted = {ref for members in nets.values() for ref, _pad in members}
    placed = set(tb.placed())
    assert netted <= placed, f"wired but never placed: {sorted(netted - placed)}"


def test_battery_actually_reaches_the_xiao():
    """J1 (the JST cell connector) feeds VSYS, which powers all nine SK6812
    VDD pins, their decoupling caps, C_BULK and U2's VCC -- but nothing tied
    VSYS to the XIAO, so the board could not run untethered, the XIAO's
    onboard charger was never in circuit with the cell, and on USB with no
    cell fitted the entire LED chain and the level shifter were dead.

    The XIAO's BAT+/BAT- are solder pads on the UNDERSIDE of the module and
    it seats on female headers, so no PCB pad can mate with them --
    XIAO_ESP32C6_HEADERS is 14 pads with no BAT pad and that is correct. The
    connection is two hand-soldered flying leads to J2, a labelled
    through-hole pad pair.
    """
    nets = tb.build_nets()
    assert ("J2", "1") in nets["VSYS"], "J2 pad 1 (BAT+) not on VSYS"
    assert ("J2", "2") in nets["GND"], "J2 pad 2 (BAT-) not on GND"
    assert ("J1", "1") in nets["VSYS"], "JST no longer feeds VSYS"

    p = tb.placed()
    assert "J2" in p, "battery flying-lead pads not placed"
    j2x, j2y, side, _rot = p["J2"]
    assert side == "F", "J2 must be reachable from the component side"
    # These take hand-soldered wire, so they must be plated THROUGH-HOLE; an
    # SMD pad tears off the first time the lead is tugged.
    fp = tb._fp_bat_pads("J2", 0, 0, None, {})
    pads = re.findall(r'\(pad "(\d)" (\S+) ', fp)
    assert len(pads) == 2, f"expected 2 battery pads, got {pads}"
    assert all(kind == "thru_hole" for _n, kind in pads), (
        f"battery pads must be through-hole, got {pads}")
    # Polarity must be unmistakable: a reversed lead puts a Li-ion cell
    # backwards into the XIAO.
    assert '"BAT+"' in fp and '"BAT-"' in fp, "battery pads lack polarity silk"

    # And it has to be solderable with the XIAO seated: U1's courtyard
    # (+-10.2 x +-10.5) is bigger than the module's own 21 x 17.5mm body, so
    # clearing that box at all means clearing the module.
    ux, uy, _s, _r = p["U1"]
    gap_x = abs(j2x - ux) - (10.2 + tb.BAT_PADS_HALF[0])
    gap_y = abs(j2y - uy) - (10.5 + tb.BAT_PADS_HALF[1])
    assert max(gap_x, gap_y) >= 1.0, (
        f"J2 is only {max(gap_x, gap_y):.2f}mm clear of the seated XIAO")


def test_vbat_sense_is_divided_and_wired():
    """PIN["VBAT_SENSE"] existed and drew a schematic port, but build_nets()
    referenced it zero times -- U1 pad 1 was floating while firmware read
    ADC1_CH0 as a battery voltage.

    The design spec's Sec.4 claimed the XIAO ESP32-C6 "already carries a 1:2
    divider on A0". It does not; that is the C3/S3 generation. Seeed's
    ESP32-C6 guidance calls for an external 200k/200k pair, which is what
    R1/R2 are. 200k keeps the standing drain near 10uA at 4.2V, which matters
    on a coin-sized cell, and the exact 1:2 ratio is what firmware's
    `vbatDividerRatio = 2` already assumes -- firmware stays correct and
    unchanged.
    """
    nets = tb.build_nets()
    assert ("U1", "1") in nets["VBAT_SENSE"], "U1 pad 1 (ADC1_CH0) unwired"
    assert ("R1", "1") in nets["VSYS"], "divider high side not on VSYS"
    assert ("R1", "2") in nets["VBAT_SENSE"], "R1 not on the divider midpoint"
    assert ("R2", "1") in nets["VBAT_SENSE"], "R2 not on the divider midpoint"
    assert ("R2", "2") in nets["GND"], "divider low side not on GND"
    # Equal legs, or the ratio isn't 2 and the firmware maths is wrong.
    assert tb.AUX_PARTS["R1"][1] == tb.AUX_PARTS["R2"][1] == "200k"
    assert {"R1", "R2"} <= set(tb.placed())


def test_level_shifter_has_local_decoupling():
    """U2 (SN74AHCT1G125DBVR) drives the LED data line and had nothing on
    VCC; the nearest cap was C_BULK, 19mm away at the other end of the bottom
    edge. C_BULK is a reservoir, not decoupling."""
    nets = tb.build_nets()
    assert ("C12", "1") in nets["VSYS"] and ("C12", "2") in nets["GND"]
    p = tb.placed()
    (cx, cy, _cs, _cr), (ux, uy, _us, _ur) = p["C12"], p["U2"]
    dist = math.hypot(cx - ux, cy - uy)
    assert dist < 5.0, f"C12 is {dist:.1f}mm from U2 -- not local decoupling"


def test_back_side_passives_are_all_nonpolar():
    """gm.fp_0603(side="B") mirrors a footprint about the Y axis (x -> -x)
    where KiCad's own flip-to-back mirrors about the X axis (y -> -y). The
    two differ by a 180-degree rotation, which is why every back-side 0603 on
    this board draws a `lib_footprint_mismatch` DRC warning.

    For a symmetric 0603 the copper, mask, paste, silk and fab geometry are
    identical either way -- only which pad is numbered 1 changes. That is
    harmless for a non-polar part and WRONG for a polarised one (an LED, a
    tantalum, a diode), which would end up reversed on the board with nothing
    but a warning to say so.

    generate_macropad.py is shared with four other generated boards, so the
    convention is not changed here. This is the guard instead: every part this
    board places back-side through that helper must be non-polar.
    """
    NONPOLAR_VALUES = {"100n", "100u", "200k"}   # ceramics and resistors
    placed = tb.placed()
    for ref, (_x, _y, side, _rot) in placed.items():
        if side != "B" or ref not in tb.AUX_PARTS:
            continue
        _sym, val, fpname, _side = tb.AUX_PARTS[ref]
        assert fpname == "RC_0603", f"{ref} is not an RC_0603"
        assert val in NONPOLAR_VALUES, (
            f"{ref} ({val}) is placed back-side through gm.fp_0603(side='B'), "
            "whose mirror convention swaps pad 1 and pad 2 relative to "
            "KiCad's own flip. That is only safe for a non-polar part.")
