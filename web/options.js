// HallwayLedBar — setup page (Location + Reboot Time + Hardware)

let config = {};

// Mirrors lib/config.py _HARDWARE_DEFAULTS — used to pre-fill inputs when no
// override is set. Keep in sync with the firmware.
const HARDWARE_DEFAULTS = {
  pin_led_strip: 15,
  pin_button_off: 16, pin_button_auto: 17, pin_button_on: 18,
  pin_button_f1: 20, pin_button_f2: 21, pin_button_alt: 22,
  pin_button_r: 16, pin_button_g: 17, pin_button_b: 18,
  pin_button_y: 20, pin_button_c: 21, pin_button_m: 22,
  num_leds: 12, led_start_offset: 0, led_brightness_max: 255,
  rp_pico_2_neopixel_compat_mode: true,
  button_debounce_ms: 50, button_hold_ms: 1000, button_combo_ms: 10000,
  brightness_step: 2, hue_step: 5, saturation_step: 2,
  transition_update_ms: 1000,
};

const HARDWARE_BOOL_KEYS = new Set( ['rp_pico_2_neopixel_compat_mode'] );

// Mirrors lib/game.py _GAME_DEFAULTS — used to pre-fill inputs when no
// override is set. Keep in sync with the firmware.
const GAME_DEFAULTS = {
  home_skip_leds: 3, end_skip_leds: 0,
  barrier_fraction: 0.05, barrier_brightness: 0.20,
  enemy_shield_fraction: 0.3, enemy_shield_fraction_per_level: 0.05,
  enemy_shield_fraction_max: 0.1, enemy_shield_brightness: 0.30,
  start_fraction: 0.50, grow_per_level: 2, max_fraction: 0.75,
  grow_tick_ms: 3000, grow_speedup_ms: 100, grow_tick_min_ms: 300,
  ball_tick_ms: 60, ball_becomes_head_level: 5, pending_shots_cap: 8,
  intro_flash_on_ms: 150, intro_flash_off_ms: 150,
  intro_hs_hold_ms: 800, intro_materialize_ms: 40,
  win_anim_step_ms: 25, win_fade_ms: 600, gameover_march_speedup: 4,
};

const GAME_FRACTION_KEYS = new Set( [
  'barrier_fraction', 'barrier_brightness',
  'enemy_shield_fraction', 'enemy_shield_fraction_per_level',
  'enemy_shield_fraction_max', 'enemy_shield_brightness',
  'start_fraction', 'max_fraction',
] );

// Hardware-block keys whose inputs render inside the Game card. They're
// saved/reset alongside the game block so the user gets one logical "save"
// per card.
const GAME_HARDWARE_PIN_KEYS = [
  'pin_button_r', 'pin_button_g', 'pin_button_b',
  'pin_button_y', 'pin_button_c', 'pin_button_m',
];

async function loadConfig() {
  try {
    const r = await fetch( '/api/config' );
    config = await r.json();
    document.getElementById( 'latitude' ).value = config.location?.latitude ?? '';
    document.getElementById( 'longitude' ).value = config.location?.longitude ?? '';
    document.getElementById( 'rebootTime' ).value = config.reboot_time || '';
    populateHardware( config.hardware || {} );
    populateGame( config.game || {} );
  } catch (e) {
    showMessage( 'Failed to load configuration', 'error' );
  }
}

function populateHardware (hw) {
  for (const key of Object.keys( HARDWARE_DEFAULTS )) {
    const el = document.getElementById( 'hw_' + key );
    if (!el) continue;
    const value = (key in hw) ? hw[key] : HARDWARE_DEFAULTS[key];
    if (HARDWARE_BOOL_KEYS.has( key )) {
      el.checked = Boolean( value );
    } else {
      el.value = value;
    }
  }
}

async function postConfig (patch, okMsg) {
  try {
    const r = await fetch( '/api/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify( patch )
    } );
    if (!r.ok) {
      const txt = await r.text();
      showMessage( `Save failed (${r.status}): ${txt}`, 'error' );
      return null;
    }
    Object.assign( config, patch );
    showMessage( okMsg, 'success' );
    let body = {};
    try { body = await r.json(); } catch (_) {}
    return body;
  } catch (e) {
    showMessage( 'Failed to save', 'error' );
    return null;
  }
}

async function maybePromptReboot (response) {
  if (!response || !response.reboot_required) return;
  if (!confirm( 'Hardware changes require a reboot to take effect. Reboot now?' )) return;
  try {
    await fetch( '/api/reboot', {method: 'POST'} );
    showMessage( 'Rebooting…', 'info' );
  } catch (e) {
    showMessage( 'Reboot request failed', 'error' );
  }
}

async function saveLocation () {
  const lat = parseFloat( document.getElementById( 'latitude' ).value );
  const lon = parseFloat( document.getElementById( 'longitude' ).value );
  if (Number.isNaN( lat ) || Number.isNaN( lon )) {
    showMessage( 'Enter valid latitude and longitude', 'error' );
    return;
  }
  await postConfig( {location: {latitude: lat, longitude: lon}}, 'Location saved' );
}

async function saveRebootTime () {
  const v = document.getElementById( 'rebootTime' ).value || '';
  await postConfig( {reboot_time: v}, v ? `Reboot time set to ${v}` : 'Reboot time disabled' );
}

async function saveHardware () {
  const hw = {};
  for (const key of Object.keys( HARDWARE_DEFAULTS )) {
    const el = document.getElementById( 'hw_' + key );
    if (!el) continue;
    if (HARDWARE_BOOL_KEYS.has( key )) {
      hw[key] = el.checked;
      continue;
    }
    if (el.value === '') continue;
    const n = parseInt( el.value, 10 );
    if (Number.isNaN( n )) continue;
    hw[key] = n;
  }
  const response = await postConfig( {hardware: hw}, 'Hardware settings saved' );
  await maybePromptReboot( response );
}

async function resetHardware () {
  if (!confirm( 'Reset all hardware settings to defaults? Takes effect after reboot.' )) return;
  const response = await postConfig( {hardware: {}}, 'Hardware settings reset to defaults' );
  populateHardware( {} );
  await maybePromptReboot( response );
}

function populateGame (g) {
  for (const key of Object.keys( GAME_DEFAULTS )) {
    const el = document.getElementById( 'g_' + key );
    if (!el) continue;
    el.value = (key in g) ? g[key] : GAME_DEFAULTS[key];
  }
}

async function saveGame () {
  const game = {};
  for (const key of Object.keys( GAME_DEFAULTS )) {
    const el = document.getElementById( 'g_' + key );
    if (!el || el.value === '') continue;
    if (GAME_FRACTION_KEYS.has( key )) {
      const f = parseFloat( el.value );
      if (Number.isNaN( f )) continue;
      game[key] = f;
    } else {
      const n = parseInt( el.value, 10 );
      if (Number.isNaN( n )) continue;
      game[key] = n;
    }
  }
  // The six game-button pin inputs render inside the Game card but live in
  // the hardware block. Merge them into the existing hardware overrides so
  // we don't wipe other hardware keys.
  const hw = Object.assign( {}, config.hardware || {} );
  for (const key of GAME_HARDWARE_PIN_KEYS) {
    const el = document.getElementById( 'hw_' + key );
    if (!el || el.value === '') continue;
    const n = parseInt( el.value, 10 );
    if (Number.isNaN( n )) continue;
    hw[key] = n;
  }
  const response = await postConfig( {game, hardware: hw}, 'Game settings saved' );
  await maybePromptReboot( response );
}

async function resetGame () {
  if (!confirm( 'Reset all game settings to defaults? Takes effect after reboot.' )) return;
  // Reset the game block, and clear the six pin overrides from the hardware
  // block (other hardware keys preserved).
  const hw = Object.assign( {}, config.hardware || {} );
  for (const key of GAME_HARDWARE_PIN_KEYS) {
    delete hw[key];
  }
  const response = await postConfig(
    {game: {}, hardware: hw},
    'Game settings reset to defaults'
  );
  populateGame( {} );
  // Repopulate the six pin inputs with their defaults too.
  for (const key of GAME_HARDWARE_PIN_KEYS) {
    const el = document.getElementById( 'hw_' + key );
    if (el) el.value = HARDWARE_DEFAULTS[key];
  }
  await maybePromptReboot( response );
}

function showMessage (text, type) {
  const msg = document.getElementById( 'message' );
  msg.textContent = text;
  msg.className = 'message ' + type;
  msg.style.display = 'block';
  setTimeout( () => msg.style.display = 'none', 3000 );
}

loadConfig();
