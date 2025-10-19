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

  const resultEl = el('invoiceResult');
  resultEl.innerHTML = '<i>Running OCR…</i>';

  const fd = new FormData();
  fd.append('file', f);

  try {
    const r = await fetch(`${API_BASE}/invoice`, { method:'POST', body: fd });
    if (!r.ok) {
      const message = await safeReadJsonOrText(r);
      throw new Error(message || 'Invoice OCR failed');
    }

    const data = await r.json();
    renderInvoiceResult(data);
  } catch (err) {
    showInvoiceError(err);
  }
};

function renderInvoiceResult(data) {
  const ocrLines = Array.isArray(data?.ocr_lines)
    ? data.ocr_lines.filter(Boolean)
    : [];

  const legacyLines = normaliseLegacyLines(data?.lines);
  const texts = ocrLines.length
    ? ocrLines.map(extractText).filter(Boolean)
    : legacyLines;

  invoiceItems = Array.isArray(data?.items_for_dropdown) && data.items_for_dropdown.length
    ? data.items_for_dropdown
    : texts;
  fillDropdown(invoiceItems);

  const ocrList = buildOcrList(ocrLines, texts);
  const normalizedBlock = buildNormalizedBlock(data?.normalized);
  const structuredBlock = buildStructuredBlock(data?.structured);
  const legacyBlock = buildLegacyBlock(data?.sample, texts);

  el('invoiceResult').innerHTML = `
    <b>Extracted ${texts.length} line${texts.length === 1 ? '' : 's'}.</b><br>
    <h4>OCR Lines</h4>
    ${ocrList}
    ${normalizedBlock}
    ${structuredBlock}
    ${legacyBlock}
  `;
}

function buildOcrList(ocrLines, fallbackTexts) {
  if (ocrLines.length) {
    return `<ul>${ocrLines.map((line) => {
      const text = escapeHtml(extractText(line));
      const confidence = extractConfidence(line);
      const confLabel = confidence !== null
        ? `<small class="muted"> (confidence ${(confidence * 100).toFixed(1)}%)</small>`
        : '';
      return `<li>${text}${confLabel}</li>`;
    }).join('')}</ul>`;
  }

  if (fallbackTexts.length) {
    return `<ul>${fallbackTexts.map((text) => `<li>${escapeHtml(text)}</li>`).join('')}</ul>`;
  }

  return '<i>No text lines detected.</i>';
}

function buildNormalizedBlock(normalized) {
  if (typeof normalized !== 'string' || !normalized.trim()) return '';
  return `<h4>Normalized Text</h4><pre>${escapeHtml(normalized)}</pre>`;
}

function buildStructuredBlock(structured) {
  if (!structured) return '';

  try {
    const structuredObj = typeof structured === 'string'
      ? JSON.parse(structured)
      : structured;
    const pretty = JSON.stringify(structuredObj, null, 2);
    return `<h4>Structured Data</h4><pre>${escapeHtml(pretty)}</pre>`;
  } catch (err) {
    const raw = typeof structured === 'string'
      ? structured
      : JSON.stringify(structured, null, 2);
    return `
      <h4>Structured Data</h4>
      <div class="error-message" style="color:#ff6b6b;">Failed to parse structured data: ${escapeHtml(err.message)}</div>
      <pre>${escapeHtml(raw)}</pre>
    `;
  }
}

function buildLegacyBlock(sample, texts) {
  const legacyList = Array.isArray(sample) && sample.length
    ? sample
    : texts.slice(0, 5);

  if (!legacyList.length) return '';

  return `
    <details>
      <summary>Legacy sample output</summary>
      <pre>${escapeHtml(legacyList.join('\n'))}</pre>
    </details>
  `;
}

function extractText(line) {
  if (!line) return '';
  if (typeof line === 'string') return line;
  if (typeof line.text === 'string') return line.text;
  return '';
}

function extractConfidence(line) {
  if (!line || typeof line === 'string') return null;
  if (typeof line.confidence === 'number') return clampConfidence(line.confidence);
  if (typeof line.confidence === 'string') {
    const parsed = Number.parseFloat(line.confidence);
    return Number.isFinite(parsed) ? clampConfidence(parsed) : null;
  }
  return null;
}

function clampConfidence(value) {
  if (!Number.isFinite(value)) return null;
  if (value > 1 && value <= 100) return value / 100;
  return Math.max(0, Math.min(1, value));
}

function normaliseLegacyLines(lines) {
  if (!lines) return [];
  if (Array.isArray(lines)) return lines.map(String).map((t) => t.trim()).filter(Boolean);
  if (typeof lines === 'string') {
    return lines.split(/\r?\n/).map((t) => t.trim()).filter(Boolean);
  }
  return [];
}

async function safeReadJsonOrText(response) {
  try {
    const data = await response.clone().json();
    if (data && typeof data.detail === 'string') return data.detail;
    return JSON.stringify(data);
  } catch (err) {
    try {
      return await response.text();
    } catch (err2) {
      return '';
    }
  }
}

function showInvoiceError(err) {
  console.error('Invoice OCR failed', err);
  const message = err?.message || 'Invoice OCR failed';
  el('invoiceResult').innerHTML = `
    <div class="error-message" style="color:#ff6b6b;">
      ${escapeHtml(message)}
    </div>
  `;
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

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
