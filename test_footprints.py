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
    "MountingHole_M2": 1,
    "JST_SH_SM02B_2pin_Back": 2,
    "XIAO_ESP32C6_HEADERS": 14,   # 2 x 1x7, 2.54mm pitch
    "EC11_VERTICAL": 5,   # A, C, B + 2 switch terminals
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


def test_xiao_header_geometry():
    """Two 1x7 rows on a 2.54mm pitch, 17.78mm apart.

    Wrong pitch or row spacing means the XIAO does not seat, which is only
    discoverable after fabrication -- hence checking it here.
    """
    text = open(os.path.join(LIB, "XIAO_ESP32C6_HEADERS.kicad_mod")).read()
    # Extract pad lines only to avoid matching fp_text entries
    pads = [ln for ln in text.splitlines() if ln.strip().startswith("(pad ")]
    ats = []
    for ln in pads:
        m = re.search(r"\(at (-?[\d.]+) (-?[\d.]+)\)", ln)
        if m:
            ats.append((float(m.group(1)), float(m.group(2))))
    xs = sorted({round(x, 2) for x, _ in ats})
    ys = sorted({round(y, 2) for _, y in ats})
    assert len(xs) == 2, f"expected 2 pad columns, got {xs}"
    assert abs((xs[1] - xs[0]) - 17.78) < 0.01, f"row spacing {xs[1] - xs[0]}"
    pitches = {round(b - a, 2) for a, b in zip(ys, ys[1:])}
    assert pitches == {2.54}, f"pad pitch not 2.54: {pitches}"
