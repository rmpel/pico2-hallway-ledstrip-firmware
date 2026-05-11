// Master Mind UI: 6 color buttons (R/G/B/Y/C/M), length picker (3-6),
// current guess display, history, per-length highscores. Status polled
// every 500ms while the page is open. Keyboard mirrors Snake:
// A=R, S=G, D=B, Q=Y, W=C, E=M.

(function () {
    function postJSON(path, payload) {
        return fetch(path, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: payload === undefined ? '' : JSON.stringify(payload),
        }).catch(function (e) { console.warn('post failed', path, e); });
    }

    function input(color) {
        return postJSON('/api/game3/input', { color: color });
    }

    async function startGame() {
        var lenEl = document.getElementById('codeLength');
        var len = parseInt((lenEl && lenEl.value) || '4', 10);
        if (Number.isNaN(len)) len = 4;
        if (len < 3) len = 3;
        if (len > 6) len = 6;
        return postJSON('/api/game3/start', { length: len });
    }

    async function stopGame() {
        return postJSON('/api/game3/stop');
    }

    async function stopAndGoHome() {
        await stopGame();
        window.location = '/';
    }

    var KEY_TO_COLOR = {
        a: 'R', s: 'G', d: 'B', q: 'Y', w: 'C', e: 'M',
    };

    function setText(id, value) {
        var el = document.getElementById(id);
        if (el) el.textContent = String(value);
    }

    function colorClass(c) {
        if (!c) return 'slot-empty';
        return 'slot-' + c;
    }

    function renderCurrentGuess(guess, length) {
        var host = document.getElementById('currentGuess');
        if (!host) return;
        host.innerHTML = '';
        for (var i = 0; i < length; i++) {
            var c = guess[i];
            var div = document.createElement('div');
            div.className = 'slot ' + colorClass(c);
            host.appendChild(div);
        }
    }

    function renderHistory(history, length) {
        var host = document.getElementById('history');
        if (!host) return;
        host.innerHTML = '';
        for (var r = 0; r < history.length; r++) {
            var row = history[r];
            var rowEl = document.createElement('div');
            rowEl.className = 'guess-row';
            for (var i = 0; i < length; i++) {
                var s = document.createElement('div');
                s.className = 'slot ' + colorClass(row.guess[i]);
                rowEl.appendChild(s);
            }
            var pegs = document.createElement('div');
            pegs.className = 'pegs';
            for (var k = 0; k < length; k++) {
                var p = document.createElement('div');
                if (k < row.greens) p.className = 'peg peg-green';
                else if (k < row.greens + row.reds) p.className = 'peg peg-red';
                else p.className = 'peg peg-empty';
                pegs.appendChild(p);
            }
            rowEl.appendChild(pegs);
            host.appendChild(rowEl);
        }
    }

    var pollTimer = null;

    async function pollStatus() {
        try {
            var r = await fetch('/api/game3/status');
            if (!r.ok) return;
            var j = await r.json();
            setText('phase', j.phase || 'inactive');
            setText('guessesUsed', j.guesses_used || 0);
            setText('maxGuesses', j.max_guesses || 10);
            var len = j.length || 4;
            renderCurrentGuess(j.current_guess || [], len);
            renderHistory(j.history || [], len);
            var hs = j.highscore || {};
            for (var L = 3; L <= 6; L++) {
                var v = hs[String(L)];
                setText('hs' + L, (v && v > 0) ? v : '—');
            }
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
        var startBtn = document.getElementById('btnStart');
        if (startBtn) startBtn.addEventListener('click', function () { startGame(); });
        var stopBtn = document.getElementById('btnStop');
        if (stopBtn) stopBtn.addEventListener('click', function () { stopGame(); });

        document.addEventListener('keydown', function (e) {
            if (e.repeat) return;
            // Don't fire color shortcuts while typing into the length picker.
            var t = e.target;
            if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA')) return;
            var k = (e.key || '').toLowerCase();
            var color = KEY_TO_COLOR[k];
            if (color) input(color);
        });

        window.addEventListener('pagehide', function () {
            try { navigator.sendBeacon && navigator.sendBeacon('/api/game3/stop'); } catch (e) {}
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        bind();
        startGame().then(startPolling);
    });
})();
