const API_BASE = window.location.origin;

const el = (id) => document.getElementById(id);
const stepBtns = document.querySelectorAll('.step-btn');

let invoiceItems = []; // populated from /invoice
let scans = [];        // { relpath, label, status, filename }

function goto(step) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('show'));
  document.querySelectorAll('.step-btn').forEach(b => b.classList.remove('active'));
  el(`step${step}`).classList.add('show');
  document.querySelector(`.step-btn[data-step="${step}"]`).classList.add('active');
  refreshCounts();
}
document.querySelectorAll('[data-goto]').forEach(b => b.onclick = () => goto(b.dataset.goto));

stepBtns.forEach(btn => btn.onclick = () => goto(btn.dataset.step));
goto(1);

// Dark mode toggle (kept simple; theme colors already dark)
el('darkToggle').onclick = () => document.body.classList.toggle('light');

// ---- Step 1: Upload invoice ----
el('uploadInvoice').onclick = async () => {
  const f = el('invoiceFile').files[0];
  if (!f) return alert('Choose an invoice image first.');
  const fd = new FormData();
  fd.append('file', f);
  const r = await fetch(`${API_BASE}/invoice`, { method:'POST', body: fd });
  if (!r.ok) { alert('Invoice OCR failed'); return; }
  const data = await r.json();
  invoiceItems = data.items_for_dropdown || [];
  // fill dropdown for the scan step
  fillDropdown(invoiceItems);
  el('invoiceResult').innerHTML = `
    <b>Extracted ${data.ocr_lines.length} lines.</b><br>
    Sample:<pre>${(data.sample||[]).join('\n')}</pre>
  `;
};

function fillDropdown(items) {
  const dd = el('correctDropdown');
  dd.innerHTML = '';
  items.forEach(it => {
    const opt = document.createElement('option');
    opt.value = it; opt.textContent = it;
    dd.appendChild(opt);
  });
}

// Search-as-you-type for dropdown
el('searchItem').addEventListener('input', (e) => {
  const q = e.target.value.toLowerCase();
  const dd = el('correctDropdown');
  Array.from(dd.options).forEach(o => {
    const match = o.textContent.toLowerCase().includes(q);
    o.hidden = !match;
  });
});

// ---- Step 2: Scan items ----
let lastScan = null; // store {relpath, label, filename}

el('scanBtn').onclick = async () => {
  const f = el('scanFile').files[0];
  if (!f) return alert('Pick or capture a photo.');
  const fd = new FormData();
  // Pass fallback label from dropdown if user pre-selected one
  const ddl = el('correctDropdown');
  const fallback = ddl.value || '';
  fd.append('file', f);
  fd.append('fallback_label', fallback);
  const r = await fetch(`${API_BASE}/scan`, { method:'POST', body: fd });
  if (!r.ok) { alert('Scan failed'); return; }
  const data = await r.json();
  el('autoLabel').textContent = data.ocr_label;
  // Track the scan
  const relpath = data.saved_relpath; // e.g., "pork_loin_130g/2025...jpg"
  const [label, filename] = relpath.split('/');
  lastScan = { relpath, label, filename, cloudKey: data.cloud_key || null, status:"pending" };
  scans.push(lastScan);
  refreshProgress();
  refreshGallery();
};

el('confirmBtn').onclick = async () => {
  if (!lastScan) return;
  lastScan.status = 'confirmed';
  refreshProgress();
  refreshGallery();
};

el('correctBtn').onclick = async () => {
  if (!lastScan) return;
  const newLabel = el('correctDropdown').value || el('searchItem').value;
  if (!newLabel) return alert('Type or choose a label to correct to.');
  // hit /correct to move the file
  const fd = new FormData();
  fd.append('old_label', lastScan.label);
  fd.append('new_label', newLabel);
  fd.append('filename', lastScan.filename);
  const r = await fetch(`${API_BASE}/correct`, { method:'POST', body: fd });
  if (!r.ok) { alert('Correction failed'); return; }
  lastScan.label = cleanLabel(newLabel);
  lastScan.relpath = `${lastScan.label}/${lastScan.filename}`;
  lastScan.status = 'corrected';
  refreshProgress();
  refreshGallery();
};

function cleanLabel(t) { return (t || '').toLowerCase().replace(/[^a-z0-9]+/g,'_').replace(/^_+|_+$/g,'') || 'unknown'; }

function refreshProgress() {
  const total = scans.length;
  const confirmed = scans.filter(s => s.status === 'confirmed').length;
  const corrected = scans.filter(s => s.status === 'corrected').length;
  el('progressText').textContent = `${total} items scanned — ${confirmed} confirmed, ${corrected} corrected`;
}

function thumbUrl(relpath) {
  // We saved to /dataset/raw/<label>/<filename>; serve by static hosting path
  return `/dataset/raw/${relpath}`; // FastAPI serves /static by default; dataset is outside, so we show meta only.
}

// For security reasons we won't expose raw disk paths via static.
// Instead, show a placeholder tile + meta. (If you want inline previews, add a static mount for 'dataset' as read-only.)
function refreshGallery() {
  const g = el('gallery');
  g.innerHTML = '';
  scans.forEach(s => {
    const tile = document.createElement('div');
    tile.className = 'tile';
    const body = document.createElement('div');
    body.style = "width:100%;height:160px;background:#0c0f16;display:flex;align-items:center;justify-content:center;color:#555;";

    if (s.cloudKey) {
      const img = document.createElement('img');
      img.style = "width:100%;height:160px;object-fit:cover;display:block;";
      body.innerHTML = '';
      body.appendChild(img);
      fetch(`${API_BASE}/preview_url?key=${encodeURIComponent(s.cloudKey)}`)
        .then(r => r.json())
        .then(d => { if (d.url) img.src = d.url; })
        .catch(()=>{ body.textContent="(image saved)"; });
    } else {
      body.textContent = "(image saved)";
    }

    const meta = document.createElement('div');
    meta.className = 'meta';
    meta.innerHTML = `<span>${s.label}</span><span>${s.status}</span>`;

    tile.appendChild(body);
    tile.appendChild(meta);
    g.appendChild(tile);
  });
}


// Keyboard shortcuts
document.addEventListener('keydown', (e) => {
  if (e.key.toLowerCase() === 'c') el('confirmBtn').click();
  if (e.key.toLowerCase() === 'e') el('correctBtn').click();
  if (e.key.toLowerCase() === 'b') goto(2);
});

// ---- Step 3: Review & Finish ----
function makeCSV() {
  const header = ['filename','label','status'];
  const rows = scans.map(s => [s.filename, s.label, s.status]);
  const csv = [header, ...rows].map(r => r.join(',')).join('\n');
  return csv;
}

el('exportCSV').onclick = () => {
  const blob = new Blob([makeCSV()], { type:'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  download(url, `session_${Date.now()}.csv`);
};

el('exportJSON').onclick = () => {
  const data = { when: new Date().toISOString(), items: scans };
  const blob = new Blob([JSON.stringify(data,null,2)], { type:'application/json' });
  const url = URL.createObjectURL(blob);
  download(url, `session_${Date.now()}.json`);
};

function download(url, name) {
  const a = document.createElement('a');
  a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

el('finishBtn').onclick = async () => {
  const payload = { when: new Date().toISOString(), items: scans };
  const fd = new FormData();
  fd.append('session_json', JSON.stringify(payload));
  const r = await fetch(`${API_BASE}/summary`, { method:'POST', body: fd });
  if (r.ok) {
    alert('Session stored. You can start a new one.');
    scans = []; lastScan = null;
    refreshProgress(); refreshGallery(); goto(1);
  } else {
    alert('Failed to store session.');
  }
};

// Class counts (dataset growth)
async function refreshCounts() {
  try {
    let r = await fetch(`${API_BASE}/class_counts_cloud`);    
    if (!r.ok) r = await fetch(`${API_BASE}/class_counts`);     
    const data = await r.json();
    const total = Object.values(data.counts||{}).reduce((a,b)=>a+b,0);
    el('classCounts').textContent = `Dataset images: ${total}`;
  } catch {}
}
setInterval(refreshCounts, 8000);
refreshCounts();
