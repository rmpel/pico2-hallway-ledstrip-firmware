let config = {};
let originalConfigJson = '{}';
let currentEditingStep = null;
let dirty = false;
let statusTimer = null;
let previewDebounceTimer = null;
let previewInUse = false;
let deviceUtcEpoch = null;     // last reported UTC epoch from device
let deviceUtcEpochAt = null;   // Date.now() when we received it
let deviceTzOffset = 0;        // device's cached tz offset in seconds
let clockTimer = null;

async function loadConfig() {
  try {
    const response = await fetch( 'api/config' );
    config = await response.json();
    originalConfigJson = JSON.stringify( config );
    dirty = false;
    updateSaveBar();
    updateUI();
  } catch (error) {
    showMessage( 'Failed to load configuration', 'error' );
  }
}

async function loadStatus() {
  if (dirty) return;
  try {
    const response = await fetch( 'api/status' );
    const status = await response.json();

    document.getElementById( 'currentMode' ).textContent = status.mode.toUpperCase();
    Array.from( document.querySelectorAll( '.mode-control button' ) ).forEach( btn => {
      btn.classList.remove( 'btn-active' );
      if (btn.classList.contains( `mode-${status.mode}` )) {
        btn.classList.add( 'btn-active' );
      }
    } );

    // Show 'Resume schedule at next event' toggle only outside auto mode.
    const tempRow = document.getElementById( 'tempModeRow' );
    const tempBox = document.getElementById( 'tempModeToggle' );
    if (status.mode === 'auto') {
      tempRow.style.display = 'none';
    } else {
      tempRow.style.display = '';
      tempBox.checked = !!status.non_auto_is_temporary;
    }

    document.getElementById( 'wifiStatus' ).textContent = status.wifi.connected ?
      `Connected (${status.wifi.ip})` : 'Disconnected';

    deviceUtcEpoch = status.utc_epoch;
    deviceUtcEpochAt = Date.now();
    deviceTzOffset = status.tz_offset_seconds || 0;

    let ntpSuffix = '';
    if (status.ntp) {
      if (status.ntp.synced) {
        const minsAgo = Math.floor( status.ntp.last_sync_seconds_ago / 60 );
        ntpSuffix = ` (NTP: ${minsAgo}m ago)`;
      } else {
        ntpSuffix = ' (NTP: not synced)';
      }
    }
    document.getElementById( 'currentTimeUtc' ).dataset.suffix = ntpSuffix;

    if (status.sun_times) {
      // Stored as seconds since UTC midnight; add device tz offset to get
      // device-local wall-clock seconds-since-midnight, then format HH:MM.
      const offset = status.tz_offset_seconds || 0;
      const sunriseLocalSec = ((status.sun_times.sunrise_utc_seconds + offset) % 86400 + 86400) % 86400;
      const sunsetLocalSec = ((status.sun_times.sunset_utc_seconds + offset) % 86400 + 86400) % 86400;
      const fmtSec = s => `${pad2( Math.floor( s / 3600 ) )}:${pad2( Math.floor( (s % 3600) / 60 ) )}`;
      document.getElementById( 'sunTimes' ).textContent = `↑${fmtSec(sunriseLocalSec)} ↓${fmtSec(sunsetLocalSec)}`;
    } else {
      document.getElementById( 'sunTimes' ).textContent = 'Not calculated';
    }

    tickClocks();

    if (status.schedule_info && status.schedule_info.steps) {
      const container = document.getElementById( 'upcomingEvents' );
      container.innerHTML = status.schedule_info.steps.map( e => {
        const offsetStr = e.step.offset >= 0 ? `+${e.step.offset}` : e.step.offset;
        const tSec = ((e.time % 86400) + 86400) % 86400;
        const hours = Math.floor( tSec / 3600 );
        const minutes = Math.floor( (tSec % 3600) / 60 );
        const timeStr = `${hours.toString().padStart( 2, '0' )}:${minutes.toString().padStart( 2, '0' )}`;
        const label = e.step.time || `${timeStr} ( ${e.step.event} ${offsetStr}m )`;
        const cls = e.is_current ? 'upcoming-event current-step' : 'upcoming-event';
        const right = e.is_current ? 'current' : formatDuration( e.seconds_until );
        const swatch = hsvToRgbCss( e.step.hue, e.step.saturation, e.step.brightness );
        return `<div class="${cls}">
                            <span class="event-left">
                                <span class="event-swatch" style="background:${swatch}"></span>
                                ${label} → ${e.step.brightness}%
                            </span>
                            <span>${right}</span>
                        </div>`;
      } ).join( '' );
    }
  } catch (error) {
    console.error( 'Failed to load status:', error );
  }
}

function pad2 (n) { return n.toString().padStart( 2, '0' ); }

function formatDuration (totalSeconds) {
  const s = Math.max( 0, Math.floor( totalSeconds ) );
  const days = Math.floor( s / 86400 );
  const hours = Math.floor( (s % 86400) / 3600 );
  const minutes = Math.floor( (s % 3600) / 60 );
  if (s < 60) return `${s} sec`;
  const parts = [];
  if (days) parts.push( `${days} day${days === 1 ? '' : 's'}` );
  if (hours) parts.push( `${hours} hour${hours === 1 ? '' : 's'}` );
  if (minutes) parts.push( `${minutes} min` );
  return parts.join( ', ' );
}

function formatHMS (date, useUtc) {
  const h = useUtc ? date.getUTCHours() : date.getHours();
  const m = useUtc ? date.getUTCMinutes() : date.getMinutes();
  const s = useUtc ? date.getUTCSeconds() : date.getSeconds();
  return `${pad2( h )}:${pad2( m )}:${pad2( s )}`;
}

function tickClocks () {
  // Browser
  document.getElementById( 'currentTimeBrowser' ).textContent = formatHMS( new Date(), false );

  // Device clocks (extrapolated from last status report + elapsed wall clock)
  if (deviceUtcEpoch != null) {
    const elapsed = Math.floor( (Date.now() - deviceUtcEpochAt) / 1000 );
    const utcNow = new Date( (deviceUtcEpoch + elapsed) * 1000 );
    const localNow = new Date( (deviceUtcEpoch + elapsed + deviceTzOffset) * 1000 );
    const utcEl = document.getElementById( 'currentTimeUtc' );
    const localEl = document.getElementById( 'currentTimeLocal' );
    const suffix = utcEl.dataset.suffix || '';
    utcEl.textContent = formatHMS( utcNow, true ) + suffix;
    // Show in UTC so browser-local rendering can't double-convert; this is the
    // "what wall-clock time the Pico thinks it is, after applying its cached offset".
    localEl.textContent = formatHMS( localNow, true );
  }
}

function markDirty () {
  if (!dirty) {
    dirty = true;
    updateSaveBar();
  }
}

function updateSaveBar () {
  document.getElementById( 'saveBar' ).style.display = dirty ? 'block' : 'none';
}

function updateUI() {
  if (config.manual) {
    document.getElementById( 'manualHue' ).value = config.manual.hue ?? 180;
    document.getElementById( 'manualSat' ).value = config.manual.saturation ?? 100;
    document.getElementById( 'manualBright' ).value = config.manual.brightness ?? 50;
    updateManualColorDisplay();
  }

  renderSchedule();
}

function updateManualColor() {
  updateManualColorDisplay();
}

function updateManualColorDisplay() {
  const h = document.getElementById( 'manualHue' ).value;
  const s = document.getElementById( 'manualSat' ).value;
  const v = document.getElementById( 'manualBright' ).value;

  document.getElementById( 'manualHueValue' ).textContent = h;
  document.getElementById( 'manualSatValue' ).textContent = s;
  document.getElementById( 'manualBrightValue' ).textContent = v;
  document.getElementById( 'manualColorPreview' ).style.background = hsvToRgbCss( h, s, v );
}

async function saveManualColor() {
  const h = parseInt( document.getElementById( 'manualHue' ).value );
  const s = parseInt( document.getElementById( 'manualSat' ).value );
  const v = parseInt( document.getElementById( 'manualBright' ).value );

  try {
    await fetch( 'api/manual', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify( {hue: h, saturation: s, brightness: v} )
    } );
    showMessage( 'Manual color saved', 'success' );

    if (!config.manual) config.manual = {};
    config.manual.hue = h;
    config.manual.saturation = s;
    config.manual.brightness = v;
    originalConfigJson = JSON.stringify( config );
  } catch (error) {
    showMessage( 'Failed to save manual color', 'error' );
  }
}

function hsvToRgbCss(h, s, v) {
  s = s / 100;
  v = v / 100;
  const c = v * s;
  const x = c * (1 - Math.abs( ((h / 60) % 2) - 1 ));
  const m = v - c;
  let r, g, b;

  if (h < 60) { r = c; g = x; b = 0; }
  else if (h < 120) { r = x; g = c; b = 0; }
  else if (h < 180) { r = 0; g = c; b = x; }
  else if (h < 240) { r = 0; g = x; b = c; }
  else if (h < 300) { r = x; g = 0; b = c; }
  else { r = c; g = 0; b = x; }

  return `rgb(${Math.round( (r + m) * 255 )}, ${Math.round( (g + m) * 255 )}, ${Math.round( (b + m) * 255 )})`;
}

function renderSchedule() {
  const container = document.getElementById( 'scheduleList' );
  if (!config.schedule || config.schedule.length === 0) {
    container.innerHTML = '<p>No schedule steps defined.</p>';
    return;
  }

  const sorted = config.schedule.map( (s, i) => ({step: s, index: i}) );
  container.innerHTML = sorted.map( ({step, index}) => {
    const timeType = step.time ? 'exact' : 'sun';
    const checked = {exact: '', sun: ''};
    checked[timeType] = 'checked';

    return `<div class="schedule-step-new">
                    <div class="time-selector">
                        <label><input type="radio" name="time_${index}" value="exact" ${checked.exact} onchange="toggleTimeType(${index}, 'exact')"> Exact Time</label>
                        <input type="time" id="time_${index}" value="${step.time || '18:00'}" ${timeType === 'exact' ? '' : 'disabled'} onchange="updateStepTime(${index}, this.value)">

                        <label><input type="radio" name="time_${index}" value="sun" ${checked.sun} onchange="toggleTimeType(${index}, 'sun')"> Sun-based</label>
                        <select id="event_${index}" ${timeType === 'sun' ? '' : 'disabled'} onchange="updateStep(${index}, 'event', this.value)">
                            <option value="sunrise" ${step.event === 'sunrise' ? 'selected' : ''}>Sunrise</option>
                            <option value="sunset" ${step.event === 'sunset' ? 'selected' : ''}>Sunset</option>
                        </select>
                        <input type="number" id="offset_${index}" value="${step.offset || 0}" ${timeType === 'sun' ? '' : 'disabled'}
                               onchange="updateStep(${index}, 'offset', parseInt(this.value))" placeholder="Offset (min)" style="width: 80px;">
                    </div>
                    <div class="calculated-time" id="calc_${index}"></div>
                    <div style="display: flex; gap: 10px; align-items: center; margin-top: 10px; flex-wrap: wrap;">
                        <div class="color-preview" style="background: ${hsvToRgbCss( step.hue, step.saturation, step.brightness )}"
                             onclick="openColorPicker(${index}, ${step.hue}, ${step.saturation}, ${step.brightness})"></div>
                        <div style="flex: 1; min-width: 180px;">
                            Brightness: ${step.brightness}% | Hue: ${step.hue}° | Sat: ${step.saturation}%
                        </div>
                        <button onclick="previewStep(${index})" class="btn btn-small">Preview</button>
                        <button onclick="removeStep(${index})" class="btn-delete">×</button>
                    </div>
                </div>`;
  } ).join( '' );
}

function toggleTimeType(index, type) {
  const step = config.schedule[index];
  if (type === 'exact') {
    step.time = document.getElementById( `time_${index}` ).value;
    delete step.event;
    delete step.offset;
  } else {
    delete step.time;
    step.event = document.getElementById( `event_${index}` ).value || 'sunset';
    step.offset = parseInt( document.getElementById( `offset_${index}` ).value ) || 0;
  }
  markDirty();
  renderSchedule();
}

function updateStepTime(index, timeValue) {
  config.schedule[index].time = timeValue;
  markDirty();
}

function openColorPicker(index, h, s, v) {
  currentEditingStep = index;
  document.getElementById( 'hueSlider' ).value = h;
  document.getElementById( 'satSlider' ).value = s;
  document.getElementById( 'brightSlider' ).value = v;
  updateColorPreview();
  document.getElementById( 'colorPickerOverlay' ).style.display = 'block';
  document.getElementById( 'colorPickerPopup' ).classList.add( 'active' );
  schedulePreviewSend();
}

function closeColorPicker() {
  document.getElementById( 'colorPickerOverlay' ).style.display = 'none';
  document.getElementById( 'colorPickerPopup' ).classList.remove( 'active' );
  if (previewInUse) {
    stopPreview();
  }
}

function updateColorPreview() {
  const h = document.getElementById( 'hueSlider' ).value;
  const s = document.getElementById( 'satSlider' ).value;
  const v = document.getElementById( 'brightSlider' ).value;
  document.getElementById( 'hueValue' ).textContent = h;
  document.getElementById( 'satValue' ).textContent = s;
  document.getElementById( 'brightValue' ).textContent = v;
  document.getElementById( 'pickerPreview' ).style.background = hsvToRgbCss( h, s, v );
  schedulePreviewSend();
}

function schedulePreviewSend () {
  if (previewDebounceTimer) clearTimeout( previewDebounceTimer );
  previewDebounceTimer = setTimeout( sendPickerPreview, 500 );
}

async function sendPickerPreview () {
  const h = parseInt( document.getElementById( 'hueSlider' ).value );
  const s = parseInt( document.getElementById( 'satSlider' ).value );
  const v = parseInt( document.getElementById( 'brightSlider' ).value );
  try {
    await fetch( 'api/preview', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify( {hue: h, saturation: s, brightness: v} )
    } );
    previewInUse = true;
  } catch (e) {
    console.error( 'preview failed', e );
  }
}

async function previewStep (index) {
  const step = config.schedule[index];
  try {
    await fetch( 'api/preview', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify( {
        hue: step.hue,
        saturation: step.saturation,
        brightness: step.brightness
      } )
    } );
    previewInUse = true;
    showMessage( `Previewing step ${index + 1}`, 'success' );
  } catch (e) {
    showMessage( 'Preview failed', 'error' );
  }
}

async function stopPreview () {
  try {
    await fetch( 'api/preview/stop', {method: 'POST'} );
  } catch (e) {
    console.error( 'stop preview failed', e );
  } finally {
    previewInUse = false;
  }
}

async function resumeSchedule () {
  await stopPreview();
  showMessage( 'Schedule resumed', 'success' );
}

function applyColor() {
  if (currentEditingStep !== null) {
    config.schedule[currentEditingStep].hue = parseInt( document.getElementById( 'hueSlider' ).value );
    config.schedule[currentEditingStep].saturation = parseInt( document.getElementById( 'satSlider' ).value );
    config.schedule[currentEditingStep].brightness = parseInt( document.getElementById( 'brightSlider' ).value );
    markDirty();
    renderSchedule();
  }
  closeColorPicker();
}

function updateStep(index, field, value) {
  config.schedule[index][field] = value;
  markDirty();
}

function addScheduleStep() {
  if (!config.schedule) config.schedule = [];
  config.schedule.push( {
    event: 'sunset',
    offset: 0,
    brightness: 50,
    hue: 180,
    saturation: 100
  } );
  markDirty();
  renderSchedule();
}

function removeStep(index) {
  config.schedule.splice( index, 1 );
  markDirty();
  renderSchedule();
}

async function saveTempModeFlag () {
  const flag = document.getElementById( 'tempModeToggle' ).checked;
  try {
    await fetch( 'api/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify( {non_auto_is_temporary: flag} )
    } );
    showMessage( flag ? 'Will resume at next event' : 'Manual mode is permanent', 'success' );
  } catch (e) {
    showMessage( 'Failed to save', 'error' );
  }
}

async function setMode(mode) {
  try {
    await fetch( 'api/mode', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify( {mode} )
    } );
    showMessage( `Mode set to ${mode.toUpperCase()}`, 'success' );
    loadStatus();
  } catch (error) {
    showMessage( 'Failed to set mode', 'error' );
  }
}

async function saveSettings () {
  if (!dirty) return;
  try {
    const configToSave = {...config};
    delete configToSave.mode;
    const response = await fetch( 'api/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify( configToSave )
    } );
    if (!response.ok) {
      const txt = await response.text();
      showMessage( `Save failed (${response.status}): ${txt}`, 'error' );
      return;
    }
    originalConfigJson = JSON.stringify( config );
    dirty = false;
    updateSaveBar();
    showMessage( 'Settings saved', 'success' );
    if (previewInUse) await stopPreview();
    loadStatus();
  } catch (error) {
    showMessage( 'Failed to save settings', 'error' );
  }
}

function discardChanges () {
  config = JSON.parse( originalConfigJson );
  dirty = false;
  updateSaveBar();
  updateUI();
  if (previewInUse) stopPreview();
  showMessage( 'Changes discarded', 'success' );
}

function showMessage(text, type) {
  const msg = document.getElementById( 'message' );
  msg.textContent = text;
  msg.className = 'message ' + type;
  msg.style.display = 'block';
  setTimeout( () => msg.style.display = 'none', 3000 );
}

window.addEventListener( 'beforeunload', (e) => {
  if (dirty) {
    e.preventDefault();
    e.returnValue = '';
  }
} );

loadConfig();
loadStatus();
statusTimer = setInterval( loadStatus, 5000 );
clockTimer = setInterval( tickClocks, 1000 );
