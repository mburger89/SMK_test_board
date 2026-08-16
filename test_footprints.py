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
    "SOT-23-5": 5,   # level shifter (SN74AHCT1G125DBVR): OE#, A, GND, Y, VCC
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


# ===================================================== library-master parity

# generate_test_board.py re-renders three footprints inline as positioned PCB
# instances (gm.py has no generator for them), each claiming to reproduce this
# repo's own smk_test_board.pretty/<NAME>.kicad_mod. Nothing checked that, and
# the comment above them asserted "byte-for-byte" — which was false, and false
# in a way that hid a real, unreworkable defect: _fp_sk6812mini_tb() emitted 4
# pads, 5 silk lines, a courtyard, 2 fab items and the 3D model, and silently
# dropped ALL 20 of the master's Edge.Cuts primitives (the milled light window
# a REVERSE-MOUNT LED shines through) plus the pin-1 silk polarity triangle.
# Nine LEDs would have been fabricated sealed behind solid FR4.
#
# The old 13-test suite could not have caught it: every test asserted netlist
# facts or footprint POSITIONS, and none compared a re-render against the
# master it copies. This does, per element-class, so a dropped layer fails
# loudly instead of shipping.
#
# What is compared is EQUIVALENT GEOMETRY, not bytes: uuids and net
# assignments differ by construction, and the masters spell rectangles as four
# fp_line segments where gm.fprect() emits one fp_rect (so fp_rect is expanded
# into its four edges before comparison). Everything else — every pad, every
# graphic, on every layer — must match exactly.

_NUM = r"-?[\d.]+"


def _sexps(text, head):
    """Every top-level `(head ...)` s-expression in `text`, paren-balanced."""
    out = []
    for m in re.finditer(r"\(" + re.escape(head) + r"[\s\"]", text):
        depth, start = 0, m.start()
        for j in range(start, len(text)):
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    out.append(" ".join(text[start:j + 1].split()))
                    break
    return out


def _f(v):
    return round(float(v), 4)


def _pts(seg, key):
    # The trailing rotation is optional: `(at 0 -12)` in the hand-drawn
    # masters, `(at 0 -12 0)` in what gm.fp_header() emits.
    m = re.search(r"\(" + key + r" (" + _NUM + r") (" + _NUM + r")"
                  r"(?: " + _NUM + r")?\)", seg)
    return (_f(m.group(1)), _f(m.group(2))) if m else None


def _layer(seg):
    m = re.search(r'\(layer "([^"]+)"\)', seg)
    return m.group(1) if m else None


def _width(seg):
    m = re.search(r"\(width (" + _NUM + r")\)", seg)
    return _f(m.group(1)) if m else None


def _layers_norm(s):
    """A pad's layer list as a concrete, comparable set.

    `"*.Cu"` and `"F&B.Cu"` name the same two copper layers on a 2-layer
    board (this one is 2-layer, asserted below), and the two spellings are
    used interchangeably: the hand-drawn EC11 master writes `"*.Cu"` for its
    NPTH mounting legs where gm.npth() emits `"F&B.Cu"`. Expanding both to
    {F.Cu, B.Cu} keeps that from reading as a difference, without weakening
    the check -- a pad that really is on only one copper layer still
    compares unequal."""
    out = set()
    for tok in s.replace('"', "").split():
        if tok in ("*.Cu", "F&B.Cu"):
            out |= {"F.Cu", "B.Cu"}
        elif tok.startswith("*."):
            out |= {"F." + tok[2:], "B." + tok[2:]}
        else:
            out.add(tok)
    return frozenset(out)


def _class_of(layer):
    if layer == "Edge.Cuts":
        return "Edge.Cuts"
    for suffix, name in ((".SilkS", "silk"), (".CrtYd", "courtyard"),
                         (".Fab", "fab"), (".Mask", "mask")):
        if layer.endswith(suffix):
            return name
    return layer


def _elements(text):
    """{element-class -> set of normalized primitives} for one footprint.

    Classes: "pads", "silk", "courtyard", "fab", "Edge.Cuts", "model", "text".
    """
    out = {}

    def add(cls, item):
        out.setdefault(cls, set()).add(item)

    for seg in _sexps(text, "pad"):
        m = re.match(r'\(pad "([^"]*)" (\S+) (\S+) ', seg)
        num, ptype, shape = m.groups()
        at = re.search(r"\(at (" + _NUM + r") (" + _NUM + r")(?: (" + _NUM + r"))?\)", seg)
        size = re.search(r"\(size (" + _NUM + r") (" + _NUM + r")\)", seg)
        drill = re.search(r"\(drill (" + _NUM + r")\)", seg)
        layers = re.search(r"\(layers ([^)]*)\)", seg)
        add("pads", (num, ptype, shape,
                     _f(at.group(1)), _f(at.group(2)),
                     _f(at.group(3) or 0),
                     _f(size.group(1)), _f(size.group(2)),
                     _f(drill.group(1)) if drill else None,
                     _layers_norm(layers.group(1))))

    for seg in _sexps(text, "fp_line"):
        a, b = _pts(seg, "start"), _pts(seg, "end")
        add(_class_of(_layer(seg)),
            ("seg", _width(seg), min(a, b), max(a, b)))

    for seg in _sexps(text, "fp_rect"):
        (x1, y1), (x2, y2) = _pts(seg, "start"), _pts(seg, "end")
        corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
        # A rectangle IS its four edges: the masters draw them as four
        # fp_lines, gm.fprect() emits one fp_rect. Same copper, same silk,
        # same milling — normalize both spellings to the same four segments
        # so the comparison is about geometry, not s-expression style.
        for i in range(4):
            a, b = corners[i], corners[(i + 1) % 4]
            add(_class_of(_layer(seg)),
                ("seg", _width(seg), min(a, b), max(a, b)))

    for seg in _sexps(text, "fp_arc"):
        add(_class_of(_layer(seg)),
            ("arc", _width(seg), _pts(seg, "start"), _pts(seg, "mid"),
             _pts(seg, "end")))

    for seg in _sexps(text, "fp_poly"):
        pts = tuple((_f(x), _f(y)) for x, y in
                    re.findall(r"\(xy (" + _NUM + r") (" + _NUM + r")\)", seg))
        fill = re.search(r"\(fill (\w+)\)", seg)
        add(_class_of(_layer(seg)),
            ("poly", _width(seg), pts, fill.group(1) if fill else None))

    for seg in _sexps(text, "fp_circle"):
        add(_class_of(_layer(seg)),
            ("circle", _width(seg), _pts(seg, "center"), _pts(seg, "end")))

    # Reference/Value carry two interchangeable spellings across KiCad
    # versions -- `(fp_text reference ...)` in the older hand-drawn masters,
    # `(property "Reference" ...)` in what gm.fp_header() emits. Same silk,
    # same position; fold both into one "refval" class so the comparison sees
    # a real difference and not a file-format difference. Any OTHER fp_text
    # (the BAT+/BAT- polarity labels) is real silk and compared as "text".
    for seg in _sexps(text, "fp_text"):
        m = re.match(r'\(fp_text (\S+) "([^"]*)"', seg)
        kind, txt = m.group(1), m.group(2)
        if kind in ("reference", "value"):
            # Content deliberately excluded: Reference and Value are
            # PER-INSTANCE fields in KiCad, so the master's "REF**"/"EC11"
            # will never equal a placed instance's "RGB4"/"EC11 (VERIFY
            # before fab)". Their layer and offset are footprint geometry
            # and are compared.
            add("refval", (kind, _layer(seg), _pts(seg, "at")))
        else:
            add("text", (kind, txt, _layer(seg), _pts(seg, "at")))

    for seg in _sexps(text, "property"):
        m = re.match(r'\(property "(Reference|Value)" "', seg)
        if m:
            add("refval", (m.group(1).lower(), _layer(seg), _pts(seg, "at")))

    for seg in _sexps(text, "model"):
        add("model", (re.match(r'\(model "([^"]*)"', seg).group(1),))

    return out


# library-master name -> a zero-argument call of the inline re-render that
# claims to reproduce it.
def _inline_renders():
    import generate_test_board as tb
    return {
        "SK6812MINI_E": lambda: tb._fp_sk6812mini_tb("REF**", 0, 0, None, {}),
        "XIAO_ESP32C6_HEADERS": lambda: tb._fp_xiao_headers("REF**", 0, 0, None, {}),
        "EC11_VERTICAL": lambda: tb._fp_ec11_vertical("REF**", 0, 0, None, {}),
    }


def test_inline_rerenders_match_their_library_master():
    for name, build in _inline_renders().items():
        master = _elements(open(os.path.join(LIB, f"{name}.kicad_mod")).read())
        inline = _elements(build())
        for cls in sorted(set(master) | set(inline)):
            want, got = master.get(cls, set()), inline.get(cls, set())
            missing, extra = want - got, got - want
            assert not missing, (
                f"{name}: inline re-render DROPPED {len(missing)} {cls} "
                f"element(s) the library master has: {sorted(missing)[:3]}")
            assert not extra, (
                f"{name}: inline re-render INVENTED {len(extra)} {cls} "
                f"element(s) the library master lacks: {sorted(extra)[:3]}")


def test_sk6812_carries_its_edge_cuts_light_window():
    """The specific defect, asserted by name as well as by class parity.

    SK6812MINI-E is REVERSE-MOUNT: it sits on the back of the board and
    shines forward THROUGH it, into each switch's north window. The window is
    milled, i.e. it exists only as Edge.Cuts geometry inside the footprint —
    8 straight segments and 12 arcs forming a ~3.4 x 3.0mm rounded rect. With
    no Edge.Cuts the LEDs are behind solid FR4 and do nothing, and it is not
    reworkable after fabrication.
    """
    import generate_test_board as tb
    edge = _elements(tb._fp_sk6812mini_tb("REF**", 0, 0, None, {})).get("Edge.Cuts", set())
    segs = [e for e in edge if e[0] == "seg"]
    arcs = [e for e in edge if e[0] == "arc"]
    assert len(segs) == 8, f"{len(segs)} Edge.Cuts segments, want 8"
    assert len(arcs) == 12, f"{len(arcs)} Edge.Cuts arcs, want 12"
    xs = [c[0] for e in edge for c in e[2:] if c]
    ys = [c[1] for e in edge for c in e[2:] if c]
    assert abs((max(xs) - min(xs)) - 3.48786) < 0.01, "window width wrong"
    assert abs((max(ys) - min(ys)) - 3.08786) < 0.01, "window height wrong"


def test_every_led_on_the_board_gets_a_window():
    """Per-instance, on the real generated board text: 9 LEDs x 20 Edge.Cuts
    primitives, plus the board outline's own gr_rect and the layer
    declaration = 182 `Edge.Cuts` mentions. A window that exists in the
    footprint but is somehow lost on the way onto the board is still nine
    dead LEDs."""
    import generate_test_board as tb
    pcb = tb.build_pcb()
    per_led = len(tb.SK6812_WINDOW_LINES) + len(tb.SK6812_WINDOW_ARCS)
    assert per_led == 20
    assert pcb.count("Edge.Cuts") == 2 + per_led * tb.LED_COUNT


def test_no_footprint_master_contains_an_sexpr_comment():
    """KiCad's s-expression parser has NO comment syntax.

    `EC11_VERTICAL.kicad_mod` and `XIAO_ESP32C6_HEADERS.kicad_mod` each
    carried a few `;; ...` explanatory lines. KiCad rejects such a file
    outright, and one rejected file makes it refuse to load the WHOLE .pretty
    library -- which is why registering the library in `fp-lib-table` alone
    did not clear DRC's `lib_footprint_issues` warnings, and why those
    warnings were mis-attributed for two revisions to "running kicad-cli
    outside the full KiCad project environment".

    Put rationale in `(descr "...")`, which KiCad actually reads, or in the
    generator alongside the code.
    """
    for name in EXPECTED:
        path = os.path.join(LIB, f"{name}.kicad_mod")
        bad = [i + 1 for i, ln in enumerate(open(path).read().splitlines())
               if ln.strip().startswith(";")]
        assert not bad, (
            f"{name}.kicad_mod has s-expression comment(s) on line(s) {bad} -- "
            "KiCad will refuse to load this file and every other footprint "
            "in the library with it")
