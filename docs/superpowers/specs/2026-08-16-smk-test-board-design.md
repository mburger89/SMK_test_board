# SMK Test Board — Design

Date: 2026-08-16
Status: Approved, pending implementation plan

A 9-position macropad built around the Seeed XIAO ESP32-C6, existing as
hardware to validate the SMK firmware and the SMK Configurator end to end.
This repo owns the PCB; the firmware lives in `~/esp/SMK` and the editor in
`~/esp/smk_configurator`, and this design names the changes each of them
needs.

## Problem

SMK's ESP32-C6 support is written against one custom 59-key board, and parts
of it have never met hardware at all:

- **The RMT LED driver has never run.** `RGBLighting`/`LedStripDriverRMT` are
  implemented, but the reference board has no per-key RGB (the firmware's
  CLAUDE.md says so explicitly), so nothing has ever driven a real LED chain.
- **`BatteryMonitor` has never been checked against a battery.** Its own
  documentation states the mV→percentage curve is "not yet verified against a
  real board".
- **The matrix path has not been exercised on a C6 at all.** The BLE upload
  work of 2026-08-15 was validated against a bare XIAO ESP32-C6 with no
  switches attached: uploads and the GATT round trip were proven, but no key
  was ever pressed, so matrix scan, layers and HID typing remain untested on
  this MCU.

A small purpose-built board closes all three, and afterwards becomes the
fixture for encoder support.

### Out of scope

- **Rotary encoder firmware.** SMK cannot decode quadrature today: there is no
  encoder action in the keymap vocabulary, no `ActionToken` case, and no
  decoder. The encoder is *wired* here and read in a later project (§10).
- Per-key RGB (see §3 for why the LEDs are not under the switches).
- Any case, plate, or enclosure.

## Design overview

1. Matrix and pin map
2. Rotary encoder
3. LED chain
4. Power and battery
5. KiCad project and mechanical
6. Firmware: a new board configuration
7. Configurator: a `KeyboardDesign`
8. Bill of materials and fabrication
9. Testing and acceptance
10. Phase 2: encoder support

## 1. Matrix and pin map

A **3×3 matrix**: 8 Gateron low-profile switches plus the EC11's integrated
push switch, which occupies the row 0 / col 2 position.

Putting the encoder's push switch *in the matrix* rather than on its own GPIO
is deliberate and buys two things. The press works immediately as an ordinary
key you can bind in the configurator, months before any quadrature decoding
exists. And the matrix stays 3×3, which keeps the LED count at 9 — a hard
constraint, because `RGBLighting(gpioNum:rowCount:colCount:)` allocates
exactly `rowCount × colCount` LEDs.

| Function | XIAO pad | GPIO |
|---|---|---|
| ROW0–ROW2 (sense, pull-down) | D1, D2, D3 | 1, 2, 21 |
| COL0–COL2 (strobe, push-pull) | D4, D5, D6 | 22, 23, 16 |
| Encoder A / B | D7, D8 | 17, 19 |
| LED data | D9 | 20 |
| VBAT sense | D0 (A0) | 0 (ADC1_CH0) |
| Spare / test point | D10 | 18 |

Pin numbering is the XIAO ESP32-C6's published map (D0–D10 →
GPIO 0, 1, 2, 21, 22, 23, 16, 17, 19, 20, 18). GPIO 3, 14 and 15 are the
antenna switch, RF switch power and the onboard LED, and GPIO 4–7 are the
JTAG pads — none are exposed on the pads used here, so there is no conflict.

**Direction matches SMK's existing convention** (`colsAreDriven = 1`, columns
strobed push-pull, rows sensed with pull-downs), so the scan logic needs no
change. Diodes are therefore **anode to column, cathode to row** — the
direction current flows when a driven column is taken high.

Note that the reference board's GPIO map cannot be reused: it needs 17 pins
(5 rows + 12 columns) across GPIOs the XIAO does not expose.

## 2. Rotary encoder

An EC11 with integrated push switch. A and B go to GPIO17 and GPIO19, each
with a 100 nF capacitor to ground for contact debounce, and pulled up — the
ESP32-C6's internal pull-ups are sufficient, so external resistors are
footprinted but may be left unpopulated.

The push switch is wired as the matrix position at row 0 / col 2, with its own
diode like any other key.

**Nothing in the firmware reads A/B until phase 2.** They are wired, brought
to known pins, and left alone. This is the whole reason the encoder appears in
a board whose purpose is testing existing functionality.

## 3. LED chain

Nine WS2812B-compatible RGB LEDs in a chain, data in on GPIO20.

**The LEDs sit along the board edge, not under the switches.** The firmware's
only requirement is that the chain length equals `rowCount × colCount`; it has
no notion of physical placement. Per-key RGB under Gateron low-profile
switches would mean reverse-mount SK6812MINI-E parts aligned to switch
cutouts — real layout risk for no testing benefit, since the goal is
exercising the RMT driver, not lighting keycaps.

**Powered from 3.3 V**, not 5 V. WS2812B at 5 V wants data ≥ 3.5 V and the C6
drives 3.3 V; that margin is the classic source of intermittent first-LED
corruption. Running the chain at 3.3 V keeps the data line in spec at the cost
of some brightness, which a test fixture does not care about. Each LED gets a
100 nF decoupling capacitor, with a 10 µF bulk capacitor at the head of the
chain.

**Current budget:** nine LEDs at full white would draw roughly 500 mA, which
is more than the XIAO's regulator should supply on battery. The firmware must
cap brightness; budget ~200 mA at moderate levels. This is a firmware
constraint, not a board one, and belongs in the bring-up notes.

## 4. Power and battery

USB-C on the XIAO powers the board when tethered. For untethered BLE testing,
a single-cell Li-ion connects to the XIAO's BAT+/BAT− pads through a JST-PH
2-pin connector on the PCB; the XIAO's onboard charger handles charging.

Battery *monitoring* costs nothing: the XIAO already carries a **1:2 divider
on A0**, which is exactly the halved VBAT that `BatteryMonitor` assumes ("the
board halves VBAT before it reaches the ADC pin"). No external divider, one
pin, and the existing firmware maths is correct as written.

## 5. KiCad project and mechanical

KiCad 9 project at the repo root: `SMK_test_board.kicad_pro`, `.kicad_sch`,
`.kicad_pcb`, plus a project-local `SMK_test_board.pretty` footprint library.

- Two layers, roughly 70 × 70 mm, keys on a 19.05 mm pitch.
- PCB-mount switches, no plate.
- The XIAO mounts on two 1×7 female headers rather than being soldered to its
  castellated pads, so it can be removed. This is the same board used for
  firmware bring-up; keeping its USB port and BOOT/RESET buttons reachable
  matters more than 5 mm of height.
- Mounting holes: 4 × M3 at the corners.

**Footprint risk, stated up front.** Stock KiCad ships neither a Gateron
low-profile switch nor a XIAO ESP32-C6 footprint. Both must come from a
third-party keyboard library or be drawn by hand, and **both must be checked
against the physical parts before fabrication** — a wrong switch footprint is
the standard way to receive a board nothing fits into. Print the layout at
1:1 and offer up a real switch and a real XIAO.

## 6. Firmware: a new board configuration

In `~/esp/SMK`:

- A new board branch in `Main.swift`'s `configJson`, with the §1 matrix, and
  its accompanying Kconfig option alongside the existing board choices.
- **`Sources/components/battery_adc.c` hardcodes IO4 / ADC1_CH4.** This board
  senses VBAT on GPIO0 / ADC1_CH0, so the ADC channel becomes per-board rather
  than fixed. This is a real change to shared firmware code, not a
  configuration value.
- `RGBLighting` is instantiated with `gpioNum: 20, rowCount: 3, colCount: 3`,
  and whatever Kconfig gate currently disables RGB on the reference board is
  enabled for this one.

## 7. Configurator: a `KeyboardDesign`

In `~/esp/smk_configurator`: a `KeyboardDesign` describing the 3×3 physical
layout with `matrix.rows = [1, 2, 21]`, `matrix.cols = [22, 23, 16]`, and
`colsAreDriven = 1`, plus a `keymap.json` for it. The design is editor-only —
the firmware never sees it — but its matrix block is what makes a written
`keymap.json` valid, so the GPIO numbers must match §1 exactly.

## 8. Bill of materials and fabrication

On hand: XIAO ESP32-C6, 8 × Gateron low-profile switches, 1 × EC11, and
**9 × 1N4148** diodes — one per matrix position, the encoder's push switch
included.

To source: 9 × WS2812B-compatible LEDs (SK6812 is the friendlier choice at
3.3 V), 2 × 1×7 female headers, 1 × JST-PH 2-pin connector, **11 × 100 nF**
capacitors (9 for LED decoupling, 2 for encoder debounce), 1 × 10 µF bulk
capacitor, 2 × 10 kΩ resistors (encoder pull-ups, likely unpopulated), 4 × M3
standoffs, and low-profile keycaps.

Fabrication is JLCPCB, bare boards only — hand assembly, no PCBA. At this
part count and with through-hole switches, assembly service buys nothing.

## 9. Testing and acceptance

The board is finished when each of these passes on it:

1. **Matrix** — every one of the 9 positions registers, including the encoder
   press, with no ghosting when three keys in an L are held.
2. **Layers** — an `mo:` binding on one key changes what the others emit while
   held; a `tg:` binding latches.
3. **BLE HID** — the board types into a Mac over BLE.
4. **Keymap upload** — the configurator's DEV pane shows "Connected via BLE",
   an upload completes, and a remapped key emits its new value. This is the
   check the 2026-08-15 BLE work could not perform, having no switches.
5. **Persistence** — the remap survives a power cycle.
6. **RGB** — the LED chain lights and animates. First hardware validation of
   the RMT driver.
7. **Battery** — on battery, the Mac's Bluetooth panel shows a plausible
   percentage that falls as the cell discharges. First hardware validation of
   `BatteryMonitor`.
8. **Multi-host bonding** — pair to two Macs and confirm both reconnect
   without re-pairing, exercising `CONFIG_BT_NIMBLE_MAX_BONDS = 4`.

Checks 1–3 are firmware; 4–5 are the configurator; 6–8 are the subsystems this
board exists to reach.

## 10. Phase 2: encoder support

Once the board is populated, encoder support becomes its own project spanning
both software repos, and it is genuinely three changes, not one:

- **Firmware:** quadrature decoding of GPIO17/19, and an encoder action in the
  keymap vocabulary.
- **Keymap schema:** a new `ActionToken` case and cell syntax, which is a
  hand-synced contract between the firmware's `LayerEngine` and the app's
  `ActionToken` — the same coupling the repos already track by hand.
- **Configurator:** UI to bind clockwise and counter-clockwise actions, which
  do not fit the existing per-key grid model.

It gets its own spec and plan. The wiring in §2 exists so that work starts
with hardware already in hand.
