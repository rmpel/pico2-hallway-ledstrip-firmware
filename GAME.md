# Game Mode — Color-Matching Defense

A one-player color-matching shooter that runs on the LED strip as an interactive overlay on top of normal HallwayLedBar operation. The persisted lighting mode is untouched while a game runs; ending the game (win-out, lose, abort) automatically returns to whatever Off/Auto/On/Rainbow mode was active before.

## Concept

A randomly-colored snake of "balls" extrudes from the **enemy base** at the far end of the LED strip and creeps toward the **player** at the home end. The player fires colored balls from home, matching the snake's head color to remove balls one-by-one. Two safety lines exist:

- **Home barrier** (player's shield): close to the player end. If the snake's head touches it → game over.
- **Enemy shield**: near the far end, between the snake's tail and the enemy base. The shield is always visible (cracking with random white-yellow energy) but only **shootable** when the snake's tail has retreated past it. Hitting the exposed enemy shield with any ball wins the level instantly.

Win the level by either fully clearing the snake **or** punching a shot through to the enemy shield. Lose if the head reaches the home barrier.

## Geometry

The LED strip is split into:

- **Status LED** (LED 0) — never used by the game.
- **Skipped LEDs at the home end** (`HOME_SKIP_LEDS` from the home end of the addressable strip) — compensation for hard-to-see LEDs.
- **Playfield** — everything between the two skip zones. Ball positions and snake render coordinates are expressed as `pf_idx ∈ [0, _pf_len)` where `pf_idx = 0` is the home (player) side and `pf_idx = _pf_len - 1` is the far (enemy) side.
- **Skipped LEDs at the far end** (`END_SKIP_LEDS`).

Within the playfield:

- **Home barrier** sits at `_resolve_count(BARRIER_FRACTION, _pf_len)` LEDs in from the home end.
- **Enemy shield** is anchored to the **far end**. Its from-end offset is level-dependent: `from_end = max(ENEMY_SHIELD_FRACTION_MAX, ENEMY_SHIELD_FRACTION - ENEMY_SHIELD_FRACTION_PER_LEVEL * (level - 1))`, then `idx = _pf_len - 1 - from_end`. Each level subtracts the per-level value, so the shield retreats further toward the enemy base; `MAX` is the **floor** in the from-end frame (must be smaller than the base value), guaranteeing the shield never reaches the very last LED.

**Dual-meaning values.** `BARRIER_FRACTION`, `ENEMY_SHIELD_FRACTION`, `ENEMY_SHIELD_FRACTION_PER_LEVEL`, `ENEMY_SHIELD_FRACTION_MAX`, `START_FRACTION`, and `MAX_FRACTION` accept either a fraction (`< 1`, scaled by playfield length) or an exact LED count (`>= 1`, used as-is). The resolver lives in `lib/game.py` as `_resolve_count(value, pf_len)`. This lets the same configuration value behave sensibly across short and long strips: small fractions on long strips, exact counts when fractions would round to 0.

The **head** of the snake is the home-side end of the snake (closest to the player — the engagement end). The **tail** is the far-side end, anchored at `pf_len - 1`. The snake renders in a contiguous block; new balls are appended at the tail and the whole block shifts toward the player on each grow tick.

## Game Flow

```
inactive
  └─► start()
intro_flash       ─ flash the last N LEDs white N times (N = current level)
  └─► intro_highscore
intro_highscore   ─ paint the last H LEDs green (H = stored highscore),
                    re-flash the level number on top
  └─► intro_materialize
intro_materialize ─ random-color snake materializes one LED at a time from
                    the far end inward to the level's starting length
  └─► playing
playing           ─ snake creeps toward home; player fires; each grow-tick
                    appends a random color at the tail and shifts the head
                    one LED closer to the home barrier
  ├─► snake cleared OR enemy shield hit  ─► win_anim ─► next level intro_flash
  └─► snake head touches home barrier    ─► gameover_anim ─► inactive
```

**Win animation:** white sweep home→far, fade to black, then the next level's intro starts.

**Game-over animation:** the snake immediately stops growing and **marches home** at an accelerated pace; each ball that walks off the home edge of the playfield increments a speed multiplier (so the march visibly accelerates as the snake unloads). Once the snake is fully gone, the highscore is saved (if beaten) and lighting mode resumes.

## Color Palette by Level

The palette of colors that appear in the snake widens as the level increases:

| Level | Snake palette |
|-------|----------------|
| 1–2   | R, G, B |
| 3     | R, G, B, **C** |
| 4     | R, G, B, C, **Y** |
| 5+    | R, G, B, C, Y, **M** |

The player can fire any of the 6 colors directly via dedicated buttons (see [Controls](#controls)).

**The very first head is always a primary** (R/G/B), regardless of level palette. This guarantees the player can match the starting head from the first moment, even at level 5+ where the snake palette includes mixes. After the first head is destroyed, subsequent heads come from the level palette as normal.

At level **`BALL_BECOMES_HEAD_LEVEL`** (default 5) and above, firing a wrong-color ball at the snake's head causes that ball to **become the new head** instead of vanishing. This punishes mis-shots at higher levels.

## Shields

### Home barrier (player's shield)

- White, ~20% brightness, with random white-yellow crackle.
- Always visible during play.
- The snake's head reaching this LED ends the game.
- Renders **on top of** in-flight balls (a ball passing under it is overdrawn).

### Enemy shield

- Cyan-amber crackle (random white/yellow energy at ~30% brightness).
- Always visible during play. Position scales with level (see Geometry).
- **Shootable** as soon as the snake's head reaches the shield position. (Visually, with the snake-around-shield render trick, the head appears displaced past the shield at that moment — so the shield is what the player sees in front, and shooting it wins.)
- A ball reaching the exposed shield instantly wins the level. Shield-hit is checked before snake-hit, so the shield always wins ties when both could fire on the same step.

### Snake-around-shield rendering trick

The snake passes "through" the enemy shield: any snake ball whose logical position lands at or past the shield's LED is rendered shifted one LED toward the tail. This visually inserts the shield "between" the head-side and tail-side halves of the snake, keeping the head ball visible even when it's logically at the shield's position. (This is geometrically incorrect — the snake appears one LED longer when it overlaps the shield — but it's a deliberate gameplay aid.)

## Ball Mechanics

### Firing balls

- Each color (R, G, B, Y, C, M) has its own dedicated input — no chord/combo logic. Press a button, get one ball of that color.
- Press fires immediately on the **down-edge** (zero input lag).
- A short debounce (`BALL_DEBOUNCE_MS`, default 60ms) prevents two balls from overlapping on the same LED.
- Each ball is a single bright LED that travels from the home end of the playfield toward the snake's head at constant speed (`BALL_TICK_MS`, default 60ms per LED).
- Below the home barrier, the ball renders dimmer the further it is from the barrier (brightness ramp from `BARRIER_BRIGHTNESS` at home to full at barrier). Above the barrier it's full brightness.
- The home barrier LED renders on top, so a ball passing under it is briefly hidden.

### Resolving a hit

When an in-flight ball reaches the snake's head:
- **Same color** → both vanish (head ball removed; snake's head retreats one LED toward the far end).
- **Wrong color, level < `BALL_BECOMES_HEAD_LEVEL`** → ball vanishes; snake unchanged.
- **Wrong color, level ≥ `BALL_BECOMES_HEAD_LEVEL`** → ball becomes the new head; snake grows by one toward the player.

A ball can never traverse the snake — collisions stop at the head.

## Scoring & Highscore

- **Score** = the highest level reached (or attempted, on game over).
- **Highscore** is persisted in `/game.json` as `{"highscore": <int>}`.
- On game over, if `level > highscore`, the new highscore is saved.
- During each level's intro, the highscore is visualized as a green underlay: the last H LEDs from the far end light green (H = stored highscore), then the level number flashes white over it.

## Controls

### Physical buttons

All six buttons fire a colored ball directly on press. Row 1 maps to the primaries (configurable via `PIN_BUTTON_R/G/B`); row 2 maps to the mixes. F1 and F2 also serve as level-adjust before the first shot.

| Button       | Push (in game)                                                                  | Push + ALT                            |
|--------------|----------------------------------------------------------------------------------|---------------------------------------|
| **OFF**      | shoot R *(via PIN_BUTTON_R alias)*                                               | shoot R                               |
| **AUTO**     | shoot G                                                                          | shoot G                               |
| **ON**       | shoot B                                                                          | shoot B                               |
| **F1**       | pre-shot: level +1; post-shot: shoot Y                                           | abort game (side-effect shots ignored) |
| **F2**       | pre-shot: level −1 (min 1); post-shot: shoot C                                   | shoot C                               |
| **ALT**      | shoot M                                                                          | (n/a — modifier)                      |

The in-game level adjust (F1/F2) is locked the moment the player fires their first ball this game. The transition is automatic: pre-shot, F1/F2 adjust the level (the press-edge color shot is suppressed). Once any ball has been fired, F1/F2 fire Y/C as their press-edge color.

ALT+F1 always aborts the game, regardless of shot state. Side-effect color shots from the same press are intentionally allowed (the game is being torn down anyway).

All-3 row-1 buttons together = no-op in game (this used to be the abort combo, replaced by ALT+F1).

### Web game UI

Visit `/game` in a browser:

- Six large color buttons in a 3×2 grid: top row R/G/B, bottom row Y/C/M.
- **Back** button: aborts the game and returns to the home page.
- **Start at level** input + **Restart** button: stops the current game and starts fresh at the specified level.
- The page calls `POST /api/game/start` on load (level 1, or the `?level=N` query parameter).

Each button fires its color independently — no chord/multi-touch logic. `touch-action: manipulation` is set to suppress mobile double-tap zoom delays.

### Keyboard

- **A / S / D** — fire R / G / B
- **Q / W / E** — fire Y / C / M

`keydown` is tracked with `e.repeat` filtered. Each key fires one ball.

## Web / REST API

| Endpoint                | Method | Body                              | Notes                                              |
|-------------------------|--------|-----------------------------------|----------------------------------------------------|
| `/game` or `/game.html` | GET    | —                                 | Serves the game UI page                            |
| `/game.js`              | GET    | —                                 | Game UI JavaScript                                 |
| `/api/game/start`       | POST   | `{"level": <int>}` (optional)     | Starts a new game; defaults to level 1             |
| `/api/game/stop`        | POST   | —                                 | Aborts the current game; no highscore save         |
| `/api/game/shoot`       | POST   | `{"color": "R"\|"G"\|"B"\|"Y"\|"C"\|"M"}` | Fires one ball of the given color           |
| `/api/game/upgrade`     | POST   | `{"mix": "Y"\|"C"\|"M"}`          | Legacy alias for shoot(mix). Kept for backward-compat with older clients |

All endpoints return `{"success": true}` on success, `{"success": false, "error": "..."}` on failure, with appropriate HTTP status. They are safe to call even when the game is not active (start is the only state-transitioning call; the rest are no-ops if `state != "playing"`).

## Tunables

All tunables live at the top of `lib/game.py`. Defaults shown.

### Playfield geometry
| Constant              | Default | Meaning |
|------------------------|---------|---------|
| `HOME_SKIP_LEDS`       | 2       | LEDs at home end excluded from playfield |
| `END_SKIP_LEDS`        | 1       | LEDs at far end excluded from playfield |
| `BARRIER_FRACTION`     | 0.05    | Home barrier position from home end. Dual-meaning (fraction or LED count) |
| `BARRIER_BRIGHTNESS`   | 0.20    | Home barrier crackle intensity (0..1) |
| `ENEMY_SHIELD_FRACTION` | 0.3    | Enemy shield base offset from FAR end at level 1. Dual-meaning |
| `ENEMY_SHIELD_FRACTION_PER_LEVEL` | 0.05 | Subtracted from offset each level (shield retreats toward enemy). Dual-meaning |
| `ENEMY_SHIELD_FRACTION_MAX` | 0.1   | Floor for the from-end offset (closest to far end the shield can retreat). Must be < base. Dual-meaning |
| `ENEMY_SHIELD_BRIGHTNESS` | 0.30 | Enemy shield crackle intensity (0..1) |

### Snake
| Constant            | Default | Meaning |
|---------------------|---------|---------|
| `START_FRACTION`    | 0.50    | Level-1 starting snake length. Dual-meaning (fraction or LED count) |
| `GROW_PER_LEVEL`    | 2       | Extra LEDs per level (always exact LED count) |
| `MAX_FRACTION`      | 0.75    | Cap on starting snake length. Dual-meaning |
| `GROW_TICK_MS`      | 1500    | Snake step interval at level 1 |
| `GROW_SPEEDUP_MS`   | 75      | Shaved per additional level |
| `GROW_TICK_MIN_MS`  | 300     | Floor for grow interval |

### Balls
| Constant                 | Default | Meaning |
|--------------------------|---------|---------|
| `BALL_TICK_MS`           | 60      | Per-LED ball travel time |
| `BALL_DEBOUNCE_MS`       | =BALL_TICK_MS | Min spacing between consecutive launches |
| `BALL_BECOMES_HEAD_LEVEL`| 5       | At this level and up, wrong-color ball joins snake |
| `PENDING_SHOTS_CAP`      | 8       | Max queued shoots/upgrades to prevent runaway memory |

### Animations
| Constant              | Default | Meaning |
|-----------------------|---------|---------|
| `INTRO_FLASH_ON_MS`   | 150     | Level-flash on duration |
| `INTRO_FLASH_OFF_MS`  | 150     | Level-flash off duration |
| `INTRO_HS_HOLD_MS`    | 800     | Hold green-highscore display before snake materializes |
| `INTRO_MATERIALIZE_MS`| 40      | Per-LED snake fill delay |
| `WIN_ANIM_STEP_MS`    | 25      | Per-LED sweep speed for win animation |
| `WIN_FADE_MS`         | 600     | Fade-to-black duration |
| `GAMEOVER_MARCH_SPEEDUP` | 4    | Initial march-home speedup vs. level grow cadence |

### Persistence
| Constant         | Default       | Meaning |
|------------------|---------------|---------|
| `HIGHSCORE_FILE` | `/game.json`  | Highscore JSON file |

## Architecture Notes

The `Game` class lives in `lib/game.py`. It owns its own state machine and runs entirely on core 0 (the main loop calls `Game.tick()` every iteration). Cross-thread input from the web server (core 1) is funneled through a small `_thread.allocate_lock()`-protected queue:

- `start(level)`, `stop()`, `shoot(color)`, `upgrade_last_ball(mix)`, `restart_at_level(level)` are all called from core 1 (or core 0 for physical buttons) and only enqueue intent.
- `Game.tick()` drains the queue at the top of each tick under the same lock, then runs the state machine and renders.

This keeps all snake/ball state mutation single-threaded on core 0, with no need for fine-grained locking inside the simulation.

When `Game.is_active()`, `main._update_mode()` defers to `Game.tick()` and skips the normal mode dispatcher. When the game ends, the persisted mode (Off/Auto/On/Rainbow in `settings.json`) resumes naturally.

## Wishlist / Future Work

- **Mega bomb** (white pulsating ball, slower travel, blast 10–20 head balls). Charged by a streak of perfect color matches. Stored up to 3, only one in flight at a time. Triggered by all-3 row-1 buttons together (or Space on keyboard). Visualized as bright white LEDs at the home end of the playfield.
- **Ball-in-flight cap** (max 5 primaries, bombs separate).
- **More games** — the `Game` class may eventually be renamed `BaseDefense` and joined by other modes (e.g., SimonSays). The mode-switching framework is ready for it.
