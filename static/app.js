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
  const texts = data.ocr_lines?.map(x => x.text) || data.lines || [];

  invoiceItems = data.items_for_dropdown || texts;
  // fill dropdown for the scan step
  fillDropdown(invoiceItems);

  const textList = texts.length
    ? `<ul>${texts.map(t => `<li>${t}</li>`).join('')}</ul>`
    : '<i>No text lines detected.</i>';

  const normalizedBlock = data.normalized
    ? `<h4>Normalized Text</h4><pre>${data.normalized}</pre>`
    : '';

  let structuredBlock = '';
  if (data.structured) {
    try {
      const structuredObj = typeof data.structured === 'string'
        ? JSON.parse(data.structured)
        : data.structured;
      structuredBlock = `<h4>Structured Data</h4><pre>${JSON.stringify(structuredObj, null, 2)}</pre>`;
    } catch (err) {
      structuredBlock = `<h4>Structured Data</h4><div class="error-message" style="color:#ff6b6b;">Failed to parse structured data: ${err.message}</div><pre>${typeof data.structured === 'string' ? data.structured : JSON.stringify(data.structured)}</pre>`;
    }
  }

  const legacySample = data.sample || texts.slice(0, 5);

  el('invoiceResult').innerHTML = `
    <b>Extracted ${texts.length} lines.</b><br>
    <h4>OCR Lines</h4>
    ${textList}
    ${normalizedBlock}
    ${structuredBlock}
    <details>
      <summary>Legacy sample output</summary>
      <pre>${legacySample.join('\n')}</pre>
    </details>
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