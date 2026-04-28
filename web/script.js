let config = {};
let currentEditingStep = null;

// Load initial config
async function loadConfig() {
  try {
    const response = await fetch( 'api/config' );
    config = await response.json();
    updateUI();
  } catch (error) {
    showMessage( 'Failed to load configuration', 'error' );
  }
}

// Load status
async function loadStatus() {
  try {
    const response = await fetch( 'api/status' );
    const status = await response.json();

    document.getElementById( 'currentMode' ).textContent = status.mode.toUpperCase();
    Array.from( document.querySelectorAll('.mode-control button') ).forEach( btn => {
      btn.classList.remove( 'btn-active' );
      if (btn.classList.contains( `mode-${status.mode}` )) {
        btn.classList.add( 'btn-active' );
      }
    } );

    document.getElementById( 'wifiStatus' ).textContent = status.wifi.connected ?
      `Connected (${status.wifi.ip})` : 'Disconnected';

    // Show current time and sun times
    let timeDisplay = status.current_time || '-';
    if (status.ntp) {
      if (status.ntp.synced) {
        const minsAgo = Math.floor( status.ntp.last_sync_seconds_ago / 60 );
        timeDisplay += ` (NTP: ${minsAgo}m ago)`;
      } else {
        timeDisplay += ' (NTP: not synced)';
      }
    }
    document.getElementById( 'currentTime' ).textContent = timeDisplay;

    if (status.sun_times) {
      document.getElementById( 'sunTimes' ).textContent =
        `↑${status.sun_times.sunrise} ↓${status.sun_times.sunset}`;
    } else {
      document.getElementById( 'sunTimes' ).textContent = 'Not calculated';
    }

    // Show upcoming events
    if (status.schedule_info && status.schedule_info.upcoming_events) {
      const container = document.getElementById( 'upcomingEvents' );
      container.innerHTML = status.schedule_info.upcoming_events.map( e => {
        const mins = Math.floor( e.seconds_until / 60 );
        const offsetStr = e.step.offset >= 0 ? `+${e.step.offset}` : e.step.offset;

        // calculate actual H:i time from seconds since midnight.
        const calculatedTime = e.time + thisMidnight();
        console.log(thisMidnight(), e)
        const hours = Math.floor( calculatedTime / 3600 ) % 24;
        const minutes = Math.floor( (calculatedTime % 3600) / 60 );
        const timeStr = `${hours.toString().padStart( 2, '0' )}:${minutes.toString().padStart( 2, '0' )}`;

        const timeType = e.step.time || `${timeStr} ( ${e.step.event} ${offsetStr}m )`;

        return `<div class="upcoming-event">
                            <span>${timeType} → ${e.step.brightness}%</span>
                            <span>${mins}min</span>
                        </div>`;
      } ).join( '' );
    }
  } catch (error) {
    console.error( 'Failed to load status:', error );
  }
}

function thisMidnight () {
  const now = new Date();
  now.setHours(0, 0, 0, 0);

// Difference in seconds
  return Math.floor(now / 1000);
}

// Update UI from config
function updateUI() {
  document.getElementById( 'latitude' ).value = config.location?.latitude || '';
  document.getElementById( 'longitude' ).value = config.location?.longitude || '';
  document.getElementById( 'timezone' ).value = config.location?.timezone || 'UTC';

  // Update manual color controls
  if (config.manual) {
    document.getElementById( 'manualHue' ).value = config.manual.hue ?? 180;
    document.getElementById( 'manualSat' ).value = config.manual.saturation ?? 100;
    document.getElementById( 'manualBright' ).value = config.manual.brightness ?? 50;
    updateManualColorDisplay();
  }

  renderSchedule();
}

// Update manual color preview and value displays
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

// Save manual color settings
async function saveManualColor() {
  const h = parseInt( document.getElementById( 'manualHue' ).value );
  const s = parseInt( document.getElementById( 'manualSat' ).value );
  const v = parseInt( document.getElementById( 'manualBright' ).value );

  try {
    await fetch( 'api/manual', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify( {
        hue: h,
        saturation: s,
        brightness: v
      } )
    } );
    showMessage( 'Manual color saved', 'success' );

    // Update local config
    if (!config.manual) config.manual = {};
    config.manual.hue = h;
    config.manual.saturation = s;
    config.manual.brightness = v;
  } catch (error) {
    showMessage( 'Failed to save manual color', 'error' );
  }
}

// HSV to RGB
function hsvToRgbCss(h, s, v) {
  s = s / 100;
  v = v / 100;
  const c = v * s;
  const x = c * (1 - Math.abs( ((h / 60) % 2) - 1 ));
  const m = v - c;
  let r, g, b;

  if (h < 60) {
    r = c;
    g = x;
    b = 0;
  } else if (h < 120) {
    r = x;
    g = c;
    b = 0;
  } else if (h < 180) {
    r = 0;
    g = c;
    b = x;
  } else if (h < 240) {
    r = 0;
    g = x;
    b = c;
  } else if (h < 300) {
    r = x;
    g = 0;
    b = c;
  } else {
    r = c;
    g = 0;
    b = x;
  }

  return `rgb(${Math.round( (r + m) * 255 )}, ${Math.round( (g + m) * 255 )}, ${Math.round( (b + m) * 255 )})`;
}

// Render schedule
function renderSchedule() {
  const container = document.getElementById( 'scheduleList' );
  if (!config.schedule || config.schedule.length === 0) {
    container.innerHTML = '<p>No schedule steps defined.</p>';
    return;
  }

  // Sort by calculated time
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
                    <div style="display: flex; gap: 10px; align-items: center; margin-top: 10px;">
                        <div class="color-preview" style="background: ${hsvToRgbCss( step.hue, step.saturation, step.brightness )}"
                             onclick="openColorPicker(${index}, ${step.hue}, ${step.saturation}, ${step.brightness})"></div>
                        <div style="flex: 1;">
                            Brightness: ${step.brightness}% | Hue: ${step.hue}° | Sat: ${step.saturation}%
                        </div>
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
  saveConfig();
}

function updateStepTime(index, timeValue) {
  config.schedule[index].time = timeValue;
  saveConfig();
}

function openColorPicker(index, h, s, v) {
  currentEditingStep = index;
  document.getElementById( 'hueSlider' ).value = h;
  document.getElementById( 'satSlider' ).value = s;
  document.getElementById( 'brightSlider' ).value = v;
  updateColorPreview();
  document.getElementById( 'colorPickerOverlay' ).style.display = 'block';
  document.getElementById( 'colorPickerPopup' ).classList.add( 'active' );
}

function closeColorPicker() {
  document.getElementById( 'colorPickerOverlay' ).style.display = 'none';
  document.getElementById( 'colorPickerPopup' ).classList.remove( 'active' );
}

function updateColorPreview() {
  const h = document.getElementById( 'hueSlider' ).value;
  const s = document.getElementById( 'satSlider' ).value;
  const v = document.getElementById( 'brightSlider' ).value;
  document.getElementById( 'hueValue' ).textContent = h;
  document.getElementById( 'satValue' ).textContent = s;
  document.getElementById( 'brightValue' ).textContent = v;
  document.getElementById( 'pickerPreview' ).style.background = hsvToRgbCss( h, s, v );
}

function applyColor() {
  if (currentEditingStep !== null) {
    config.schedule[currentEditingStep].hue = parseInt( document.getElementById( 'hueSlider' ).value );
    config.schedule[currentEditingStep].saturation = parseInt( document.getElementById( 'satSlider' ).value );
    config.schedule[currentEditingStep].brightness = parseInt( document.getElementById( 'brightSlider' ).value );
    saveConfig();
  }
  closeColorPicker();
}

function updateStep(index, field, value) {
  config.schedule[index][field] = value;
  saveConfig();
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
  saveConfig();
}

function removeStep(index) {
  config.schedule.splice( index, 1 );
  saveConfig();
}

async function saveLocation() {
  config.location = {
    latitude: parseFloat( document.getElementById( 'latitude' ).value ),
    longitude: parseFloat( document.getElementById( 'longitude' ).value ),
    timezone: document.getElementById( 'timezone' ).value
  };
  await saveConfig();
  showMessage( 'Location saved successfully', 'success' );
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

async function saveConfig() {
  try {
    // Don't send mode in config - it has its own endpoint
    const configToSave = {...config};
    delete configToSave.mode;

    await fetch( 'api/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify( configToSave )
    } );
    renderSchedule();
  } catch (error) {
    showMessage( 'Failed to save configuration', 'error' );
  }
}

function showMessage(text, type) {
  const msg = document.getElementById( 'message' );
  msg.textContent = text;
  msg.className = 'message ' + type;
  msg.style.display = 'block';
  setTimeout( () => msg.style.display = 'none', 3000 );
}

// Initialize
loadConfig();
loadStatus();
setInterval( loadStatus, 5000 );
