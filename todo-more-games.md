claude --resume 3d37495c-b295-46aa-9263-45a2d9a3035c

# More Games — Implementation Plan

This document is the agreed implementation spec. Implementer should follow it as-written; deviations require approval.

---

## Status (2026-05-09)

**Shipped on `feature/more-games`:**
- §1 Universal F1-held-3s abort + ALT+F1 abort removal
- §1.1 Game-select carousel (F1 opens, F1 cycles, F2 starts, F1-held-3s exits, 10-s idle reset on F1, F2 quick-start of `last_game`, white↔yellow 2 Hz flash, lighting frozen while open)
- §2 Hardware config refactor (dropped `pin_button_r/g/b/y/c/m`; per-game `buttons` block)
- §3 `lib/game_common.py` (BaseGame, GameRegistry, helpers, button-name list)
- §5 Simon Says end-to-end (`lib/game2.py`, `web/game2.html`/`game2.js`, `/api/game2/*`, sanitizer, options card)
- §7 Index page lists Snake + Simon Says (Master Mind link not yet)
- §8 `_sanitize_game2`, `last_game` top-level key
- §9 main.py wiring for Snake + Simon
- §10 web routes for `/game2(.html|.js)` + `/api/game2/*`
- Bonus (not in original plan, discovered during implementation):
  - Configurable HTTP proxy at `hardware.http_proxy` (bare hostname; firmware adds scheme + `?_=` + URL-encoded upstream). Sun-times and tz-offset use it. Empty = direct HTTPS.
  - `gc.collect()` between import groups in `main.py` to keep heap contiguity for the second-core thread. Pico W has ~190 KB usable heap; TLS handshake needs ~30–50 KB contiguous and routinely ENOMEMs after our modules load — the proxy is the workaround.

**Outstanding:**
- §6 Master Mind (lib/game3.py + web/game3.{html,js} + /api/game3/* + sanitizer + main wiring + options card + index button + carousel slot)

**Open questions / lessons:**
- Memory budget on Pico W is the binding constraint. Adding game3 may push us back into MemoryError territory. If so: precompile `lib/*.py` to `.mpy` first, or freeze modules into a custom UF2. `.mpy` setup is documented in chat history if/when needed.
- `/settings.json` writes are non-atomic; concurrent writes from core 0 + core 1 can corrupt. Has not bitten us yet on the merged code, but worth hardening before adding more save sites.

---

## 0. Scope and ground rules

- **Do NOT change Snake gameplay.** `lib/game.py` may be touched ONLY to extract shared helpers into a new `lib/game_common.py`. Snake’s files keep their existing names (`lib/game.py`, `web/game.html`, `web/game.js`, `/game.json`, `/api/game/*`).
- New games:
  - Game 2 (Simon Says) → `lib/game2.py`, `web/game2.html`, `web/game2.js`, `/game2.json`, `/api/game2/*`.
  - Game 3 (Master Mind) → `lib/game3.py`, `web/game3.html`, `web/game3.js`, `/game3.json`, `/api/game3/*`.
- Each game owns the LED strip exclusively. **Only one game can run at a time.** API and web start endpoints refuse-if-busy with HTTP 409.
- All buttons in lighting mode behave as today; in any active game, all keys are remapped to that game’s actions.
- The Snake game button on the index page is renamed to **“Snake”**; files and routes are unchanged.

---

## 1. Global input change: universal abort and game-select  ✅ DONE

- Remove ALT+F1 abort from Snake and any other code path.
- Add a **single universal abort**: pressing-and-holding **F1 for 3 seconds** while ANY game is active aborts that game and returns to lighting mode. The same 3-s hold also exits the game-select carousel (§1.1) back to lighting.
- A 3-second F1 hold in lighting mode does **not** enter game-select. The short-press game-select action only fires on **release before the 3s hold threshold**.
- Implementation: `ButtonHandler` already tracks hold duration. Add an `abort_game` flag emitted when F1 has been held ≥ 3000ms while `game_input_mode` is True (or while game-select is active). Once emitted, the press is consumed (no further action when released).

### 1.1 Game-select carousel (lighting mode)

In lighting mode, F1 no longer starts Snake directly. Instead F1 enters a **game-select carousel** that lets the player pick which game to start:

- **F1 short-press (lighting mode)** → enter game-select. The strip is fully cleared; carousel owns the entire strip while open (lighting effects/auto-mode are frozen — see "Strip ownership" below). The carousel displays N centered white LEDs, where N = number of implemented games (currently 3). The home-end LED of those N **alternates between full white and full yellow at ~2 Hz** (250 ms white / 250 ms yellow) to indicate the current selection; the other N − 1 LEDs are solid white.
- **F1 short-press (in game-select)** → shift selection to the next game (cursor moves one LED toward the far end). After the last game, the next F1 press wraps back to the first. **The 10-s idle timer resets on each F1 press.**
- **F2 short-press (in game-select)** → start the currently-highlighted game.
- **F2 short-press (lighting mode, BEFORE carousel is opened)** → quick-start the **last-played game** (Snake on first boot / when no last-played game is recorded). Equivalent to F1→(cycle to that game)→F2 but without showing the carousel. Snake/Simon start gameplay directly; Master Mind enters length-select (§6.4) at the last-used length.
  - Persistence: last-played-game is stored in `/settings.json` at top-level key `last_game` with value `"snake"` | `"simon"` | `"mastermind"`. Updated whenever any game starts (from any source: carousel, F2 quick-start, web API). Sanitizer drops unknown values and falls back to `"snake"`.
- **Idle timeout**: if 10 seconds elapse with no F1 or F2 press while in game-select, exit back to lighting mode (no game starts). The timer is (re)set on carousel-open AND on every F1 press.
- **F1-held-3s (in game-select)** → exit back to lighting mode immediately.
- All other buttons (off/auto/on/alt) behave as in lighting mode while the carousel is open — except per "Strip ownership" below they have no visible effect on the strip until the carousel exits.
- Game order in the carousel is **fixed**: Snake (slot 1), Simon Says (slot 2), Master Mind (slot 3). Adding a future game appends a slot.
- Centering: place the N LEDs centered on the strip midpoint; if the strip length and N have opposite parity, prefer the home-side pair (same convention as §5.4).
- Master Mind, when selected and started via F2 (or via F2 quick-start when it was the last-played game), transitions into its **length-select** sub-phase (§6.4) before gameplay begins. Snake and Simon Says start gameplay directly.
- ALT+F1 / ALT+F2 / ALT+anything no longer have any game-start meaning (the old ALT+F1 → Master Mind length-select binding is gone). ALT+key combinations retain whatever lighting-mode meaning they have today.

**Strip ownership while carousel is open**: the carousel owns the entire strip. Lighting-mode rendering (auto-mode color/effects, manual mode, off) is **paused** for the duration of the carousel — `_update_mode()` early-exits while a `game_select_active` flag is True, exactly like it does when a game is active. Off/auto/on button presses still update the underlying mode state (so the right state is in place when the carousel exits) but do not render to the strip. When the carousel exits (timeout / abort / game start), the lighting mode resumes from the current state on the next tick.

Implementation note: game-select is a lighting-mode UI sub-state, not a game. It lives in `main.py` (or a small `lib/game_select.py` helper) — not in any single game module. Treat it as a fourth "owner" for strip arbitration alongside the three games.

---

## 2. Hardware config refactor: button names, not color aliases  ✅ DONE

Today `config.py` has two parallel sets of button pins (`pin_button_off/auto/on/f1/f2/alt` AND `pin_button_r/g/b/y/c/m`). Per Q4 we collapse this:

### 2.1 Hardware config (in `/settings.json` → `hardware`)
Six canonical buttons, each with a GPIO pin number:

| Name   | Default pin | Row             |
| ------ | ----------- | --------------- |
| `off`  | 16          | 1 (mode panel)  |
| `auto` | 17          | 1               |
| `on`   | 18          | 1               |
| `f1`   | 20          | 2 (function row)|
| `f2`   | 21          | 2               |
| `alt`  | 22          | 2               |

Remove `pin_button_r/g/b/y/c/m` from the hardware config and from the options.html “Game buttons” section.

### 2.2 Game configs reference button names
Each game config maps **game actions → button names**, never to pin numbers. The button-handler resolves name → pin at runtime.

Example (Snake, in `/settings.json` → `game`):
```json
{
  "buttons": {
    "shoot_red":   "off",
    "shoot_green": "auto",
    "shoot_blue":  "on",
    "shoot_yellow":"f1",
    "shoot_cyan":  "f2",
    "shoot_magenta":"alt"
  }
}
```

The web options page renders this as: “**Shoot red ball with**: [Off button ▾]”, with a dropdown of the 6 button names. Snake’s defaults match today’s behavior so existing users see no change.

### 2.3 Web options UI
- Hardware section: 6 inputs (Off / Auto / On / F1 / F2 / Alt → pin number).
- Game-1 (Snake) section: 6 dropdowns mapping `shoot_*` → button name.
- Game-2 / Game-3 sections: their own action-to-button-name dropdowns (see §5.6, §6.6).

### 2.4 Compatibility
On boot, `config.py` reads the new flat 6 pins. `lib/game.py` switches its internal `_game_color_by_btn` from the pin-aliasing approach to reading `game.buttons` dict (with the defaults above). Any old `pin_button_r..m` keys in an existing `/settings.json` are silently ignored.

---

## 3. Shared infrastructure: `lib/game_common.py`  ✅ DONE

Extract from `lib/game.py` only what the new games genuinely need to reuse. Keep the module small; avoid premature abstraction.

Initial contents:
- `load_game_overrides(slot)` — reads `/settings.json` and returns the dict at the given top-level key (`"game"`, `"game2"`, `"game3"`).
- `resolve_count(value, total)` — dual-meaning helper (< 1 = fraction, ≥ 1 = exact LED count). Used by all three games.
- `load_highscore(path)` / `save_highscore(path, data)` — generic dict-shaped highscore I/O. Snake’s usage stays integer-shaped via a thin wrapper in `game.py`.
- `BaseGame` — minimal abstract: holds `led`, `storage`, `state`, `_lock`, `_pending_*` queues, `is_active()`, `on_active_change`, and a `tick()` that calls subclass `_drain_pending_inputs(now)` / `_advance_state(now)` / `_render()`. Snake refactor to inherit it is **out of scope** for this change — Snake keeps its current structure unmodified except for the button-name lookup change in §2.4. New games inherit from `BaseGame`.

`main.py` instantiates all three games and exposes them as `self.snake` (= today’s `self.game`), `self.simon`, `self.mastermind`. The main loop still calls all three `.tick()`s every iteration; only one will be active at a time. The “refuse if busy” check lives in each game’s `start()` — it consults the others via a small `GameRegistry` passed in at construction, returning False if any other game is active. The web API returns 409 in that case.

`ButtonHandler.set_game_input_mode(active)` continues to be wired through `on_active_change`; only one game is ever active so there is no conflict.

---

## 4. Snake (Game 1) — changes  ✅ DONE

Only two changes:
1. **Internal**: switch `_game_color_by_btn` lookup from “pin-alias” to “read `game.buttons` from settings, fall back to the defaults in §2.2 table”.
2. **Abort key**: ALT+F1 abort goes away (§1). The Snake game responds to the universal F1-held-3s abort instead.

No gameplay, rendering, or API changes. The `/api/game/upgrade` legacy endpoint remains as-is.

The index page menu replaces the single “Start game” button with a list (see §7).

---

## 5. Game 2: Simon Says  ✅ DONE
*Implementation note: §5.3 spec said the red/green 3× flash supersedes the per-press color feedback, but in practice that hides the user's keypress. Code instead always shows the press color first (`press_feedback` state, ~150 ms), then the red/green flash. Update spec next time it changes.*

### 5.1 Files
`lib/game2.py`, `web/game2.html`, `web/game2.js`, `/game2.json` (highscore), `/api/game2/*` routes.

### 5.2 Gameplay rules
- Sequence of colors from the set **R, G, B, Y** (4 colors only).
- Round 1: sequence length 1. Each correct round adds one random color to the end of the sequence (sequence grows by 1 each round; the prefix is identical to the previous round, with one new color appended).
- The strip fills the **defined playfield** (start LED → end LED) with each color in turn:
  - 750 ms ON
  - 250 ms OFF (gap between colors)
- After the full sequence has played, the strip enters the **input phase** for the player to replay it.
- Player must press the buttons in the same order as the sequence.
- Each player press triggers immediate per-press feedback (see §5.3).
- A single press has up to **3 seconds** to be entered, indicated by a countdown (see §5.4). Failure to press in time = wrong.
- On a wrong press OR timeout: flash entire playfield **red 3× (250 ms on / 250 ms off)**, then show the score for **3 seconds** (see §5.5), then return to lighting.
- On the final correct press of the sequence: flash entire playfield **green 3× (250 ms on / 250 ms off)**, then immediately go dark and start the next round (sequence + 1).
- Score = the longest sequence length the player completed correctly. (i.e. if they busted on round 7 after completing round 6, score = 6.)

### 5.3 Per-press feedback
- When the player presses a button during input phase, briefly fill the playfield with that color (replacing the current countdown view) for ~150 ms, then return to the countdown for the next input.
- If the press was correct AND was the final press of the sequence, the green-3× flash supersedes the per-press feedback.
- If the press was wrong, the red-3× flash supersedes the per-press feedback.

### 5.4 Countdown rendering
- The per-press timer is shown as **white LEDs in the center of the playfield**.
- For an N-second countdown (default N = 3), the schedule is:
  - **t = 0 ms**: light **N + 1** white LEDs (default 4), centered on the playfield midpoint; if playfield is even-length, prefer the home-side pair.
  - **t = 250 ms**: pop one LED (now N lit).
  - **t = 1000 ms**: pop one LED (now N − 1 lit).
  - **t = 2000 ms**: pop one LED (now N − 2 lit).
  - …continue popping one per full second…
  - **t = N × 1000 ms** (= 3000 ms for N=3): pop the last LED. Zero lit → time’s up, round over (wrong-result path).
- Generalized: first pop at **+250 ms**, every subsequent pop on the next full-second boundary (+1000 ms, +2000 ms, …, +N × 1000 ms).
- The countdown is shown only during the input phase, between presses. It restarts at N + 1 LEDs after each correct press.

### 5.4a Configurable countdown length
- `input_timeout_ms` controls N (= `input_timeout_ms / 1000`). The initial LED count is always **N + 1**; this supersedes the older `countdown_leds` field.
- For N = 3 (default): 4 LEDs initially, pops at 250, 1000, 2000, 3000 ms.
- For N = 5: 6 LEDs initially, pops at 250, 1000, 2000, 3000, 4000, 5000 ms.
- `input_timeout_ms` should be a whole number of seconds for clean visuals; the sanitizer rounds down to the nearest 1000.

### 5.5 End-of-game score display
- After the red-3× wrong flash: light **N white LEDs starting from the FAR end** (the player’s “far” = away from home, same convention as Snake’s level/highscore display), where N = the score (longest correctly-completed sequence length).
- Hold for 3 seconds, then return to lighting mode.
- If N exceeds the playfield length, just light the entire playfield white (don’t wrap, don’t scroll).

### 5.6 Web-configurable settings (`/settings.json` → `game2`)
Defaults shown:
```json
{
  "playfield_start_led": 0,
  "playfield_end_led": -1,
  "flash_on_ms": 750,
  "flash_off_ms": 250,
  "input_timeout_ms": 3000,
  "press_feedback_ms": 150,
  "result_flash_ms": 250,
  "result_flash_count": 3,
  "score_display_ms": 3000,
  "buttons": {
    "input_red":    "on",
    "input_blue":   "auto",
    "input_yellow": "f1",
    "input_green":  "f2"
  }
}
```

Field notes:
- `playfield_start_led` / `playfield_end_led` are strip indices, inclusive. `playfield_end_led = -1` means `NUM_LEDS - 1`.
- `input_timeout_ms` controls the per-press countdown length; see §5.4 / §5.4a. Initial LED count is `(input_timeout_ms / 1000) + 1`. Sanitizer rounds down to the nearest whole second.
- `result_flash_ms` is the on/off duration for both red (wrong) and green (correct) flashes.

### 5.7 Highscore (`/game2.json`)
```json
{ "highscore": 0 }
```
Update only on game over, only if the new score exceeds the stored value. Display in web UI; LED display of highscore is **not implemented in this iteration**.

### 5.8 Buttons in-game
Per §1, all keys are remapped while Simon Says is active. The default mapping forms a **square 2×2 keypad** spanning the on/auto row-1 buttons and the f1/f2 row-2 buttons (mirroring the physical layout of a typical 4-color Simon device):

| Color  | Default button | Physical position |
| ------ | -------------- | ----------------- |
| Red    | `on`           | row 1, right      |
| Blue   | `auto`         | row 1, middle     |
| Yellow | `f1`           | row 2, left       |
| Green  | `f2`           | row 2, middle     |

- All four mapped buttons are **valid color inputs during play** — including F1 and F2. The lighting-mode meanings of F1 (enter game-select) and F2 (no-op in lighting mode; only meaningful inside game-select) do **not** apply while a game is active.
- Unmapped buttons (in the default mapping: `off` and `alt`) are no-ops during play.
- F1-held-3s remains the universal abort (§1). The 3-second hold is detected independently of the press-edge color input — if the player presses F1 and releases before 3 s, it counts as a yellow input; if they hold past 3 s, the game aborts and the press-edge yellow input is discarded.
- The mapping is fully overridable via the `buttons` block in `/settings.json` → `game2`. Any of the 6 hardware buttons may be assigned to any color.

### 5.9 Web UI (`web/game2.html` + `web/game2.js`)
- 4 buttons: R, G, B, Y. Same visual style as Snake’s 6-button grid but only the 4 colors used.
- Keyboard: **A=R, S=G, D=B, Q=Y** (matching Snake’s ASD/QWE convention; W/E unused for Simon).
- “Start” / “Stop” buttons only — no level / restart inputs.
- The 4 color buttons fire `/api/game2/input { "color": "R" }`. The page POSTs `/api/game2/start` on load, `/api/game2/stop` via Stop or `pagehide`.
- Show current round number / current score and the highscore as text, polled from `/api/game2/status` every ~500 ms while the game is active.

### 5.10 API
- `POST /api/game2/start` → `{ success: true }` or `{ success: false, error: "busy" }` (409).
- `POST /api/game2/stop` → `{ success: true }`.
- `POST /api/game2/input` `{ "color": "R"|"G"|"B"|"Y" }` → `{ success: true }`.
- `GET  /api/game2/status` → `{ active, round, score, highscore, phase }` where `phase ∈ "playing_sequence"|"awaiting_input"|"feedback"|"score_display"|"inactive"`.

---

## 6. Game 3: Master Mind  ⏳ TODO (only outstanding game)

### 6.1 Files
`lib/game3.py`, `web/game3.html`, `web/game3.js`, `/game3.json` (highscores), `/api/game3/*` routes.

### 6.2 Gameplay rules
- Code length **L** is selectable per game; default 4, range 3–6.
- Color palette: **R G B Y C M** (6 colors). White is dropped (one per physical button).
- Codes can repeat colors. The secret is an **ordered sequence**: position matters. `RRGB` and `RGBR` are different secrets and only the exact ordered match wins.
- The game generates a uniformly-random secret of length L (each position independently sampled from the 6-color palette, with repetition allowed).
- Player has up to **10 guesses**.
- Player constructs a guess by pressing L color buttons in order. Each press is **locked in** immediately (no backspace, no submit button). After the L-th press, the guess auto-evaluates.
- Feedback per guess:
  - **GREEN LEDs** = number of colors that are correct AND in the correct position (= original Mastermind’s “black peg”).
  - **RED LEDs** = number of colors that are correct color but in the wrong position (= “white peg”).
  - Exactly the standard Mastermind scoring (no double-counting).
- Win = all L green pegs in one guess. Show win animation, save highscore, return to lighting.
- Loss = 10 guesses without win. Show the secret revealed, hold for 5 s, return to lighting.

### 6.3 Playfield rendering
Per Q14/Q15:

A **row** is `xxxx%yyyy%` style with **L guess LEDs + 1 separator + L feedback LEDs + 1 separator** = `2L + 2` LEDs per row, **stacked**:
```
%xxxx%yyyy%xxxx%yyyy%xxxx%yyyy%
```
The first row’s leading `%` is shared with the strip’s home-end boundary, so the home-end of the playfield begins with a separator. Each subsequent row begins immediately after the previous row’s trailing `%`. No gap between rows.

- Separator (`%`) = white at 20 % brightness (per the implement spec). Always lit while the game is in progress.
- Guess slot (`x`) = the color the player pressed for that position.
- Feedback slot (`y`) = green/red LEDs counting per §6.2 — pack greens first (closest to the leading `%`), then reds, then dark for unused slots.

**Layout direction**: rows fill **from the home end** toward the far end (newest guess at home end, oldest scrolls toward the far end / off the strip). FIFO: when a new row is added, all previous rows shift one row toward the far end.

**Modulus / no partial rows**: `rows_visible = (playfield_length - 1) // (2L + 1)`. The leading `%` at home counts once; each row consumes `2L + 1` LEDs after that. If the strip can fit fewer rows than the player has played, the oldest rows are simply not rendered (shifted off the far end). Never render a partial row.

(With a 12-LED strip and L=4, `rows_visible = (12 - 1) // 9 = 1` — only the most recent row visible. Acceptable.)

### 6.4 Length-select phase
Triggered by selecting Master Mind in the game-select carousel (§1.1) and pressing F2 to start. (Web: `/api/game3/start` with no `length` param → enters length-select; with `length` param → starts directly.)

- The strip lights N white LEDs from the home end where N = current selected length (initial = `default_length`, or last-used).
- Each F1 press: length += 1; if > `max_length` wrap to `min_length`. Re-render.
- F2 press: confirms length, starts game.
- F1-held-3s: aborts back to lighting mode.
- ALT and other keys: ignored in length-select.
- Length-select has no idle timeout of its own (the 10-s idle timeout is on the game-select carousel only). Once the player has reached length-select, only F1, F2, or F1-held-3s exit it.

### 6.5 Input behavior during play
- All 6 hardware buttons are **valid color inputs during play**, per the `buttons` mapping in §6.6. The default mapping uses every button: R=off, G=auto, B=on, Y=f1, C=f2, M=alt. F1, F2, and ALT therefore all fire color inputs during a running game — their lighting-mode meanings (F1 = enter game-select; F2 = no-op outside game-select; ALT = no game-start meaning) do not apply while a game is active.
- Each color button press is locked in immediately as the next position of the current guess. After L presses, the guess is evaluated and rendered as a new row at the home end.
- After evaluation, the row is held for **5 seconds** to let the player read the feedback. The next guess is **blocked during this 5 s window**, EXCEPT:
  - **Early-input override**: if the player presses a color button during the 5 s window, the hold is cancelled immediately, the press IS counted as the first press of the next guess, and input proceeds normally.
- F1-held-3s: universal abort. The 3-second hold is detected independently of the press-edge color input — if the player presses F1 and releases before 3 s, it counts as a yellow input; if they hold past 3 s, the game aborts and the press-edge yellow input is discarded.

### 6.6 Web-configurable settings (`/settings.json` → `game3`)
Defaults shown:
```json
{
  "playfield_start_led": 0,
  "playfield_end_led": -1,
  "default_length": 4,
  "min_length": 3,
  "max_length": 6,
  "max_guesses": 10,
  "feedback_hold_ms": 5000,
  "reveal_hold_ms": 5000,
  "separator_brightness": 0.20,
  "buttons": {
    "input_red":     "off",
    "input_green":   "auto",
    "input_blue":    "on",
    "input_yellow":  "f1",
    "input_cyan":    "f2",
    "input_magenta": "alt"
  }
}
```

Length must satisfy `3 ≤ default_length ≤ 6` and `min_length ≤ max_length` within `[3, 6]`. Sanitizer in storage clamps these.

### 6.7 Highscore (`/game3.json`)
Per-length best (fewest guesses to win):
```json
{ "highscore": { "3": 0, "4": 0, "5": 0, "6": 0 } }
```
- A value of 0 means “no record yet”.
- On win, `guesses_used` becomes the new record if smaller than the stored value (or if stored is 0).
- On loss: no update.
- Web UI shows all four records.

### 6.8 Win / loss animations
- **Win**: flash the playfield green 3× (same cadence as Simon: 250 ms on / 250 ms off), then return to lighting. Save highscore.
- **Loss**: render the secret as a single row `%secret_colors%[empty feedback]%` at the home end, holding all previous rows where they are. Hold for 5 s, then return to lighting.

### 6.9 Web UI (`web/game3.html` + `web/game3.js`)
- 6 color buttons in a 2×3 grid mirroring the physical layout:
  - Row 1: R (off), G (auto), B (on)
  - Row 2: Y (f1), C (f2), M (alt)
- Keyboard: **A=R, S=G, D=B, Q=Y, W=C, E=M** (same as Snake).
- A length picker (number input 3–6) and a Start / Stop pair. Posting `/api/game3/start { length: N }` starts directly at length N; posting with no length enters length-select mode (unused from web — web always provides a length).
- During play, show: current guess being assembled (e.g. “R G _ _”), guesses used / 10, per-length highscores.
- Each color button posts `/api/game3/input { color: "R" }`.
- `pagehide` triggers stop.

### 6.10 API
- `POST /api/game3/start` body `{ "length": 4 }` (optional; if omitted → length-select mode) → `{ success, length }` or 409 if busy.
- `POST /api/game3/stop` → `{ success: true }`.
- `POST /api/game3/input` `{ "color": "R"|"G"|"B"|"Y"|"C"|"M" }` → `{ success: true }` (silently ignored if not in input phase).
- `GET  /api/game3/status` → `{ active, phase, length, current_guess: ["R","G",null,null], guesses_used, history: [{guess, greens, reds}, ...], highscore: {3,4,5,6} }`.

---

## 7. Index page (menu)  🟡 PARTIAL (Snake + Simon Says listed; add Master Mind when §6 ships)

Replace the single “Start game” button under the “Game” card with a list of three buttons:
- **Snake** → `/game`
- **Simon Says** → `/game2`
- **Master Mind** → `/game3`

Same `.btn` styling as today; stack vertically on mobile, inline on desktop. No dropdown.

---

## 8. Storage / sanitizer changes  🟡 PARTIAL (game2 + last_game shipped; game3 sanitizer pending)

`lib/storage.py`:
- Add `_sanitize_game2(d)` and `_sanitize_game3(d)`, modeled on the existing `_sanitize_game`. Allow only known keys; clamp ranges (e.g. Master Mind length to 3–6, max_guesses ≥ 1, brightnesses to [0,1], ms values ≥ 1).
- The `buttons` sub-dict: validate each value is one of `"off","auto","on","f1","f2","alt"`; drop unknown entries, fall back to defaults for missing entries.
- Extend `update_settings` to recognise `game2` and `game3` top-level keys and route them through their sanitizers.
- `_sanitize_hardware` no longer accepts `pin_button_r/g/b/y/c/m` keys (drop them).
- Add top-level `last_game` key (per §1.1, F2 quick-start). Sanitizer accepts only `"snake" | "simon" | "mastermind"`; unknown/missing → `"snake"`. Updated by `main.py` whenever any game transitions to active.

`lib/config.py`:
- Remove `PIN_BUTTON_R..M` constants and their defaults from `_HARDWARE_DEFAULTS`.

---

## 9. main.py wiring  🟡 PARTIAL (Snake + Simon wired; add Master Mind when §6 ships)

```python
self.snake      = Game(self.led, self.storage, registry)
self.simon      = SimonGame(self.led, self.storage, registry)
self.mastermind = MasterMindGame(self.led, self.storage, registry)
registry.register(self.snake, self.simon, self.mastermind)

for g in (self.snake, self.simon, self.mastermind):
    g.on_active_change = lambda active: self.buttons.set_game_input_mode(active)
```

The main loop:
- Calls `.tick()` on all three each iteration.
- `is_active()` aggregated via `registry.any_active()`; if true, the lighting-mode `_update_mode()` early-exits (same as today’s single-game check).
- Button dispatch reads which game is active (registry.current_active()) and routes inputs accordingly. The button-handler emits a uniform action dict; each game’s `handle_button_action(action)` interprets it.

---

## 10. Web server routes  🟡 PARTIAL (game2 routes shipped; game3 routes pending)

Add to `lib/web_server.py`:
- Static: `/game2`, `/game2.html`, `/game2.js`, `/game3`, `/game3.html`, `/game3.js`.
- API: the eight endpoints listed in §5.10 and §6.10.
- `409 Conflict` JSON `{success: false, error: "busy"}` when start is refused.

The constructor takes the registry (or all three game references); existing `game` parameter becomes `snake` for clarity but the type is the same.

---

## 11. Out of scope (explicit non-goals)

- No on-LED highscore display for Simon Says or Master Mind in this iteration (web UI only).
- No refactor of Snake into a `BaseGame` subclass beyond the button-name lookup change.
- No change to the file-management or scheduler subsystems.
- No new “games tab” in options.html beyond the two new sub-sections (game2, game3) following the existing options pattern.
- No multi-player / network play.

---

## 12. Implementation order (suggested)
*Update: §1–§5 + §7-partial + §8-partial + §9-partial + §10-partial are merged on `feature/more-games`. Remaining order is just §6 (Master Mind) + finishing the partial sections to include game3.*

1. §1 + §2: button refactor + universal F1-3s abort. Make sure Snake still plays.
2. §3: extract `lib/game_common.py` with `BaseGame` and helpers.
3. §5: implement Simon Says end-to-end (lib + web + API + storage sanitizer + options UI).
4. §6: implement Master Mind end-to-end.
5. §7: index menu update.
6. End-to-end manual test on hardware: each game starts/aborts cleanly, refuse-if-busy works, web UI works, settings persist.
