"""Deterministic obstacle-aware autorouter for the SMK test board.

Why this exists as its own module rather than more code inside
`generate_test_board.py`: routing is a self-contained problem with its own
vocabulary (grids, costs, masks) and roughly as much code as the rest of the
generator's PCB writer put together. It is also board-specific -- the shared
`generate_macropad.py` sibling has no router and four other boards depend on
that module, so per this project's CLAUDE.md the change does not belong
there.

Design, in one paragraph. Every obstacle on the board (pads, holes, board
edge, the nine milled LED light windows) is rasterised onto a fixed grid,
inflated by clearance, once. Nets are then routed one at a time with an
8-direction A* that charges for direction changes and for vias, so the
cheapest path is the straight one and the router only bends or changes
layer when geometry forces it. Each net grows as a *cloud*: the first pad
seeds it, and every subsequent pad is routed to whatever the net has
already laid down, which is what produces daisy-chains and T-junctions
rather than a star of overlapping traces from one arbitrary pad.

Three properties this module has to guarantee, all of them requirements
that came from outside it:

* **Determinism.** `generate_test_board.py` promises a byte-identical
  `.kicad_pcb` on every regeneration (docs/fabrication.md's ordering
  checklist step 2 is exactly that check). Nothing here may depend on set
  iteration order, dict hashing, wall-clock time or randomness. Every
  collection that feeds a decision is sorted explicitly, and ties in the A*
  frontier are broken on an explicit counter rather than on object
  identity.
* **No via in pad, ever.** Enforced structurally, not by convention: a
  separate mask forbids a via anywhere its copper would touch any pad on
  either layer, so a via inside a pad is not a thing the search can
  express. See `_build_via_mask()`.
* **JLCPCB-manufacturable.** Defaults in `Rules` sit at or above JLCPCB's
  2-layer standard process (0.127mm trace/space, 0.45mm via, 0.2mm drill,
  copper >=0.3mm from a board edge), not at their floor.

Smoothness is a first-class cost, not a post-process: `TURN_COST` is what
keeps routes from staircasing. Simplification afterwards
(`_simplify_path()`) only removes redundant collinear vertices and pulls
strings straight where the straight line is genuinely clear; it cannot
introduce a bend the search did not already accept.
"""

import heapq
import math
from dataclasses import dataclass, field

# ---------------------------------------------------------------- rules ---


@dataclass(frozen=True)
class Rules:
    """Physical design rules, in mm.

    Defaults are the project's own netclass (see `build_pro()`'s
    `net_settings`) which in turn sits above JLCPCB's 2-layer standard
    process. `edge_clear` is the one number here that is *not* from the
    netclass: JLCPCB asks for copper >=0.3mm from any board edge, and this
    router holds new copper to that even though the board's pre-existing
    SK6812MINI-E pads sit closer to their own light windows (0.2467mm, a
    documented and precedent-justified exception -- see
    docs/fabrication.md). New copper does not get to use that exception.
    """

    signal_w: float = 0.25
    power_w: float = 0.5
    # Extra standoff around pads of a POURED net, so the pour has somewhere
    # to flow. Zero, deliberately. Connectivity for those pads comes from
    # `_route_pour_ties()` giving each one its own via, not from the pour
    # reaching it, so this buys only tidier fill -- and it is not free:
    # the bottom of this board is dense enough (U1's 14 through-holes, U2,
    # four passives, two connectors) that even 0.15mm of standoff on every
    # ground pad strands LEDD0 between U1 and the level shifter.
    pour_margin: float = 0.0
    clearance: float = 0.2
    via_dia: float = 0.6
    via_drill: float = 0.3
    edge_clear: float = 0.3
    hole_clear: float = 0.2
    hole_to_hole: float = 0.25
    grid: float = 0.2

    @property
    def max_half(self):
        """Half-width of the widest TRACE this router can place.

        Deliberately not widened to cover the via diameter. A via is
        fatter than the widest trace is half-wide, so a via centred on a
        cell that is merely trace-legal lands 0.05mm short of clearance
        (thirteen such violations, all via-against-track, on the first
        routed board). Folding the via radius in here fixes those by
        making every trace on the board 0.05mm more standoffish, which
        cost more than it bought -- it congested the key field enough to
        strand a LED-chain hop. Vias carry their own, separate exclusion
        mask instead; see `Grid.via_ok` and `_claim()`.
        """
        return max(self.signal_w, self.power_w) / 2.0


# Nets carrying supply current get the wider trace. Everything else is
# signal-width. (GND is absent on purpose -- it is a pour, not a trace.)
POWER_NETS = frozenset({"VSYS"})

# Search costs, in mm-equivalents. TURN_COST is the smoothness knob: at
# 0.9mm a detour has to save nearly a millimetre of length before the
# router will accept an extra corner to get it, which is what suppresses
# staircasing on a 0.2mm grid. VIA_COST likewise makes a layer change a
# deliberate act rather than a cheap way around a small obstacle.
TURN_COST = 0.9
VIA_COST = 10.0

F_CU, B_CU = 0, 1
LAYER_NAME = {F_CU: "F.Cu", B_CU: "B.Cu"}

# 8 directions, indexed; even indices are orthogonal, odd are diagonal.
DIRS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
SQRT2 = math.sqrt(2.0)


# ------------------------------------------------------------ geometry ---


@dataclass
class Pad:
    """One pad, in absolute board coordinates, already un-rotated into an
    axis-aligned half-extent. `layers` is a set of {F_CU, B_CU}."""

    ref: str
    num: str
    net: str | None
    x: float
    y: float
    hx: float          # half-extent in x, after footprint+pad rotation
    hy: float
    layers: frozenset
    drill: float | None
    plated: bool
    shape: str = "rect"

    @property
    def is_hole(self):
        return self.drill is not None

    @property
    def is_round(self):
        """Circular/oval copper, as opposed to rect/roundrect.

        Worth distinguishing in both directions. Modelling a round pad as
        its bounding box over-reserves the corners; modelling a RECT pad
        as a disc of radius max(hx,hy) under-reserves them, which is how
        three traces ended up 0.193mm from ENC1's square through-hole pad
        against a 0.2mm rule.
        """
        return self.shape in ("circle", "oval")


@dataclass
class Keepout:
    """An axis-aligned region no new copper may enter (board edge margin,
    a milled LED window, a bare hole). Stored as a half-extent box."""

    x: float
    y: float
    hx: float
    hy: float
    reason: str


@dataclass
class Segment:
    net: str
    layer: int
    x1: float
    y1: float
    x2: float
    y2: float
    width: float


@dataclass
class Via:
    net: str
    x: float
    y: float


@dataclass
class RouteResult:
    segments: list = field(default_factory=list)
    vias: list = field(default_factory=list)
    failed: list = field(default_factory=list)   # (net, ref.pad) not reached

    @property
    def ok(self):
        return not self.failed


# ------------------------------------------------------------- the grid ---


class Grid:
    """Occupancy over the board, one cell per `rules.grid` step per layer.

    `owner[layer][idx]` holds the id of the net whose copper (inflated by
    clearance) claims that cell, 0 for free, and `BLOCKED` for something no
    net may ever use -- a hole, the board edge margin, a milled window. A
    cell claimed by net N is passable by N and by nobody else, which is the
    whole clearance model: because the halo already includes clearance plus
    the widest trace this router will draw, a centreline anywhere in a free
    cell is guaranteed legal.
    """

    BLOCKED = -1

    def __init__(self, w, h, rules):
        self.rules = rules
        self.pitch = rules.grid
        self.nx = int(math.floor(w / self.pitch)) + 1
        self.ny = int(math.floor(h / self.pitch)) + 1
        self.owner = [[0] * (self.nx * self.ny) for _ in range(2)]
        self.via_ok = bytearray([1]) * (self.nx * self.ny)

    # -- coordinate helpers -------------------------------------------------
    def idx(self, ix, iy):
        return iy * self.nx + ix

    def to_xy(self, ix, iy):
        return (ix * self.pitch, iy * self.pitch)

    def to_ij(self, x, y):
        return (int(round(x / self.pitch)), int(round(y / self.pitch)))

    def inside(self, ix, iy):
        return 0 <= ix < self.nx and 0 <= iy < self.ny

    # -- painting -----------------------------------------------------------
    def _box_cells(self, x, y, hx, hy):
        """Grid cells whose centre falls inside the box (x,y) +- (hx,hy)."""
        ix0 = max(0, int(math.ceil((x - hx) / self.pitch)))
        ix1 = min(self.nx - 1, int(math.floor((x + hx) / self.pitch)))
        iy0 = max(0, int(math.ceil((y - hy) / self.pitch)))
        iy1 = min(self.ny - 1, int(math.floor((y + hy) / self.pitch)))
        for iy in range(iy0, iy1 + 1):
            for ix in range(ix0, ix1 + 1):
                yield ix, iy

    def paint_box(self, layers, x, y, hx, hy, value, only_free=True):
        for layer in layers:
            arr = self.owner[layer]
            for ix, iy in self._box_cells(x, y, hx, hy):
                i = self.idx(ix, iy)
                if only_free and arr[i] != 0:
                    continue
                arr[i] = value

    def paint_disc(self, layers, x, y, r, value, only_free=True):
        r2 = r * r
        for layer in layers:
            arr = self.owner[layer]
            for ix, iy in self._box_cells(x, y, r, r):
                cx, cy = self.to_xy(ix, iy)
                if (cx - x) ** 2 + (cy - y) ** 2 > r2:
                    continue
                i = self.idx(ix, iy)
                if only_free and arr[i] != 0:
                    continue
                arr[i] = value

    def block_via_box(self, x, y, hx, hy):
        for ix, iy in self._box_cells(x, y, hx, hy):
            self.via_ok[self.idx(ix, iy)] = 0

    def block_via_disc(self, x, y, r):
        r2 = r * r
        for ix, iy in self._box_cells(x, y, r, r):
            cx, cy = self.to_xy(ix, iy)
            if (cx - x) ** 2 + (cy - y) ** 2 <= r2:
                self.via_ok[self.idx(ix, iy)] = 0


# --------------------------------------------------------------- router ---


class Router:
    """Routes a netlist over a two-layer board.

    Usage is two calls: construct with geometry, then `route()`. Everything
    in between is deterministic given identical inputs.
    """

    def __init__(self, board_w, board_h, pads, keepouts, rules=None,
                 net_ids=None, pour_nets=frozenset()):
        self.rules = rules or Rules()
        self.w, self.h = board_w, board_h
        self.pads = pads
        self.keepouts = keepouts
        self.net_ids = net_ids or {}
        self.pour_nets = frozenset(pour_nets)
        self.grid = Grid(board_w, board_h, self.rules)
        self._future_half = self.rules.max_half
        # net name -> small positive int used as the owner tag in the grid.
        # Poured nets DO get a tag: they are not routed pad-to-pad, but
        # each of their pads is stubbed out to a via, and that stub needs
        # a net of its own to route on.
        names = sorted({p.net for p in pads if p.net})
        self._tag = {n: i + 1 for i, n in enumerate(names)}
        self._untag = {i + 1: n for i, n in enumerate(names)}
        self._paint_static()

    # -- static obstacles ---------------------------------------------------
    def _paint_static(self):
        """Rasterise every fixed obstacle once.

        Order matters and is deliberate: pads are painted first, then the
        board-edge margin and the milled windows are painted over them as
        hard blocks. Painting the hard blocks LAST is what guarantees no
        routed copper can ever enter a milled LED light window or run off
        the board -- if pads were painted last they would re-open the cells
        where an SK6812MINI-E pad already overlaps its own window's
        clearance halo, and a trace on that LED's net could then be routed
        straight through the opening. (Those pads themselves sit 0.2467mm
        from their window, an accepted, precedent-justified exception
        documented in docs/fabrication.md. The exception covers the
        existing pads; it does not extend to new copper.)
        """
        r = self.rules
        g = self.grid
        halo = r.clearance + r.max_half

        # Pads, in two passes.
        #
        # Pass 1 paints each pad's CLEARANCE HALO, and where two nets'
        # halos overlap the cell becomes hard-blocked rather than going to
        # whichever pad was painted last. Last-writer-wins is wrong and
        # not subtly so: SW22 pad 1 (COL2) and D22 pad 2 (SW22_N) sit close
        # enough for their halos to overlap, "SW22" sorts after "D22", so
        # COL2 took ownership of cells inside D22's clearance ring and the
        # router then ran a COL2 trace 0.133mm from a foreign pad.
        #
        # Pass 2 then paints each pad's own COPPER with its own tag,
        # unconditionally, so a pad whose copper happens to fall inside a
        # neighbour's halo is still reachable by its own net. A trace
        # there is no closer to the neighbour than the pad itself already
        # is, and the pad's own placement clearance was checked long ago.
        for p in sorted(self.pads, key=lambda p: (p.ref, p.num)):
            tag = self._tag.get(p.net, Grid.BLOCKED) if p.net else Grid.BLOCKED
            extra = r.pour_margin if p.net in self.pour_nets else 0.0
            layers = tuple(sorted(p.layers))
            self._paint_pad_halo(layers, p, halo + extra, tag)
            if p.is_hole and not p.plated:
                g.paint_disc(layers, p.x, p.y,
                             p.drill / 2 + r.hole_clear + r.max_half,
                             Grid.BLOCKED, only_free=False)

        for p in sorted(self.pads, key=lambda p: (p.ref, p.num)):
            if not p.net or p.net not in self._tag:
                continue
            tag = self._tag[p.net]
            layers = tuple(sorted(p.layers))
            if p.is_round:
                g.paint_disc(layers, p.x, p.y, max(p.hx, p.hy), tag,
                             only_free=False)
            else:
                g.paint_box(layers, p.x, p.y, p.hx, p.hy, tag,
                            only_free=False)

        # Board edge margin: a frame of forbidden cells around the outline.
        m = r.edge_clear + r.max_half
        for layer in (F_CU, B_CU):
            arr = g.owner[layer]
            for iy in range(g.ny):
                for ix in range(g.nx):
                    x, y = g.to_xy(ix, iy)
                    if x < m or y < m or x > self.w - m or y > self.h - m:
                        arr[g.idx(ix, iy)] = Grid.BLOCKED

        # Milled windows: holes through the board, so no copper on either
        # layer, and no via anywhere its barrel would reach one.
        for k in self.keepouts:
            g.paint_box((F_CU, B_CU), k.x, k.y, k.hx + m, k.hy + m,
                        Grid.BLOCKED, only_free=False)
            g.block_via_box(k.x, k.y, k.hx + m + r.via_dia / 2,
                            k.hy + m + r.via_dia / 2)

        self._build_via_mask()

    def _paint_pad_halo(self, layers, pad, halo, tag):
        """Paint one pad's clearance halo, blocking contested cells.

        A cell already owned by a different net is claimed by neither: a
        trace of either net there would violate clearance to the other
        one's pad, so it belongs to nobody.
        """
        g = self.grid
        for layer in layers:
            arr = g.owner[layer]
            if pad.is_round:
                rad = max(pad.hx, pad.hy) + halo
                cells = [(ix, iy) for ix, iy in g._box_cells(
                    pad.x, pad.y, rad, rad)
                    if (g.to_xy(ix, iy)[0] - pad.x) ** 2
                    + (g.to_xy(ix, iy)[1] - pad.y) ** 2 <= rad * rad]
            else:
                cells = list(g._box_cells(pad.x, pad.y, pad.hx + halo,
                                          pad.hy + halo))
            for ix, iy in cells:
                i = g.idx(ix, iy)
                cur = arr[i]
                if cur == 0:
                    arr[i] = tag
                elif cur != tag:
                    arr[i] = Grid.BLOCKED

    def _build_via_mask(self):
        """No via in pad, ever -- expressed as geometry the search cannot
        violate rather than as a rule it is asked to respect.

        A via is forbidden anywhere its copper (or its drill's hole-to-hole
        keepout, against an existing hole) would reach a pad on EITHER
        layer. Because a via is a through feature, a pad on the far side
        forbids it just as firmly as one on its own side.
        """
        r = self.rules
        g = self.grid
        vr = r.via_dia / 2.0
        for p in sorted(self.pads, key=lambda p: (p.ref, p.num)):
            bx = p.hx + vr + r.clearance
            by = p.hy + vr + r.clearance
            if p.is_hole:
                # hole-to-hole is drill-to-drill, as well as copper-to-copper.
                sep = p.drill / 2 + r.via_drill / 2 + r.hole_to_hole
                bx, by = max(bx, sep), max(by, sep)
            g.block_via_box(p.x, p.y, bx, by)

    # -- pad anchors --------------------------------------------------------
    def _anchors(self, pad):
        """Grid nodes that lie inside `pad`'s copper, per layer it is on.

        Routing terminates on any of these, which lets a trace enter a pad
        from whichever side is cheapest instead of always aiming at the
        centre -- one of the bigger contributors to routes looking drawn
        rather than generated.
        """
        g = self.grid
        out = []
        # Shrink slightly so an anchor is properly inside the copper, but
        # never below one cell's worth for small pads.
        sx = max(pad.hx - g.pitch * 0.5, g.pitch * 0.25)
        sy = max(pad.hy - g.pitch * 0.5, g.pitch * 0.25)
        # Round pads must be tested against the circle, not its bounding
        # box: a box corner on U1's 1.7mm round header pad sits 1.06mm from
        # centre, outside the 0.85mm copper. A trace ending on such an
        # "anchor" ends in free space next to the pad, and KiCad reports
        # the net as unconnected -- which is exactly what happened to
        # LEDD0 at U1 pad 10.
        rad = max(sx, sy)
        for layer in sorted(pad.layers):
            for ix, iy in g._box_cells(pad.x, pad.y, sx, sy):
                if pad.is_round:
                    cx, cy = g.to_xy(ix, iy)
                    if (cx - pad.x) ** 2 + (cy - pad.y) ** 2 > rad * rad:
                        continue
                out.append((ix, iy, layer))
        if not out:
            ix, iy = g.to_ij(pad.x, pad.y)
            for layer in sorted(pad.layers):
                if g.inside(ix, iy):
                    out.append((ix, iy, layer))
        return out

    # -- the search ---------------------------------------------------------
    def _astar(self, sources, targets, tag, width,
               via_cost=VIA_COST, turn_cost=TURN_COST, margin=None):
        """8-direction A* from any source node to any target node.

        `sources` and `targets` are sets of (ix, iy, layer). Cost is path
        length in mm plus TURN_COST per direction change plus VIA_COST per
        layer change. State carries the incoming direction so a turn can be
        priced; the heuristic is the octile distance to the nearest target,
        which stays admissible because turns and vias only ever add cost.
        """
        g = self.grid
        pitch = g.pitch
        owner = g.owner
        nx, ny = g.nx, g.ny

        tset = set(targets)
        if not tset:
            return None

        # Optional search window. A route between two pads 15mm apart has
        # no business exploring the far corner of the board: bounding the
        # search makes the common case an order of magnitude faster AND
        # rules out the sweeping cross-board detours an unbounded search
        # will happily return when the direct path is mildly congested.
        if margin is None:
            wx0, wy0, wx1, wy1 = 0, 0, nx - 1, ny - 1
        else:
            # Anchor the window on the target and the CLOSEST source, not
            # on every source. By the time a big net like VSYS is half
            # routed its cloud spans the whole board, and a window drawn
            # round the whole cloud would be the whole board -- exactly the
            # case the window exists to avoid.
            tcx = sum(p[0] for p in tset) / len(tset)
            tcy = sum(p[1] for p in tset) / len(tset)
            near = min(sources,
                       key=lambda s: ((s[0] - tcx) ** 2 + (s[1] - tcy) ** 2,
                                      s[0], s[1], s[2]))
            pts = list(tset) + [near]
            pad_cells = int(math.ceil(margin / pitch))
            wx0 = max(0, min(p[0] for p in pts) - pad_cells)
            wx1 = min(nx - 1, max(p[0] for p in pts) + pad_cells)
            wy0 = max(0, min(p[1] for p in pts) - pad_cells)
            wy1 = min(ny - 1, max(p[1] for p in pts) + pad_cells)
        # Precompute the heuristic's reference points, one per layer.
        tby = {}
        for (tx, ty, tl) in tset:
            tby.setdefault(tl, []).append((tx, ty))

        def heur(ix, iy, layer):
            best = None
            for tl, pts in tby.items():
                extra = 0.0 if tl == layer else via_cost
                for (tx, ty) in pts:
                    dx, dy = abs(tx - ix), abs(ty - iy)
                    d = (max(dx, dy) + (SQRT2 - 1) * min(dx, dy)) * pitch
                    v = d + extra
                    if best is None or v < best:
                        best = v
            return best or 0.0

        def passable(ix, iy, layer):
            o = owner[layer][iy * nx + ix]
            return o == 0 or o == tag

        heap = []
        counter = 0
        best = {}
        for (ix, iy, layer) in sorted(sources):
            if not (wx0 <= ix <= wx1 and wy0 <= iy <= wy1):
                continue
            if not g.inside(ix, iy) or not passable(ix, iy, layer):
                continue
            st = (ix, iy, layer, -1)
            best[st] = 0.0
            counter += 1
            heapq.heappush(heap, (heur(ix, iy, layer), counter, 0.0, st, None))
        if not heap:
            return None

        came = {}
        while heap:
            _f, _c, cost, st, parent = heapq.heappop(heap)
            if st in came:
                continue
            came[st] = parent
            ix, iy, layer, pdir = st
            if (ix, iy, layer) in tset:
                # Unwind.
                path = []
                cur = st
                while cur is not None:
                    path.append((cur[0], cur[1], cur[2]))
                    cur = came[cur]
                path.reverse()
                return path

            # Layer change.
            if g.via_ok[iy * nx + ix]:
                other = B_CU if layer == F_CU else F_CU
                if passable(ix, iy, other):
                    nst = (ix, iy, other, -1)
                    nc = cost + via_cost
                    if nc < best.get(nst, float("inf")):
                        best[nst] = nc
                        counter += 1
                        heapq.heappush(
                            heap, (nc + heur(ix, iy, other), counter, nc,
                                   nst, st))

            for di, (dx, dy) in enumerate(DIRS):
                jx, jy = ix + dx, iy + dy
                if not (wx0 <= jx <= wx1 and wy0 <= jy <= wy1):
                    continue
                if not passable(jx, jy, layer):
                    continue
                if dx and dy:
                    # Diagonal: refuse to cut a corner between two blocked
                    # orthogonal neighbours, which would squeeze copper
                    # through a gap narrower than the clearance model
                    # assumes.
                    if not (passable(ix + dx, iy, layer)
                            and passable(ix, iy + dy, layer)):
                        continue
                    step = SQRT2 * pitch
                else:
                    step = pitch
                nc = cost + step
                if pdir != -1 and di != pdir:
                    nc += turn_cost
                nst = (jx, jy, layer, di)
                if nc < best.get(nst, float("inf")):
                    best[nst] = nc
                    counter += 1
                    heapq.heappush(
                        heap, (nc + heur(jx, jy, layer), counter, nc, nst, st))
        return None

    # A connection is attempted cheap-and-pretty first, and the cost model
    # is relaxed only for the connections that actually need it. Raising
    # VIA_COST globally to stop short nets hopping layers pointlessly also
    # stopped congested ones escaping at all -- three nets went unrouted.
    # A ladder gets both: 23 vias across the board, and nothing unrouted.
    # (via_cost, turn_cost, search margin in mm; None = whole board)
    COST_LADDER = (
        (VIA_COST, TURN_COST, 8.0),    # preferred: straight, one layer, local
        (VIA_COST, TURN_COST, 25.0),   # room to go around
        (3.0, TURN_COST, None),        # allow vias, search everywhere
        (1.5, 0.35, None),             # last resort: any legal path at all
    )

    def _astar_ladder(self, sources, targets, tag, width):
        for via_cost, turn_cost, margin in self.COST_LADDER:
            path = self._astar(sources, targets, tag, width,
                               via_cost=via_cost, turn_cost=turn_cost,
                               margin=margin)
            if path is not None:
                return path
        return None

    # -- path post-processing ----------------------------------------------
    def _simplify_path(self, path):
        """Collapse a cell path into as few straight runs as possible.

        Two passes. First drop interior points that continue in the same
        direction -- pure bookkeeping, changes no geometry. Then attempt a
        string pull: for each vertex, if a *single* straight octilinear run
        from the previous vertex to a later one is clear, take it. Only
        exact horizontal, vertical and 45 degree lines are considered, so
        this can never introduce an off-angle segment.
        """
        if len(path) < 3:
            return path
        # Pass 1: collinear merge, split at layer changes.
        out = [path[0]]
        for i in range(1, len(path) - 1):
            px, py, pl = path[i - 1]
            cx, cy, cl = path[i]
            nx_, ny_, nl = path[i + 1]
            if pl != cl or cl != nl:
                out.append(path[i])
                continue
            d1 = (_sgn(cx - px), _sgn(cy - py))
            d2 = (_sgn(nx_ - cx), _sgn(ny_ - cy))
            if d1 != d2:
                out.append(path[i])
        out.append(path[-1])
        return out

    def _clear_run(self, a, b, tag):
        """Is the straight octilinear run a->b free for `tag`? Both ends
        must share a layer and the run must be H, V or exactly 45."""
        ax, ay, al = a
        bx, by, bl = b
        if al != bl:
            return False
        dx, dy = bx - ax, by - ay
        if dx == 0 and dy == 0:
            return True
        if not (dx == 0 or dy == 0 or abs(dx) == abs(dy)):
            return False
        n = max(abs(dx), abs(dy))
        sx, sy = _sgn(dx), _sgn(dy)
        g = self.grid
        arr = g.owner[al]
        for k in range(1, n + 1):
            ix, iy = ax + sx * k, ay + sy * k
            o = arr[iy * g.nx + ix]
            if not (o == 0 or o == tag):
                return False
            if sx and sy:
                for (mx, my) in ((ix - sx, iy), (ix, iy - sy)):
                    o2 = arr[my * g.nx + mx]
                    if not (o2 == 0 or o2 == tag):
                        return False
        return True

    def _string_pull(self, pts, tag):
        if len(pts) < 3:
            return pts
        out = [pts[0]]
        i = 0
        while i < len(pts) - 1:
            j = len(pts) - 1
            best = i + 1
            while j > i + 1:
                if self._clear_run(pts[i], pts[j], tag):
                    best = j
                    break
                j -= 1
            out.append(pts[best])
            i = best
        return out

    # -- painting a finished route -----------------------------------------
    def _claim(self, pts, tag, width):
        """Mark a routed path's copper (plus halo) as owned by `tag`.

        The halo reserves `clearance` plus half of the widest trace still
        to be drawn -- not half of the widest trace on the board. Once the
        power nets are done (they are routed first, see `route()`) only
        signal-width traces remain, so signal routes stop reserving room
        for a 0.5mm neighbour that can no longer arrive. On a board this
        dense that recovered margin is the difference between a net
        routing and failing.
        """
        g = self.grid
        r = self.rules
        halo = width / 2.0 + r.clearance + self._future_half
        for k in range(len(pts) - 1):
            ax, ay, al = pts[k]
            bx, by, bl = pts[k + 1]
            if al != bl:
                # a via: claim a disc on both layers
                x, y = g.to_xy(ax, ay)
                g.paint_disc((F_CU, B_CU), x, y,
                             r.via_dia / 2 + r.clearance + r.max_half, tag)
                g.block_via_box(x, y, r.via_dia + r.hole_to_hole,
                                r.via_dia + r.hole_to_hole)
                continue
            n = max(abs(bx - ax), abs(by - ay))
            # A via placed later must clear this trace by `clearance`
            # measured from its own 0.3mm radius, which is more than the
            # trace halo above reserves. Vias get their own exclusion
            # radius rather than inflating the halo for everyone.
            via_keepout = width / 2.0 + r.clearance + r.via_dia / 2.0
            for s in range(n + 1):
                t = s / n if n else 0
                x = (ax + (bx - ax) * t) * g.pitch
                y = (ay + (by - ay) * t) * g.pitch
                g.paint_disc((al,), x, y, halo, tag)
                g.block_via_disc(x, y, via_keepout)

    # -- top level ----------------------------------------------------------
    def route(self, net_order=None):
        """Route every net that has two or more pads.

        Work is ordered by individual CONNECTION, not by whole net. Each
        net is reduced to a minimum spanning tree over its pads, every
        edge of every tree goes into one list, and that list is routed
        shortest-edge-first across all nets at once.

        Ordering whole nets instead is what produced the failures this
        replaced. VSYS is a 24-pad net, so any whole-net order treats its
        4mm hop from an LED's VDD pad to its own decoupling cap the same
        as its 40mm spine run. Route the net late and the short hops are
        already walled in; route it early and it steals the key cells the
        switch/diode nets have no alternative to. Ordering by connection
        dissolves the conflict: the 4mm hops are among the shortest edges
        on the board and go down first, the spine competes fairly with
        the other long hauls, and no net is early or late as a whole.

        Edges are routed component-to-component, so a later edge can tee
        off copper an earlier one already laid rather than running its own
        parallel path back to a pad.
        """
        res = RouteResult()

        # Poured nets first: stub every pad that cannot see the pour's
        # main plane out to its own via. These are the shortest routes on
        # the board and they are not optional, so nothing else gets to
        # claim their space first.
        for net in sorted(self.pour_nets):
            self._route_pour_ties(net, res)

        by_net = {}
        for p in self.pads:
            if p.net and p.net not in self.pour_nets:
                by_net.setdefault(p.net, []).append(p)

        # One MST per net; all their edges pooled into a single work list.
        edges = []
        for net in sorted(by_net):
            pads = sorted(by_net[net], key=lambda p: (p.ref, p.num))
            if len(pads) < 2:
                continue
            for (a, b) in _mst(pads):
                edges.append([_dist(a, b), net, a, b])

        # Nets a previous pass could not route get their edges pulled to
        # the front, keeping shortest-first among themselves.
        rank = {n: i for i, n in enumerate(net_order or [])}
        edges.sort(key=lambda e: (rank.get(e[1], len(rank)), e[0], e[1],
                                  e[2].ref, e[2].num, e[3].ref, e[3].num))

        # Per-net union-find over pads, plus the grid nodes each component
        # currently owns. Routing an edge merges two components and the
        # merged cloud becomes a target for everything after it.
        parent = {}
        cloud = {}

        def key(net, pad):
            return (net, pad.ref, pad.num)

        def find(k):
            while parent[k] != k:
                parent[k] = parent[parent[k]]
                k = parent[k]
            return k

        for net, pads in by_net.items():
            for p in pads:
                k = key(net, p)
                parent[k] = k
                cloud[k] = set(self._anchors(p))

        for i, (_d, net, a, b) in enumerate(edges):
            # Widest trace still to be drawn after this edge -- what this
            # route's clearance halo has to leave room for.
            self._future_half = max(
                [self._width_of(e[1]) / 2.0 for e in edges[i + 1:]] or [0.0])
            ka, kb = find(key(net, a)), find(key(net, b))
            if ka == kb:
                continue
            tag = self._tag[net]
            width = self._width_of(net)
            path = self._astar_ladder(cloud[ka], cloud[kb], tag, width)
            if path is None:
                res.failed.append((net, f"{a.ref}.{a.num}->{b.ref}.{b.num}"))
                continue
            pts = self._string_pull(self._simplify_path(path), tag)
            self._claim(pts, tag, width)
            self._emit(net, pts, width, res)
            merged = cloud[ka] | cloud[kb] | set(path)
            parent[kb] = ka
            cloud[ka] = merged
        return res

    def route_with_retries(self, max_passes=4):
        """Route, and if anything failed, start over with the nets that
        failed promoted to the front of the order.

        This is the cheap, deterministic cousin of rip-up-and-retry. A
        failure here is never geometric -- a flood fill confirms every pad
        on this board can see the rest of its net across open board -- it
        is always some earlier net having taken the corridor this one
        needed. Reordering is enough to resolve that, and unlike true
        rip-up it cannot loop: the promoted set only grows, passes are
        capped, and the best pass seen is what gets returned.
        """
        promoted = []
        best = None
        for _ in range(max_passes):
            self._reset()
            res = self.route(net_order=promoted or None)
            if best is None or len(res.failed) < len(best.failed):
                best = res
            if not res.failed:
                return res
            newly = sorted({n for (n, _pad) in res.failed})
            merged = list(dict.fromkeys(newly + promoted))
            if merged == promoted:
                break            # same nets failing in the same order
            promoted = merged
        return best

    # Which layer a poured net's main plane lives on. Pads already on that
    # layer sit in the pour's largest, essentially intact fill region and
    # need nothing; pads that cannot see it need a via.
    POUR_PLANE_LAYER = F_CU

    def _route_pour_ties(self, net, res):
        """Give every pad of a poured net its own path to the main plane.

        The problem this solves: a pour on a densely routed 2-layer board
        does not fill as one piece. On this board the front pour comes out
        essentially intact (one 7262mm^2 region) but the back pour breaks
        into ten fragments, and a ground pad can end up alone in a 1.9mm^2
        sliver of fill that reaches nothing -- electrically floating, and
        reported by DRC as a zone-to-zone unconnected item. C1's and C2's
        ground pads did exactly that.

        Trying to fix it by making the pour reach further does not work:
        the standoff a guaranteed pour corridor needs (min_thickness plus
        clearance on both sides) is wide enough to strand other nets.

        So connectivity does not depend on the pour at all. Each pad that
        is not already on the plane layer gets a short stub to a via, and
        the via lands it on the front plane. The back pour is then purely
        a bonus -- extra copper and shorter return paths -- and it does
        not matter how it fragments.

        A pad already on the plane layer is left alone, and pads with a
        through-hole (which span both layers by themselves) need nothing.
        """
        tag = self._tag[net]
        width = self.rules.signal_w
        r = self.rules
        g = self.grid
        pads = sorted((p for p in self.pads if p.net == net),
                      key=lambda p: (p.ref, p.num))
        for p in pads:
            if p.is_hole:
                continue          # spans both layers by itself
            on_plane = self.POUR_PLANE_LAYER in p.layers
            src_layer = (self.POUR_PLANE_LAYER if on_plane
                         else sorted(p.layers)[0])
            placed = False
            for (vx, vy) in self._via_spots_near(p.x, p.y, 4.0, limit=16):
                ix, iy = g.to_ij(vx, vy)
                if g.owner[src_layer][g.idx(ix, iy)] not in (0, tag):
                    continue
                path = self._astar(self._anchors(p), [(ix, iy, src_layer)],
                                   tag, width, margin=6.0)
                if path is None:
                    continue
                pts = self._string_pull(self._simplify_path(path), tag)
                self._claim(pts, tag, width)
                self._emit(net, pts, width, res)
                res.vias.append(Via(net, round(vx, 4), round(vy, 4)))
                g.paint_disc((F_CU, B_CU), vx, vy,
                             r.via_dia / 2 + r.clearance + r.max_half, tag)
                g.block_via_box(vx, vy, r.via_dia + r.hole_to_hole,
                                r.via_dia + r.hole_to_hole)
                placed = True
                break
            if not placed and not on_plane:
                # A pad off the plane layer has no other way to reach the
                # net, so failing to tie it is a hard failure. A pad ON
                # the plane layer is merely un-helped: the plane is the
                # one fill region that comes out essentially intact, and
                # it reaches almost all of them by itself.
                res.failed.append((net, f"{p.ref}.{p.num} -> pour tie via"))

    def _via_spots_near(self, x, y, max_reach, limit=16):
        """Legal via centres near (x, y), nearest first. Deterministic."""
        g = self.grid
        cx, cy = g.to_ij(x, y)
        span = int(math.ceil(max_reach / g.pitch))
        cands = []
        for dy in range(-span, span + 1):
            for dx in range(-span, span + 1):
                ix, iy = cx + dx, cy + dy
                if not g.inside(ix, iy):
                    continue
                i = g.idx(ix, iy)
                if not g.via_ok[i]:
                    continue
                if g.owner[F_CU][i] != 0:
                    continue
                px, py = g.to_xy(ix, iy)
                d2 = (px - x) ** 2 + (py - y) ** 2
                if d2 > max_reach ** 2:
                    continue
                cands.append((d2, px, py))
        cands.sort()
        return [(px, py) for (_d, px, py) in cands[:limit]]

    def stitching_vias(self, net, spacing=12.0):
        """Legal positions for ground stitching vias, on a coarse grid.

        Call after `route()`. A position qualifies only if it is free of
        every routed net's clearance halo on BOTH layers and passes the
        same no-via-in-pad mask every routed via passes, so these cannot
        land in a pad either.

        Why bother when the two pours already share the board's three
        through-hole GND pads: three ties is enough for DC and not enough
        for return currents. EMC rule VS-001 asks for stitching at
        lambda/20 of the highest frequency of interest, which is ~48mm
        here, so the 12mm default sits four times inside the requirement.

        Not tighter than that on purpose. Stitching vias are close to free
        on a bare-PCB order, but each one punches a hole through both
        pours, and an 8mm grid put 137 vias on this board -- enough extra
        drill hits to be worth noticing and enough perforation to start
        working against the plane it is meant to help.
        """
        g = self.grid
        step = max(1, int(round(spacing / g.pitch)))
        out = []
        for iy in range(step, g.ny - step, step):
            for ix in range(step, g.nx - step, step):
                i = g.idx(ix, iy)
                if not g.via_ok[i]:
                    continue
                if g.owner[F_CU][i] != 0 or g.owner[B_CU][i] != 0:
                    continue
                x, y = g.to_xy(ix, iy)
                out.append(Via(net, round(x, 4), round(y, 4)))
                # Claim it so nothing later routes into it.
                r = self.rules
                g.paint_disc((F_CU, B_CU), x, y,
                             r.via_dia / 2 + r.clearance + r.max_half,
                             Grid.BLOCKED)
        return out

    def _reset(self):
        self.grid = Grid(self.w, self.h, self.rules)
        self._future_half = self.rules.max_half
        self._paint_static()

    def _width_of(self, net):
        return self.rules.power_w if net in POWER_NETS else self.rules.signal_w

    def _emit(self, net, pts, width, res):
        g = self.grid
        for k in range(len(pts) - 1):
            ax, ay, al = pts[k]
            bx, by, bl = pts[k + 1]
            x1, y1 = g.to_xy(ax, ay)
            x2, y2 = g.to_xy(bx, by)
            if al != bl:
                res.vias.append(Via(net, x1, y1))
                continue
            if (x1, y1) == (x2, y2):
                continue
            res.segments.append(
                Segment(net, al, round(x1, 4), round(y1, 4),
                        round(x2, 4), round(y2, 4), width))


def _sgn(v):
    return (v > 0) - (v < 0)


def _dist(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def _mst(pads):
    """Minimum spanning tree over a net's pads, by straight-line distance.

    Prim's, with every tie broken on (ref, pad) so the tree is identical
    on every run. The MST is only a starting topology -- the router routes
    each edge component-to-component, so a later edge can tee onto copper
    an earlier one laid down and the finished net is usually shorter than
    its own MST.
    """
    if len(pads) < 2:
        return []
    inside = [pads[0]]
    outside = list(pads[1:])
    edges = []
    while outside:
        best = None
        for a in inside:
            for b in outside:
                cand = (_dist(a, b), a.ref, a.num, b.ref, b.num)
                if best is None or cand < best[0]:
                    best = (cand, a, b)
        _c, a, b = best
        edges.append((a, b))
        inside.append(b)
        outside.remove(b)
    return edges


# ------------------------------------------------------- geometry input ---
# The router reads the board's REAL emitted geometry rather than being told
# coordinates a second time. That is this project's standing idiom (see
# `_pad_obstacles()` / `_probe_obstacles()` in generate_test_board.py, and
# the comment there about hand-copied coordinates going stale): a footprint
# that changes shape changes what the router routes around, automatically,
# with no second place to update.


def _tokenize(s):
    out, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c in "()":
            out.append(c)
            i += 1
        elif c == '"':
            j, buf = i + 1, []
            while j < n:
                if s[j] == "\\":
                    buf.append(s[j + 1])
                    j += 2
                elif s[j] == '"':
                    break
                else:
                    buf.append(s[j])
                    j += 1
            out.append("".join(buf))
            i = j + 1
        elif c.isspace():
            i += 1
        else:
            j = i
            while j < n and not s[j].isspace() and s[j] not in '()"':
                j += 1
            out.append(s[i:j])
            i = j
    return out


def _parse_all(tokens):
    """Parse a stream of top-level s-expressions."""
    nodes, i, n = [], 0, len(tokens)
    while i < n:
        if tokens[i] != "(":
            i += 1
            continue
        depth, start = 0, i
        while i < n:
            if tokens[i] == "(":
                depth += 1
            elif tokens[i] == ")":
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            i += 1
        nodes.append(_build(tokens[start:i]))
    return nodes


def _build(tokens):
    def rec(i):
        node = []
        i += 1
        while tokens[i] != ")":
            if tokens[i] == "(":
                sub, i = rec(i)
                node.append(sub)
            else:
                node.append(tokens[i])
                i += 1
        return node, i + 1

    node, _ = rec(0)
    return node


def _kids(node, name):
    return [c for c in node if isinstance(c, list) and c and c[0] == name]


def _kid(node, name):
    k = _kids(node, name)
    return k[0] if k else None


def extract_geometry(footprint_text):
    """Parse emitted footprint s-expressions into router inputs.

    Returns (pads, keepouts). Keepouts are the Edge.Cuts primitives found
    *inside* footprints -- on this board that is exactly the nine milled
    SK6812MINI-E light windows, which are holes through the board and so
    forbid copper on both layers. The board's own outline is handled
    separately by `Router` from its width/height.
    """
    nodes = _parse_all(_tokenize(footprint_text))
    # Accept either a bare run of `(footprint ...)` forms (what
    # build_pcb() assembles internally) or a whole `(kicad_pcb ...)` file
    # with them nested one level down.
    flat = []
    for n in nodes:
        if n and n[0] == "kicad_pcb":
            flat.extend(c for c in n if isinstance(c, list))
        else:
            flat.append(n)

    pads, keepouts = [], []

    for fp in flat:
        if not fp or fp[0] != "footprint":
            continue
        at = _kid(fp, "at")
        fx, fy = float(at[1]), float(at[2])
        frot = float(at[3]) if len(at) > 3 else 0.0
        fplayer = _kid(fp, "layer")
        ref = ""
        for prop in _kids(fp, "property"):
            if len(prop) > 2 and prop[1] == "Reference":
                ref = prop[2]

        # A footprint on B.Cu has its stored rotation applied NEGATED --
        # the pad offsets themselves are not mirrored. Verified against
        # KiCad's own DRC output on this board, both ways round:
        #   RGB1 (B.Cu, rot 180) pad 1 local (-2.725, -0.75) -> (27.725,
        #   19.725), which plain rotation also predicts because sin(180)
        #   is 0 -- so that case proves nothing on its own;
        #   D00  (B.Cu, rot 270) pad 2 local (+1.635, 0) -> (16.5,
        #   27.635), where plain rotation predicts 24.365 and only the
        #   negated angle gives 27.635.
        # Getting this wrong swapped anode and cathode on all nine matrix
        # diodes (the only back-side parts here whose rotation is not a
        # multiple of 180), and the router cheerfully drew each ROW trace
        # straight through the neighbouring pad: 16 shorting_items in DRC.
        if fplayer is not None and fplayer[1] == "B.Cu":
            frot = -frot
        ca = math.cos(math.radians(frot))
        sa = math.sin(math.radians(frot))

        def to_board(px, py):
            return (fx + px * ca - py * sa, fy + px * sa + py * ca)

        for pad in _kids(fp, "pad"):
            num, ptype, pshape = pad[1], pad[2], pad[3]
            pat = _kid(pad, "at")
            px, py = float(pat[1]), float(pat[2])
            prot = float(pat[3]) if len(pat) > 3 else 0.0
            size = _kid(pad, "size")
            sx, sy = float(size[1]), float(size[2])
            drill_node = _kid(pad, "drill")
            drill = None
            if drill_node is not None:
                vals = [t for t in drill_node[1:] if not isinstance(t, list)]
                numeric = [v for v in vals if _isnum(v)]
                if numeric:
                    drill = float(numeric[0])
            lay = _kid(pad, "layers")
            names = [t for t in lay[1:]] if lay else []
            layers = set()
            for nm in names:
                if nm.startswith("*."):
                    layers |= {F_CU, B_CU}
                elif nm == "F.Cu":
                    layers.add(F_CU)
                elif nm == "B.Cu":
                    layers.add(B_CU)
            if not layers:
                layers = {F_CU, B_CU}
            netn = _kid(pad, "net")
            net = netn[2] if netn is not None and len(netn) > 2 else None

            ax, ay = to_board(px, py)
            # A pad's stored angle is ABSOLUTE -- the footprint's own
            # rotation is already baked into it, which is why KiCad
            # rewrites every pad angle when you rotate a footprint, and
            # why `generate_macropad.py`'s fp_diode() passes the
            # footprint's rot straight through to each pad() call. Adding
            # the footprint rotation on top double-counts it.
            #
            # It only shows up where the total is an odd multiple of 90,
            # which on this board is the nine diodes alone (footprint 270,
            # pads 270). Double-counting made them 1.0 x 1.2 instead of
            # 1.2 x 1.0, moving D22 pad 2's edge 0.1mm the wrong way and
            # convincing the router it had room it did not have.
            # Confirmed against KiCad: with the wrong extents, D22 pad 2
            # sits 0.19mm from SW22 pad 1 against a 0.2mm rule and DRC
            # would have to flag the pads themselves -- it does not.
            tot = prot % 180.0
            if abs(tot) < 1e-6 or abs(tot - 180.0) < 1e-6:
                hx, hy = sx / 2.0, sy / 2.0
            elif abs(tot - 90.0) < 1e-6:
                hx, hy = sy / 2.0, sx / 2.0
            else:
                d = math.hypot(sx, sy) / 2.0
                hx = hy = d
            pads.append(Pad(ref=ref, num=str(num), net=net,
                            x=round(ax, 4), y=round(ay, 4), hx=hx, hy=hy,
                            layers=frozenset(layers), drill=drill,
                            plated=(ptype != "np_thru_hole"),
                            shape=str(pshape)))

        # Edge.Cuts inside a footprint = a milled opening.
        xs, ys = [], []
        for prim in fp:
            if not isinstance(prim, list) or not prim:
                continue
            if prim[0] not in ("fp_line", "fp_arc", "fp_poly", "fp_rect",
                               "fp_circle"):
                continue
            lay = _kid(prim, "layer")
            if lay is None or lay[1] != "Edge.Cuts":
                continue
            for key in ("start", "mid", "end", "center"):
                pt = _kid(prim, key)
                if pt is not None:
                    bx, by = to_board(float(pt[1]), float(pt[2]))
                    xs.append(bx)
                    ys.append(by)
            ptsnode = _kid(prim, "pts")
            if ptsnode is not None:
                for xy in _kids(ptsnode, "xy"):
                    bx, by = to_board(float(xy[1]), float(xy[2]))
                    xs.append(bx)
                    ys.append(by)
        if xs:
            keepouts.append(Keepout(
                x=(min(xs) + max(xs)) / 2.0, y=(min(ys) + max(ys)) / 2.0,
                hx=(max(xs) - min(xs)) / 2.0, hy=(max(ys) - min(ys)) / 2.0,
                reason=f"{ref} milled opening"))

    pads.sort(key=lambda p: (p.ref, p.num))
    keepouts.sort(key=lambda k: (k.reason,))
    return pads, keepouts


def gnd_zones(board_w, board_h, net_id, net_name, uuid_fn, inset=0.3):
    """Ground pours on both copper layers, as zone OUTLINES only.

    Deliberately unfilled. A filled zone carries KiCad's computed
    `filled_polygon` blobs in the board file -- tens of kilobytes of
    derived geometry that changes with the KiCad version and would make
    "regenerating an unchanged generator produces a byte-identical
    .kicad_pcb" false the first time anyone ran a different KiCad. The
    fill is derivable, so it is derived at the point of use instead:
    `kicad-cli pcb drc --refill-zones` and `kicad-cli pcb export gerbers
    --check-zones` both compute it, and export_fab.py passes the latter.

    Settings follow the sibling ~/esp/SMK_macro_pad board's own zones so
    the two projects behave the same in KiCad, with two additions.
    Thermal reliefs on pad connections, because this board is hand-soldered
    and a GND pad tied solidly into a full pour sinks enough heat into the
    plane to make it hard to wet with an iron. Note the mode is the
    omitted/default one, which means thermal relief for EVERY pad -- not
    `thru_hole_only`, which reads like "give through-hole pads a thermal
    relief" but actually means "connect only through-hole pads", leaving
    every SMD ground pad on the board floating in the pour. And
    `island_removal_mode 0`
    -- always drop fill regions that reach no pad. On a 2-layer board this
    dense the pour is cut into many pieces, and any piece touching nothing
    is copper KiCad rightly reports as an unconnected GND item; deleting
    them is what makes the net clean rather than merely quiet.
    """
    out = []
    x0, y0 = inset, inset
    x1, y1 = board_w - inset, board_h - inset
    for layer in ("F.Cu", "B.Cu"):
        out.append(f'''  (zone (net {net_id}) (net_name "{net_name}") (layer "{layer}") (uuid "{uuid_fn("zone", layer)}") (hatch edge 0.5)
    (connect_pads (clearance 0.25))
    (min_thickness 0.25) (filled_areas_thickness no)
    (fill yes (thermal_gap 0.3) (thermal_bridge_width 0.4)
      (island_removal_mode 0))
    (polygon (pts (xy {x0:g} {y0:g}) (xy {x1:g} {y0:g}) (xy {x1:g} {y1:g}) (xy {x0:g} {y1:g})))
  )''')
    return "\n".join(out)


def _isnum(tok):
    try:
        float(tok)
        return True
    except (TypeError, ValueError):
        return False


# ------------------------------------------------------------- emission ---


def emit_tracks(result, net_ids, uuid_fn, rules=None):
    """Render routed copper as KiCad `segment` / `via` s-expressions.

    Emission order is sorted, and `uuid_fn` is called in that order, so the
    UUIDs land identically on every regeneration -- which is what keeps
    docs/fabrication.md's "regenerating an unchanged generator produces a
    byte-identical .kicad_pcb" check true with routing present.

    Pass a CONTENT-hashed uuid function here (gm.U), not the counter-based
    one (gm.NU). NU bumps a module-global counter per call, so emitting a
    few hundred tracks shifts every UUID generated after them -- including
    the six footprints re-emitted into the project's own kbd.pretty, which
    then show up in `git diff` as six changed files whose geometry is
    identical. That is precisely the signal CLAUDE.md asks to keep clean:
    the diff on smk_test_board/ should show what moved electrically and
    nothing else. The index is part of the key so two identical-looking
    segments cannot collide.
    """
    rules = rules or Rules()
    out = []
    segs = sorted(result.segments,
                  key=lambda s: (s.net, s.layer, s.x1, s.y1, s.x2, s.y2))
    for i, s in enumerate(segs):
        out.append(
            f'  (segment (start {s.x1:g} {s.y1:g}) (end {s.x2:g} {s.y2:g}) '
            f'(width {s.width:g}) (layer "{LAYER_NAME[s.layer]}") '
            f'(net {net_ids[s.net]}) '
            f'(uuid "{uuid_fn("seg", i, s.net, s.x1, s.y1, s.x2, s.y2, s.layer)}"))')
    vias = sorted(result.vias, key=lambda v: (v.net, v.x, v.y))
    for i, v in enumerate(vias):
        out.append(
            f'  (via (at {v.x:g} {v.y:g}) (size {rules.via_dia:g}) '
            f'(drill {rules.via_drill:g}) (layers "F.Cu" "B.Cu") '
            f'(net {net_ids[v.net]}) '
            f'(uuid "{uuid_fn("via", i, v.net, v.x, v.y)}"))')
    return "\n".join(out)
