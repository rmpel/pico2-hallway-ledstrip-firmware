// HallwayLedBar — file management page
// Standalone (no shared helpers). Talks to /api/files/* and /api/reboot.

const $ = (id) => document.getElementById(id);

// SHA-256 in pure JS — fallback for when SubtleCrypto is unavailable.
// Browsers expose crypto.subtle only in secure contexts; LAN HTTP isn't one.
// Reference: FIPS 180-4. Operates on a Uint8Array, returns hex.
const SHA256 = (function () {
  const K = new Uint32Array([
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2,
  ]);
  function rotr(x, n) { return (x >>> n) | (x << (32 - n)); }
  function digest(bytes) {
    const l = bytes.length;
    const bitLen = l * 8;
    const padded = new Uint8Array(((l + 9 + 63) >>> 6) << 6);
    padded.set(bytes);
    padded[l] = 0x80;
    const hi = Math.floor(bitLen / 0x100000000);
    const lo = bitLen >>> 0;
    const dv = new DataView(padded.buffer);
    dv.setUint32(padded.length - 8, hi, false);
    dv.setUint32(padded.length - 4, lo, false);
    const H = new Uint32Array([
      0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,
      0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19,
    ]);
    const W = new Uint32Array(64);
    for (let i = 0; i < padded.length; i += 64) {
      for (let t = 0; t < 16; t++) W[t] = dv.getUint32(i + t * 4, false);
      for (let t = 16; t < 64; t++) {
        const s0 = rotr(W[t-15], 7) ^ rotr(W[t-15], 18) ^ (W[t-15] >>> 3);
        const s1 = rotr(W[t-2], 17) ^ rotr(W[t-2], 19) ^ (W[t-2] >>> 10);
        W[t] = (W[t-16] + s0 + W[t-7] + s1) >>> 0;
      }
      let [a,b,c,d,e,f,g,h] = H;
      for (let t = 0; t < 64; t++) {
        const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
        const ch = (e & f) ^ (~e & g);
        const t1 = (h + S1 + ch + K[t] + W[t]) >>> 0;
        const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
        const mj = (a & b) ^ (a & c) ^ (b & c);
        const t2 = (S0 + mj) >>> 0;
        h = g; g = f; f = e; e = (d + t1) >>> 0;
        d = c; c = b; b = a; a = (t1 + t2) >>> 0;
      }
      H[0] = (H[0] + a) >>> 0; H[1] = (H[1] + b) >>> 0;
      H[2] = (H[2] + c) >>> 0; H[3] = (H[3] + d) >>> 0;
      H[4] = (H[4] + e) >>> 0; H[5] = (H[5] + f) >>> 0;
      H[6] = (H[6] + g) >>> 0; H[7] = (H[7] + h) >>> 0;
    }
    let hex = "";
    for (let i = 0; i < 8; i++) hex += H[i].toString(16).padStart(8, "0");
    return hex;
  }
  return { digest };
})();

async function sha256Hex(bytes) {
  if (window.crypto && window.crypto.subtle) {
    try {
      const buf = await window.crypto.subtle.digest("SHA-256", bytes);
      return Array.from(new Uint8Array(buf))
        .map(b => b.toString(16).padStart(2, "0"))
        .join("");
    } catch (_) { /* fall through */ }
  }
  return SHA256.digest(bytes);
}

function fmtBytes(n) {
  if (n < 0) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

function showMsg(text, kind) {
  const el = $("upload-msg");
  el.textContent = text;
  el.className = "message" + (kind ? " " + kind : "");
  el.style.display = text ? "" : "none";
}

async function refreshList() {
  const tbody = document.querySelector("#file-table tbody");
  tbody.innerHTML = "<tr><td colspan='4'>Loading…</td></tr>";
  let j;
  try {
    const r = await fetch("/api/files/list");
    j = await r.json();
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan='4'>Error: ${e}</td></tr>`;
    return;
  }
  if (!j.success) {
    tbody.innerHTML = `<tr><td colspan='4'>Error</td></tr>`;
    return;
  }
  tbody.innerHTML = "";
  for (const f of j.files) {
    const tr = document.createElement("tr");

    const tdPath = document.createElement("td");
    tdPath.className = "mono";
    tdPath.textContent = f.path;
    tr.appendChild(tdPath);

    const tdSize = document.createElement("td");
    tdSize.textContent = fmtBytes(f.size);
    tr.appendChild(tdSize);

    const tdSha = document.createElement("td");
    tdSha.className = "mono sha";
    const shaBtn = document.createElement("button");
    shaBtn.textContent = "SHA";
    shaBtn.className = "btn btn-small";
    shaBtn.addEventListener("click", async () => {
      shaBtn.disabled = true;
      shaBtn.textContent = "…";
      try {
        const r = await fetch("/api/files/sha?path=" + encodeURIComponent(f.path));
        const jj = await r.json();
        tdSha.textContent = jj.success ? jj.sha256 : (jj.error || "error");
      } catch (e) {
        tdSha.textContent = String(e);
      }
    });
    tdSha.appendChild(shaBtn);
    tr.appendChild(tdSha);

    const tdAct = document.createElement("td");
    const dl = document.createElement("a");
    dl.textContent = "Download";
    dl.className = "btn btn-small";
    dl.href = "/api/files/download?path=" + encodeURIComponent(f.path);
    dl.setAttribute("download", f.path.split("/").pop());
    tdAct.appendChild(dl);
    tdAct.appendChild(document.createTextNode(" "));

    const del = document.createElement("button");
    del.textContent = "Delete";
    del.className = "btn btn-small btn-danger";
    del.addEventListener("click", async () => {
      if (!confirm(`Delete ${f.path}?`)) return;
      const r = await fetch("/api/files/delete?path=" + encodeURIComponent(f.path), {
        method: "POST",
      });
      const jj = await r.json();
      if (jj.success) refreshList();
      else alert("Delete failed: " + (jj.error || ""));
    });
    tdAct.appendChild(del);
    tr.appendChild(tdAct);

    tbody.appendChild(tr);
  }
}

async function doUpload() {
  const fileEl = $("local-file");
  const pathEl = $("target-path");
  const prog = $("upload-progress");
  const file = fileEl.files && fileEl.files[0];
  let target = (pathEl.value || "").trim();
  if (!file) { showMsg("Pick a file first.", "error"); return; }
  if (!target) { showMsg("Enter a target path.", "error"); return; }
  if (target.startsWith("/")) target = target.slice(1);

  showMsg("Hashing…", "info");
  prog.style.display = "";
  prog.value = 0;

  const buf = await file.arrayBuffer();
  const bytes = new Uint8Array(buf);
  const sha = await sha256Hex(bytes);
  showMsg(`SHA-256: ${sha.slice(0, 16)}… — uploading ${bytes.length} bytes`, "info");

  const url = "/api/files/upload?path=" + encodeURIComponent(target)
    + "&sha256=" + sha + "&size=" + bytes.length;

  await new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) prog.value = (e.loaded / e.total) * 100;
    };
    xhr.onload = () => {
      prog.style.display = "none";
      try {
        const j = JSON.parse(xhr.responseText);
        if (xhr.status === 200 && j.success) {
          showMsg(`Uploaded ${j.path} (${j.size} bytes).`, "success");
          refreshList();
        } else {
          showMsg("Upload failed: " + (j.error || xhr.status), "error");
        }
      } catch (_) {
        showMsg("Upload failed: " + xhr.status, "error");
      }
      resolve();
    };
    xhr.onerror = () => {
      prog.style.display = "none";
      showMsg("Network error", "error");
      resolve();
    };
    xhr.send(bytes);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  $("upload-btn").addEventListener("click", () => { doUpload(); });
  $("reboot-btn").addEventListener("click", async () => {
    if (!confirm("Reboot the device now?")) return;
    try { await fetch("/api/reboot", { method: "POST" }); } catch (_) {}
    showMsg("Rebooting… reconnect in a few seconds.", "info");
  });
  refreshList();
});
