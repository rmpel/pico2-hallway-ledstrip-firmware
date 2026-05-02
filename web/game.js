// Game UI: 3 primary buttons + Back. Mixes (Y/C/M) are produced by pressing
// two primaries within MIX_WINDOW_MS of each other (option D — fire-on-press;
// the most recently launched ball is then upgraded to the mix color).

(function () {
    var MIX_WINDOW_MS = 80;

    var MIX_OF = {
        'R+G': 'Y', 'G+R': 'Y',
        'G+B': 'C', 'B+G': 'C',
        'R+B': 'M', 'B+R': 'M',
    };

    function postJSON(path, payload) {
        return fetch(path, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: payload === undefined ? '' : JSON.stringify(payload),
        }).catch(function (e) { console.warn('post failed', path, e); });
    }

    function shoot(color) {
        console.log('[game] shoot', color);
        return postJSON('/api/game/shoot', { color: color });
    }

    function upgrade(mix) {
        console.log('[game] upgrade', mix);
        return postJSON('/api/game/upgrade', { mix: mix });
    }

    function readDesiredLevel() {
        var url = new URL(window.location.href);
        var qLevel = parseInt(url.searchParams.get('level'), 10);
        if (!isNaN(qLevel) && qLevel >= 1) return qLevel;
        var input = document.getElementById('startLevel');
        if (input) {
            var v = parseInt(input.value, 10);
            if (!isNaN(v) && v >= 1) return v;
        }
        return 1;
    }

    function startGame() {
        return postJSON('/api/game/start', { level: readDesiredLevel() });
    }

    async function restartAtLevel() {
        await postJSON('/api/game/stop');
        await startGame();
    }

    async function stopAndGoHome() {
        await postJSON('/api/game/stop');
        window.location = '/';
    }

    // Per-color last-press timestamp (ms epoch). 0 = not currently held.
    var lastPress = { R: 0, G: 0, B: 0 };

    function pressPrimary(color) {
        var now = Date.now();
        // Fire the single shot immediately.
        shoot(color);
        // If another primary is currently held AND its press was within
        // MIX_WINDOW_MS of this press, upgrade to the corresponding mix.
        var bestOther = null;
        var bestAge = MIX_WINDOW_MS + 1;
        for (var other in lastPress) {
            if (other === color) continue;
            var ts = lastPress[other];
            if (ts === 0) continue;
            var age = now - ts;
            if (age >= 0 && age <= MIX_WINDOW_MS && age < bestAge) {
                bestOther = other;
                bestAge = age;
            }
        }
        if (bestOther) {
            var mix = MIX_OF[color + '+' + bestOther];
            if (mix) upgrade(mix);
        }
        lastPress[color] = now;
    }

    function releasePrimary(color) {
        lastPress[color] = 0;
    }

    // Direct mix shortcuts: fires one primary then immediately upgrades to the
    // mix color. The upgrade hits the just-launched ball.
    var MIX_DIRECT = {
        'q': { primary: 'R', mix: 'Y' },  // R + G = Y
        'w': { primary: 'G', mix: 'C' },  // G + B = C
        'e': { primary: 'R', mix: 'M' },  // R + B = M
    };

    function fireMixDirect(spec) {
        shoot(spec.primary);
        upgrade(spec.mix);
    }

    function bindPointer(el, color) {
        if (!el) return;
        // Use pointer events (covers mouse, touch, pen) and prevent default
        // to suppress touch-induced clicks/scroll/zoom.
        el.style.touchAction = 'none';
        el.style.userSelect = 'none';
        el.addEventListener('pointerdown', function (e) {
            e.preventDefault();
            // Capture so subsequent pointer events keep targeting this button
            // even if the finger drifts to an adjacent element. Without this,
            // a slight finger movement triggers pointerleave -> spurious
            // releasePrimary, breaking the mix window.
            try { el.setPointerCapture(e.pointerId); } catch (_) {}
            pressPrimary(color);
        });
        el.addEventListener('pointerup', function (e) {
            try { el.releasePointerCapture(e.pointerId); } catch (_) {}
            releasePrimary(color);
        });
        el.addEventListener('pointercancel', function () {
            releasePrimary(color);
        });
        // Don't release on pointerleave — pointerleave fires when the captured
        // pointer drifts off the element bounding box, which on touch happens
        // constantly. Rely on pointerup/cancel only.
    }

    var KEY_TO_COLOR = { a: 'R', s: 'G', d: 'B' };

    function bind() {
        bindPointer(document.getElementById('btnR'), 'R');
        bindPointer(document.getElementById('btnG'), 'G');
        bindPointer(document.getElementById('btnB'), 'B');

        var back = document.getElementById('btnBack');
        if (back) back.addEventListener('click', stopAndGoHome);
        var restart = document.getElementById('btnRestart');
        if (restart) restart.addEventListener('click', restartAtLevel);

        // Sync the level input with ?level= on first load.
        var url = new URL(window.location.href);
        var qLevel = parseInt(url.searchParams.get('level'), 10);
        var input = document.getElementById('startLevel');
        if (!isNaN(qLevel) && qLevel >= 1 && input) {
            input.value = qLevel;
        }

        // Keyboard NKRO: A/S/D primaries, two-within-window = mix; Q/W/E = direct mix.
        document.addEventListener('keydown', function (e) {
            if (e.repeat) return;
            var k = (e.key || '').toLowerCase();
            var color = KEY_TO_COLOR[k];
            if (color) { pressPrimary(color); return; }
            var direct = MIX_DIRECT[k];
            if (direct) fireMixDirect(direct);
        });
        document.addEventListener('keyup', function (e) {
            var k = (e.key || '').toLowerCase();
            var color = KEY_TO_COLOR[k];
            if (color) releasePrimary(color);
        });
        // If the page loses focus (alt-tab etc.), clear key state to avoid
        // stuck "held" timestamps.
        window.addEventListener('blur', function () {
            lastPress.R = 0; lastPress.G = 0; lastPress.B = 0;
        });

        // Stop the game cleanly if the user closes the tab / navigates away.
        window.addEventListener('pagehide', function () {
            try { navigator.sendBeacon && navigator.sendBeacon('/api/game/stop'); } catch (e) {}
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        bind();
        startGame();
    });
})();
