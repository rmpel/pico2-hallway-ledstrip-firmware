// HallwayLedBar — setup page (Location + Reboot Time)

let config = {};

async function loadConfig() {
  try {
    const r = await fetch( '/api/config' );
    config = await r.json();
    document.getElementById( 'latitude' ).value = config.location?.latitude ?? '';
    document.getElementById( 'longitude' ).value = config.location?.longitude ?? '';
    document.getElementById( 'rebootTime' ).value = config.reboot_time || '';
  } catch (e) {
    showMessage( 'Failed to load configuration', 'error' );
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
      return false;
    }
    Object.assign( config, patch );
    showMessage( okMsg, 'success' );
    return true;
  } catch (e) {
    showMessage( 'Failed to save', 'error' );
    return false;
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

function showMessage (text, type) {
  const msg = document.getElementById( 'message' );
  msg.textContent = text;
  msg.className = 'message ' + type;
  msg.style.display = 'block';
  setTimeout( () => msg.style.display = 'none', 3000 );
}

loadConfig();
