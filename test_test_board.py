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
