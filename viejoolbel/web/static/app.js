// Progressive-enhancement helpers. The UI works as plain HTML forms; these make
// it feel snappier by submitting via fetch and reloading, with clear errors.

// IMPORTANT: this MUST stay a *synchronous* function that returns false.
// Used as `onsubmit="return postForm(this)"`; an inline onsubmit only cancels the
// native form submission when the handler returns literally false. An async
// function would return a (truthy) Promise, so the browser would ALSO submit the
// form natively and navigate to the API URL. The real work runs in _submitForm().
function postForm(form) {
  _submitForm(form);
  return false;
}

// Build the request body explicitly. A plain `new FormData(form)` OMITS unchecked
// checkboxes, so the server (whose booleans default to true) would ignore a user
// un-ticking "audio" or "relais". We therefore send every checkbox as an explicit
// "true"/"false" so toggling off actually takes effect.
function buildBody(form) {
  const fd = new FormData();
  for (const el of form.elements) {
    if (!el.name || el.disabled) continue;
    if (el.type === 'checkbox') {
      fd.set(el.name, el.checked ? 'true' : 'false');
    } else if (el.type === 'radio') {
      if (el.checked) fd.set(el.name, el.value);
    } else if (el.type === 'file') {
      if (el.files.length) fd.set(el.name, el.files[0]);
    } else if (el.type !== 'submit' && el.type !== 'button') {
      fd.set(el.name, el.value);
    }
  }
  return fd;
}

async function _submitForm(form) {
  const btn = form.querySelector('button[type=submit]');
  if (btn) btn.disabled = true;
  try {
    const resp = await fetch(form.action, { method: form.method || 'POST', body: buildBody(form) });
    if (!resp.ok) {
      alert('Mislukt: ' + (await extractError(resp)));
      if (btn) btn.disabled = false;
      return;
    }
    reloadWithToast('Gelukt ✓');
  } catch (e) {
    alert('Netwerkfout: ' + e);
    if (btn) btn.disabled = false;
  }
}

// Show a brief confirmation after the page reloads, so a non-expert can see that
// their action actually took effect.
function reloadWithToast(msg) {
  try { sessionStorage.setItem('vb_toast', msg); } catch (e) { /* ignore */ }
  location.reload();
}

function showToast(msg) {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = msg;
  el.hidden = false;
  el.classList.add('show');
  setTimeout(() => { el.classList.remove('show'); }, 2200);
  setTimeout(() => { el.hidden = true; }, 2600);
}

window.addEventListener('DOMContentLoaded', () => {
  let msg = null;
  try { msg = sessionStorage.getItem('vb_toast'); sessionStorage.removeItem('vb_toast'); } catch (e) { /* ignore */ }
  if (msg) showToast(msg);
});

async function apiDelete(url, confirmMsg) {
  if (confirmMsg && !confirm(confirmMsg)) return;
  try {
    const resp = await fetch(url, { method: 'DELETE' });
    if (!resp.ok) { alert('Mislukt: ' + (await extractError(resp))); return; }
    reloadWithToast('Verwijderd ✓');
  } catch (e) { alert('Netwerkfout: ' + e); }
}

async function apiPost(url, data) {
  const body = new FormData();
  Object.entries(data || {}).forEach(([k, v]) => body.append(k, v));
  try {
    const resp = await fetch(url, { method: 'POST', body });
    if (!resp.ok) { alert('Mislukt: ' + (await extractError(resp))); return; }
    reloadWithToast('Gelukt ✓');
  } catch (e) { alert('Netwerkfout: ' + e); }
}

async function extractError(resp) {
  try {
    const data = await resp.json();
    if (typeof data.detail === 'string') return data.detail;
    if (Array.isArray(data.detail)) return data.detail.map(d => d.msg).join(', ');
    return JSON.stringify(data);
  } catch { return resp.status + ' ' + resp.statusText; }
}

// Preview a sound in the browser.
function playSound(id) {
  const audio = new Audio('/api/sounds/' + id + '/audio');
  audio.play().catch(e => alert('Kan geluid niet afspelen: ' + e));
}

// 24-hour time entry (class "time24"). We use a plain text field rather than a
// native <input type="time"> because the native picker follows the browser's
// locale and shows AM/PM in English-locale browsers — the school wants 24h
// always. While typing we keep only digits and a colon; on leaving the field we
// normalise "830"/"8:3"/"8" into a zero-padded "HH:MM" the API accepts.
function normalizeTime24(el) {
  const raw = el.value.replace(/[^0-9:]/g, '');
  if (!raw) { el.value = ''; return; }
  let h, m;
  if (raw.includes(':')) {
    const parts = raw.split(':');
    h = parts[0]; m = parts[1] || '0';
  } else if (raw.length <= 2) {
    h = raw; m = '0';
  } else {
    h = raw.slice(0, raw.length - 2); m = raw.slice(-2);
  }
  let hi = parseInt(h, 10); if (isNaN(hi)) hi = 0;
  let mi = parseInt(m, 10); if (isNaN(mi)) mi = 0;
  hi = Math.min(23, Math.max(0, hi));
  mi = Math.min(59, Math.max(0, mi));
  el.value = String(hi).padStart(2, '0') + ':' + String(mi).padStart(2, '0');
}

document.addEventListener('input', (e) => {
  const el = e.target;
  if (el && el.classList && el.classList.contains('time24')) {
    el.value = el.value.replace(/[^0-9:]/g, '');
  }
});
// blur does not bubble, so listen for focusout (which does).
document.addEventListener('focusout', (e) => {
  const el = e.target;
  if (el && el.classList && el.classList.contains('time24')) {
    normalizeTime24(el);
  }
});
