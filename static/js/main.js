// ─── Toast ────────────────────────────────────────────────────────────────────
function showToast(msg, type = 'success') {
  const toast = document.getElementById('toast');
  toast.textContent = msg;
  toast.className = `toast ${type === 'error' ? 'error' : ''}`;
  setTimeout(() => toast.classList.add('hidden'), 3000);
}

// ─── Modal ─────────────────────────────────────────────────────────────────────
function openModal(contentId) {
  const overlay = document.getElementById('modal-overlay');
  const box = document.getElementById('modal-box');
  const tpl = document.getElementById(contentId);

  if (!tpl) return;

  box.querySelector('#modal-content').innerHTML = tpl.innerHTML;
  overlay.classList.remove('hidden');

  // Re-bind form submit handlers
  const form = box.querySelector('form');
  if (form && form.getAttribute('onsubmit')) {
    // onsubmit is set inline, nothing to do
  }
}

function closeModal() {
  document.getElementById('modal-overlay').classList.add('hidden');
}

// Close modal on overlay click
document.addEventListener('click', function(e) {
  if (e.target === document.getElementById('modal-overlay')) {
    closeModal();
  }
});

// Close on Escape
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') closeModal();
});

// ─── File input trigger helper ────────────────────────────────────────────────
function triggerFileInput(inputId, callback) {
  const input = document.getElementById(inputId);
  input.value = '';
  input.onchange = callback;
  input.click();
}

// ─── Safe Markdown Rendering ─────────────────────────────────────────────────
function escapeHtml(text) {
  return String(text || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function renderMarkdown(md) {
  const lines = String(md || '').replace(/\r\n/g, '\n').split('\n');
  const out = [];
  let inUl = false;
  let inOl = false;

  function closeLists() {
    if (inUl) { out.push('</ul>'); inUl = false; }
    if (inOl) { out.push('</ol>'); inOl = false; }
  }

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      closeLists();
      continue;
    }

    const ul = /^[-*]\s+(.+)/.exec(line);
    if (ul) {
      if (!inUl) { closeLists(); out.push('<ul>'); inUl = true; }
      out.push(`<li>${formatInline(ul[1])}</li>`);
      continue;
    }

    const ol = /^(\d+)\.\s+(.+)/.exec(line);
    if (ol) {
      if (!inOl) { closeLists(); out.push('<ol>'); inOl = true; }
      out.push(`<li>${formatInline(ol[2])}</li>`);
      continue;
    }

    closeLists();
    out.push(`<p>${formatInline(line)}</p>`);
  }

  closeLists();
  return out.join('');
}

function formatInline(text) {
  let s = escapeHtml(text);
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/(^|[^\*])\*([^*]+)\*/g, '$1<em>$2</em>');
  return s;
}
