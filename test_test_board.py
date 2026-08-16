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
    shipped board and abandoned -- that is the side the leg holes are on."""
    p = tb.placed()
    for r in range(tb.ROWS):
        for c in range(tb.COLS):
            kx, ky = tb.key_xy(r, c)
            lx, ly, side, _ = p[f"RGB{r * tb.COLS + c + 1}"]
            assert side == "B", "SK6812MINI-E is reverse-mount: back side"
            assert abs(lx - kx) < 0.1, f"RGB under key {r},{c} off-axis by {lx-kx:.2f}"
            assert abs(ly - (ky - 6.025)) < 0.1, f"RGB y offset {ly-ky:.2f}, want -6.025"


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
