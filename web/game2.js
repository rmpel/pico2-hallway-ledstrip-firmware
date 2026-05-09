// Simon Says UI: 4 color buttons (R/G/B/Y) + status polling. Keyboard
// matches the Snake convention: A=R, S=G, D=B, Q=Y. W/E unused.

(function () {
    function postJSON(path, payload) {
        return fetch(path, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: payload === undefined ? '' : JSON.stringify(payload),
        }).catch(function (e) { console.warn('post failed', path, e); });
    }

    function input(color) {
        return postJSON('/api/game2/input', { color: color });
    }

    function startGame() {
        return postJSON('/api/game2/start');
    }

    async function restart() {
        await postJSON('/api/game2/stop');
        await startGame();
    }

    async function stopAndGoHome() {
        await postJSON('/api/game2/stop');
        window.location = '/';
    }

    var KEY_TO_COLOR = {
        a: 'R', s: 'G', d: 'B', q: 'Y',
    };

    function setText(id, value) {
        var el = document.getElementById(id);
        if (el) el.textContent = String(value);
    }

    var pollTimer = null;

    async function pollStatus() {
        try {
            var r = await fetch('/api/game2/status');
            if (!r.ok) return;
            var j = await r.json();
            setText('round', j.round || 0);
            setText('score', j.score || 0);
            setText('highscore', j.highscore || 0);
            setText('phase', j.phase || 'inactive');
        } catch (e) {
            // Silently retry next tick.
        }
    }

    function startPolling() {
        if (pollTimer) return;
        pollStatus();
        pollTimer = setInterval(pollStatus, 500);
    }

    function bind() {
        var btns = document.querySelectorAll('.shoot-btn');
        for (var i = 0; i < btns.length; i++) {
            (function (el) {
                el.addEventListener('click', function () {
                    var c = el.getAttribute('data-color');
                    if (c) input(c);
                });
            })(btns[i]);
        }

        var back = document.getElementById('btnBack');
        if (back) back.addEventListener('click', stopAndGoHome);
        var restartBtn = document.getElementById('btnRestart');
        if (restartBtn) restartBtn.addEventListener('click', restart);

        document.addEventListener('keydown', function (e) {
            if (e.repeat) return;
            var k = (e.key || '').toLowerCase();
            var color = KEY_TO_COLOR[k];
            if (color) input(color);
        });

        window.addEventListener('pagehide', function () {
            try { navigator.sendBeacon && navigator.sendBeacon('/api/game2/stop'); } catch (e) {}
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        bind();
        startGame().then(startPolling);
    });
})();
