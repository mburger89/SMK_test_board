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
