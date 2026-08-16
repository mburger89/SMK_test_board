# Bring-up — SMK Test Board (rev A)

Procedure for turning a freshly fabricated/assembled board into a validated
one. Transcribed from the design spec's §9 acceptance checks
(`docs/superpowers/specs/2026-08-16-smk-test-board-design.md`) into an
ordered, checkable form.

**Do these in order.** Power and continuity come before the XIAO module is
ever seated, and matrix/layer checks come before anything wireless — each
step assumes every step above it already passed. If a step fails, stop and
fix it before continuing; a later step's result is not trustworthy if an
earlier one didn't actually pass.

Board reference: `docs/superpowers/specs/2026-08-16-smk-test-board-design.md`.
Fabrication reference: `docs/fabrication.md`. Firmware: `~/esp/SMK`
branch `test-board-config` (commit 171f67c). Configurator: `~/esp/smk_configurator`
branch `test-board-design` (commit dfd84da). Reference keymap: `keymap.json`
in this repo (commit 610cb87).

Every checkbox below has a blank **Result** line. This document was written
without hardware in hand — nothing in it has been run. Fill in each result
as you go; don't check a box you haven't actually observed.

---

## Before you start: the footprint gate

Two footprints on this board — `XIAO_ESP32C6_HEADERS` and `EC11_VERTICAL` —
were hand-drawn from datasheet dimensions and had never been checked against
physical parts as of fabrication (`docs/fabrication.md`'s "STOP — pre-order
gate"). If that 1:1 print check happened before this board was ordered, its
result belongs there, not here. If it didn't, or you're not sure, **Step 1
below is your first chance to catch a footprint error** — a header row that
doesn't seat, or encoder pins that don't line up with the PCB's holes both
show up as soon as you hold the real parts against the board.

---

## Step 1 — Visual inspection and continuity

Before the XIAO is seated. Power checks come first because a short here can
damage the XIAO the moment it's powered, and there is no way to undo that.

- [ ] **1a. Visual inspection.** No solder bridges, no lifted pads, no
  obviously cold joints. Check `XIAO_ESP32C6_HEADERS` and `EC11_VERTICAL`
  specifically — headers seat flush and square, encoder pins line up with
  their holes and the mounting posts aren't binding against the footprint's
  silkscreen/pads. (See "Before you start" above — this is where a
  never-checked footprint shows up.)

  Result: ______________________________________________

- [ ] **1b. VSYS–GND continuity.** Multimeter in continuity/low-resistance
  mode, board unpowered, XIAO **not yet seated**. Probe VSYS to GND at the
  JST-PH battery connector or the XIAO footprint's VSYS/GND pads. Expect
  **no continuity** (open, or a normal high-impedance reading — not a dead
  short).

  Result: ______________________________________________

- [ ] **1c. 3V3–GND continuity.** Same method, 3V3 to GND. Expect **no
  continuity**.

  Result: ______________________________________________

  If either 1b or 1c shows a dead short: stop. Do not seat the XIAO or
  apply power. Re-inspect for a solder bridge on the power rails before
  going any further.

---

## Step 2 — Seat the XIAO and power up

- [ ] **2a. Seat the XIAO ESP32-C6** module into its headers.

  Result: ______________________________________________

- [ ] **2b. Power over USB-C and confirm enumeration.** This board's
  firmware build has no USB HID path on ESP32-C6 (BLE + wired-UART only,
  per `~/esp/SMK/CLAUDE.md`'s target table — this board has no CH9350
  bridge either) — what you're confirming here is the XIAO's native
  USB-Serial/JTAG showing up as a new serial device, e.g.
  `ls /dev/tty.usbmodem*` (macOS), so `idf.py flash` has something to talk
  to. A device that doesn't enumerate at all points at the XIAO seating, a
  bad USB-C cable/port, or a dead module — not yet a board wiring problem.

  Result: ______________________________________________

---

## Step 3 — Flash the test board build

- [ ] **3a. Select the board variant in Kconfig before building.**
  `~/esp/SMK`'s `main/Kconfig.projbuild` defines a `choice SMK_BOARD` whose
  **default is `SMK_BOARD_SMK_KBD`** — the *other* board, the 5×12
  reference keyboard, not this one. If you skip this, the firmware
  compiles and flashes cleanly and every matrix test below fails
  confusingly, because it's scanning a pin map for a keyboard this board
  isn't.

  ```bash
  . ~/.espressif/v6.0.1/esp-idf/export.sh
  cd ~/esp/SMK
  idf.py set-target esp32c6    # one-time, if not already set
  idf.py menuconfig
  ```

  In the menu: **SMK Keyboard Configuration → Board variant**, select
  **"SMK test board (Seeed XIAO ESP32-C6, 3x3 macropad bring-up board)"**
  (`CONFIG_SMK_BOARD_TEST_BOARD`). Save and exit.

  Result: ______________________________________________

- [ ] **3b. Two-Mac bonding needs `CONFIG_BT_NIMBLE_MAX_BONDS = 4`, and the
  tracked defaults don't set it.** `sdkconfig.defaults` (the file that
  seeds a fresh `sdkconfig` when none exists) carries
  `CONFIG_BT_NIMBLE_MAX_BONDS=1`, not 4 — the design spec's §9 check 8
  wants 4, matching this repo's own working (but gitignored, machine-local)
  `sdkconfig`. If you're building from a fresh clone, or after
  `idf.py fullclean`, check this explicitly:
  **Component config → Bluetooth → NimBLE Options → General → "Maximum
  number of bonds to save across reboots"** should read **4**. If it's not,
  set it now — Step 11 (two-Mac bonding) will otherwise fail for a config
  reason that has nothing to do with this board's hardware.

  Result: ______________________________________________

- [ ] **3c. Build and flash.**

  ```bash
  idf.py build
  idf.py flash monitor
  ```

  Confirm the flash completes without error and the monitor shows the
  firmware booting (no boot-loop, no crash backtrace).

  Result: ______________________________________________

---

## Step 4 — Matrix

The compiled-in default keymap for this board (`Sources/smk/Main.swift`,
`#elseif SMK_BOARD_TEST_BOARD` branch) is a single flat layer,
`key:1`…`key:9`, one keycode per matrix position, row-major — nothing
uploaded yet. Use it as-is for this step; don't load anything in the
configurator until Step 5.

- [ ] **4a. All 9 positions register.** Press each of the 9 physical
  positions in turn (the 8 Gateron switches plus the encoder's integrated
  push-switch) and confirm each one reports a distinct keystroke 1–9 with
  nothing missing and nothing duplicated. **The encoder's contribution here
  is its push-switch only — press straight down on the knob.** Nothing in
  this firmware build decodes rotation (GPIO17/GPIO19 are wired but
  unread — quadrature decoding is a later spec, out of scope for this
  board's bring-up); turning the knob left or right is expected to do
  **nothing**, and that is not a failure.

  Physically, the encoder's push-switch is wired at matrix **row 0 / col
  2** — confirmed independently in three places: `generate_test_board.py`'s
  `build_nets()` (`ENC1` pad 4 → `COL2`, pad 5 → the diode side of
  `D02`, whose cathode is on `ROW0`), the design spec's §1/§2, and
  `Main.swift`'s own comment on this board's default keymap ("row 0, col 2
  is the rotary encoder's push switch"). If you're cross-referencing
  against the schematic, that's the position to press for "encoder"; the
  other 8 are ordinary Gateron switches.

  Result (list each of the 9 positions and what it typed):
  ______________________________________________
  ______________________________________________

- [ ] **4b. No ghosting on a three-key L.** Hold down three keys forming an
  L-shape in the 3×3 grid (e.g. two keys in one row plus one key in a
  different row, sharing a column with one of the first two) and confirm
  exactly those three keystrokes register — no phantom fourth key from the
  diode matrix.

  Result: ______________________________________________

---

## Step 5 — Layers (`mo:` and `tg:`)

The compiled-in default keymap from Step 4 has no layers at all — one flat
9-key layer, no `mo:`/`tg:` tokens anywhere — so this step can't be
exercised without uploading a keymap that has them first. That upload is
what the rest of this step walks through.

**Known issue in the shipped reference keymap — read before wiring up your
expectations.** `keymap.json`'s `mo:1` binding sits at grid position **row
2 / col 2** — an ordinary Gateron switch, ordinary switch `SW22` in the
generator's own naming, two rows away from the encoder. It is **not** on
the encoder's push-switch (row 0 / col 2, see Step 4a). Concretely, as
shipped:

- Layer 0, row 0 (`key:1`, `key:2`, `key:3`) — col 2 here (`key:3`) is the
  encoder's physical position. Pressing the encoder with this keymap
  loaded just types "3"; it does not touch layers.
- Layer 0, row 2 (`key:7`, `key:8`, `mo:1`) — col 2 here is an ordinary
  switch. **This** is the key that momentarily switches to layer 1.
- Layer 1 mirrors layer 0's grid with `f1`–`f8` in place of `1`–`8`, and
  `trans` at row 2 / col 2 (falls through to layer 0's `mo:1`, so holding
  that key behaves consistently whichever layer you're viewing it from).

This is a defect in the reference file (Task 9's board deliverable,
`keymap.json` commit 610cb87), not a hardware fault — it's flagged here
rather than fixed, since this document is documentation-only and
`keymap.json` is out of this task's scope to edit. Test layers against the
key that's **actually** bound (row 2 / col 2), not the encoder, and don't
read "the encoder doesn't change layers" as a board failure — per the
wiring above, it was never supposed to.

`keymap.json` also has no `tg:` binding at all (design spec §9 check 2
wants both `mo:` and `tg:` verified). Add one as part of the same upload:

- [ ] **5a. Load and edit the reference keymap.** In the configurator, File
  → Open `~/esp/SMK_test_board/keymap.json`. Its matrix (`rows: [1,2,21]`,
  `cols: [22,23,16]`, `colsAreDriven: 1`) matches `KeyboardDesign
  .smkTestBoard` exactly, so the app should auto-select that design — the
  key grid should render as a labeled 3×3, not a generic/unlabeled
  fallback. Remap the **row 2 / col 1** key (currently `key:8` on layer 0)
  to `tg:1`. Leave everything else as-is, including the row 2 / col 2
  `mo:1` binding described above.

  Result: ______________________________________________

- [ ] **5b. Upload this edited keymap** via the DEV pane (see Step 7 below
  for what "upload" looks like mechanically over BLE — do that now, using
  this edited keymap as the payload, ahead of Step 7's own upload).

  Result: ______________________________________________

- [ ] **5c. `mo:` while held.** Hold the row 2 / col 2 key. Confirm the
  other 8 keys emit `F1`–`F8` (per `keymap.json`'s layer 1) while it's
  held, and revert to `1`,`2`,`3`,`4`,`5`,`6`,`7` (layer 0) the instant you
  release it — no lag, no stuck layer.

  Result: ______________________________________________

- [ ] **5d. `tg:` latching.** Press and release the row 2 / col 1 key once
  (the `tg:1` you just added). Confirm the board **stays** on layer 1 —
  the other keys now emit `F1`–`F8` without anything held down. Press the
  same key again and confirm it toggles back to layer 0.

  Result: ______________________________________________

---

## Step 6 — BLE HID typing into a Mac

- [ ] **6a. Pair.** On a Mac, open Bluetooth settings and pair to
  **"SMK Keyboard"** — the device name is hardcoded
  (`Sources/components/ble_helper.c`) and is the same on every SMK board
  variant, so if there's another SMK board nearby, confirm you're pairing
  to this one (e.g. by its MAC/proximity, or by temporarily powering the
  other one off).

  Result: ______________________________________________

- [ ] **6b. Type.** Open a text field and press keys on the board (layer 0
  is fine — `1`–`8` plus the `tg:1` you added). Confirm each keystroke
  appears correctly and promptly.

  Result: ______________________________________________

---

## Step 7 — Keymap upload from the configurator, confirm a remap

This step specifically exercises the upload-and-confirm round trip called
out in the design spec's §9 check 4 ("the check the 2026-08-15 BLE work
could not perform, having no switches") — a fresh, isolated remap, separate
from Step 5's layer edits, so a failure here points at the upload path and
not at anything layer-related.

Note on what "connected" looks like: the configurator's BLE transport
(`Sources/SMKConfigurator/Device/BLETransport.swift`) has no live
connect-status indicator yet — the DEV pane's transport list always shows
BLE as "Not connected" even mid-upload (see that view's own comment). The
real signal is the upload itself: no error banner
("Couldn't send keymap to device: …") and `Send to Device` returning to its
idle label with a fresh "Last sent Xs ago" timestamp.

- [ ] **7a. Remap one key.** In the configurator (same session as Step 5,
  or reopen `keymap.json`), change the **row 0 / col 0** key (currently
  `key:1`) to `key:z`.

  Result: ______________________________________________

- [ ] **7b. Upload.** DEV pane → **Send to Device**. It tries USB first,
  finds nothing (this board has no USB HID path), then falls back to BLE
  automatically — no manual transport selection needed. Confirm no error
  banner appears and `Last sent` updates.

  Result: ______________________________________________

- [ ] **7c. Confirm the remap.** Press the row 0 / col 0 key and confirm it
  now types `z`, not `1`.

  Result: ______________________________________________

---

## Step 8 — Persistence across power cycle

- [ ] **8a. Power cycle the board** (unplug/replug USB, or full power-off
  if running on battery — see Step 10).

  Result: ______________________________________________

- [ ] **8b. Confirm the remap survived.** Press row 0 / col 0 again;
  confirm it still types `z`. If it reverted to `1`, the upload didn't
  actually persist to NVS — treat this as a firmware/storage bug, not a
  configurator bug (Step 7 already confirmed the upload path itself
  worked).

  Result: ______________________________________________

---

## Step 9 — RGB (first hardware validation of the RMT driver)

Nothing has exercised `LedStripDriverRMT.swift` against a real LED chain
before this board. Give this more than a pass/fail checkbox — a partial
failure here is the expected way a driver meets real hardware for the
first time, and where it fails tells you what's wrong.

This firmware's RGB isn't an idle animation — it's **per-key, reactive**:
`Main.swift` lights a key's LED solid white (255,255,255) on press and
turns it off on release (see `rgb?.setKey(...)` in the scan loop). "Lights
and animates" in the design spec's §9 means this — press a key, its LED
lights; release it, the LED goes dark. There is no boot-time rainbow or
idle pattern to wait for.

- [ ] **9a. Press each of the 9 keys in turn and watch its LED.** Expect:
  LED lights solid white while held, goes dark on release, and it's the
  **correct** LED under the key you pressed (the chain is wired
  serpentine — even rows run col 0→2, odd rows run col 2→0 — so a
  transposed row is a plausible failure mode, not just "some LED lights").

  Result (note any key whose LED doesn't match, is dim, wrong color, or
  doesn't light at all):
  ______________________________________________
  ______________________________________________

- [ ] **9b. If nothing lights at all:** `led_strip_driver_init` fails
  silently (no log line) if `rmt_new_tx_channel`/`rmt_new_led_strip_encoder`
  /`rmt_enable` return nonzero — check GPIO20 wiring, the SN74AHCT1G125
  level shifter's power (VCC from VSYS, not 3V3 — an unpowered shifter
  drives nothing downstream) and OE# (tied permanently to GND to enable
  it), and the 100µF bulk cap at the chain entry.

  Result: ______________________________________________

- [ ] **9c. If only the first LED (under whichever key you press) responds
  and the rest never do:** points at the chain wiring past RGB1 — a broken
  DOUT→DIN hop, a cold solder joint on one of the 9 SK6812MINI-E parts, or
  a reversed LED (DIN/DOUT swapped) partway down the chain. Isolate by
  checking continuity DOUT(n)→DIN(n+1) starting from RGB1.

  Result: ______________________________________________

- [ ] **9d. If colors look wrong (e.g. a key you expect white shows red or
  green):** the driver's wire format is GRB, MSB-first — a channel-order
  mismatch this early usually means a miswired LED footprint, not a
  software bug (this project's SK6812MINI-E footprint is the fab-proven
  one shared with `~/esp/SMK_Keyboard`, so a wiring/solder defect is more
  likely than a footprint error here).

  Result: ______________________________________________

---

## Step 10 — Battery (first hardware validation of `BatteryMonitor`)

Nothing has exercised `BatteryMonitor.swift`/`battery_adc.c` against a real
cell and a real divider before this board. As with Step 9, a plausible
partial failure needs somewhere to point, not just a checkbox.

`BatteryMonitor` reads GPIO0 (ADC1_CH0), doubles it (the board's VBAT÷2
divider — `vbatDividerRatio = 2` in `BatteryMonitor.swift`), then maps
3300mV–4200mV linearly to 0–100% and clamps outside that range. This is a
rough single-cell Li-ion approximation, not a calibrated discharge curve —
don't expect a precise number, but a **stable, plausible, slowly-falling**
one.

- [ ] **10a. Connect a charged single-cell Li-ion to the JST-PH connector,
  unplug USB, and run untethered.** Confirm the board still functions
  (matrix/BLE) on battery alone.

  Result: ______________________________________________

- [ ] **10b. Check the reported percentage.** On the paired Mac, Bluetooth
  settings shows a battery percentage for "SMK Keyboard" (via the BLE HID
  Battery Service). Expect a plausible number (not 0%, not obviously
  wrong for a charged cell) that **falls slowly** over time/use, not one
  that's frozen or jumps erratically.

  Result: ______________________________________________

- [ ] **10c. If it's stuck at 0%:** the ADC reading is at or below
  3300mV/2 at the pin — check the VBAT divider's wiring and that the cell
  is actually connected/charged, before suspecting the ADC/firmware.

  Result: ______________________________________________

- [ ] **10d. If it's stuck at 100%, or implausibly high right after
  connecting a partially-discharged cell:** the pin reading is at or above
  4200mV/2 — check for the divider ratio being wrong (e.g. the pin
  actually seeing near-undivided VBAT, doubling an already-high reading)
  or the ADC pin shorted toward VSYS/3V3 rather than reading the true
  divider midpoint.

  Result: ______________________________________________

- [ ] **10e. If `smk_battery_adc_init` failed outright:** the serial
  monitor logs "Battery ADC init failed; battery reporting disabled"
  (`BatteryMonitor.swift`'s `initBatteryMonitor()`) — unlike Step 9's RMT
  driver, this failure path *does* log, so check `idf.py monitor` output
  first.

  Result: ______________________________________________

---

## Step 11 — Two-Mac bonding

Depends on Step 3b (`CONFIG_BT_NIMBLE_MAX_BONDS = 4`) actually being set in
the build you flashed — if you skipped that check, confirm it now before
concluding this step failed on hardware.

- [ ] **11a. Pair to a first Mac**, confirm typing works (as in Step 6).

  Result: ______________________________________________

- [ ] **11b. Pair to a second Mac** (same device name, "SMK Keyboard" —
  see Step 6a's note), confirm typing works there too.

  Result: ______________________________________________

- [ ] **11c. Switch back to the first Mac** (put it in range / wake
  Bluetooth there) and confirm it **reconnects without re-pairing** —
  no "forgotten device" prompt, no re-entering a passkey.

  Result: ______________________________________________

- [ ] **11d. Switch to the second Mac** and confirm the same — reconnects
  without re-pairing.

  Result: ______________________________________________

---

## Summary

| Step | Pass/Fail | Notes |
|---|---|---|
| 1. Visual + continuity | | |
| 2. Seat + power | | |
| 3. Flash (test board Kconfig + bond count) | | |
| 4. Matrix (9 positions, no ghosting) | | |
| 5. Layers (`mo:`, `tg:`) | | |
| 6. BLE HID typing | | |
| 7. Keymap upload + remap | | |
| 8. Persistence | | |
| 9. RGB (first RMT validation) | | |
| 10. Battery (first `BatteryMonitor` validation) | | |
| 11. Two-Mac bonding | | |

Board is validated when every row above is Pass.
