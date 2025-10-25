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
  const r = await fetch(`${API_BASE}/invoice`, { method:'POST', body: fd });
  if (!r.ok) { alert('Invoice OCR failed'); return; }
  const data = await r.json();

  let structuredObj = null;
  let structuredBlock = '';
  if (data.structured) {
    try {
      structuredObj = typeof data.structured === 'string'
        ? JSON.parse(data.structured)
        : data.structured;
      structuredBlock = `<h4>GPT Normalised</h4><pre>${escapeHtml(JSON.stringify(structuredObj, null, 2))}</pre>`;
    } catch (err) {
      structuredBlock = `<h4>GPT Normalised</h4><div class="error-message" style="color:#ff6b6b;">Failed to parse structured data: ${escapeHtml(err.message)}</div><pre>${escapeHtml(typeof data.structured === 'string' ? data.structured : JSON.stringify(data.structured))}</pre>`;
    }
  }

  const rawBlock = data.ocr_raw
    ? `<h4>Raw OCR (PaddleOCR-VL)</h4><pre>${escapeHtml(JSON.stringify(data.ocr_raw, null, 2))}</pre>`
    : '<i>No OCR response returned.</i>';

  const itemNames = new Set();
  if (structuredObj?.items) {
    structuredObj.items.forEach((item) => {
      if (item && typeof item.name === 'string' && item.name.trim()) {
        itemNames.add(item.name.trim());
      }
    });
  }
  if (Array.isArray(data.ocr_raw?.table)) {
    data.ocr_raw.table.forEach((row) => {
      if (row && typeof row.description === 'string' && row.description.trim()) {
        itemNames.add(row.description.trim());
      }
    });
  }

  invoiceItems = Array.from(itemNames);
  fillDropdown(invoiceItems);

  el('invoiceResult').innerHTML = `
    ${rawBlock}
    ${structuredBlock}
  `;
};

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