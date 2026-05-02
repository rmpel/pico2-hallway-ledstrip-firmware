// Game UI: 6 color buttons (R/G/B + Y/C/M) plus Back/Restart. Each button
// fires one ball directly — no simultaneous-press / mix-window logic.
// Keyboard: A=R, S=G, D=B, Q=Y, W=C, E=M.

(function () {
    function postJSON(path, payload) {
        return fetch(path, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: payload === undefined ? '' : JSON.stringify(payload),
        }).catch(function (e) { console.warn('post failed', path, e); });
    }

    function shoot(color) {
        return postJSON('/api/game/shoot', { color: color });
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

    var KEY_TO_COLOR = {
        a: 'R', s: 'G', d: 'B',
        q: 'Y', w: 'C', e: 'M',
    };

    function bind() {
        // Wire each shoot button via plain click. Independent — no chord logic.
        var btns = document.querySelectorAll('.shoot-btn');
        for (var i = 0; i < btns.length; i++) {
            (function (el) {
                el.addEventListener('click', function () {
                    var c = el.getAttribute('data-color');
                    if (c) shoot(c);
                });
            })(btns[i]);
        }

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

        // Keyboard: each key fires one color directly.
        document.addEventListener('keydown', function (e) {
            if (e.repeat) return;
            var k = (e.key || '').toLowerCase();
            var color = KEY_TO_COLOR[k];
            if (color) shoot(color);
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
