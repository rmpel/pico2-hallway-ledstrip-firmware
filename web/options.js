// HallwayLedBar — setup page (Location + Reboot Time + Hardware)

let config = {};

// Mirrors lib/config.py _HARDWARE_DEFAULTS — used to pre-fill inputs when no
// override is set. Keep in sync with the firmware.
const HARDWARE_DEFAULTS = {
  pin_led_strip: 15,
  pin_button_off: 16, pin_button_auto: 17, pin_button_on: 18,
  pin_button_f1: 20, pin_button_f2: 21, pin_button_alt: 22,
  pin_button_r: 16, pin_button_g: 17, pin_button_b: 18,
  num_leds: 12, led_start_offset: 0, led_brightness_max: 255,
  rp_pico_2_neopixel_compat_mode: true,
  button_debounce_ms: 50, button_hold_ms: 1000, button_combo_ms: 10000,
  brightness_step: 2, hue_step: 5, saturation_step: 2,
  transition_update_ms: 1000,
};

const HARDWARE_BOOL_KEYS = new Set( ['rp_pico_2_neopixel_compat_mode'] );

async function loadConfig() {
  try {
    const r = await fetch( '/api/config' );
    config = await r.json();
    document.getElementById( 'latitude' ).value = config.location?.latitude ?? '';
    document.getElementById( 'longitude' ).value = config.location?.longitude ?? '';
    document.getElementById( 'rebootTime' ).value = config.reboot_time || '';
    populateHardware( config.hardware || {} );
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

function showMessage (text, type) {
  const msg = document.getElementById( 'message' );
  msg.textContent = text;
  msg.className = 'message ' + type;
  msg.style.display = 'block';
  setTimeout( () => msg.style.display = 'none', 3000 );
}

loadConfig();
