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
    location.reload();
  } catch (e) {
    alert('Netwerkfout: ' + e);
    if (btn) btn.disabled = false;
  }
}

async function apiDelete(url, confirmMsg) {
  if (confirmMsg && !confirm(confirmMsg)) return;
  try {
    const resp = await fetch(url, { method: 'DELETE' });
    if (!resp.ok) { alert('Mislukt: ' + (await extractError(resp))); return; }
    location.reload();
  } catch (e) { alert('Netwerkfout: ' + e); }
}

async function apiPost(url, data) {
  const body = new FormData();
  Object.entries(data || {}).forEach(([k, v]) => body.append(k, v));
  try {
    const resp = await fetch(url, { method: 'POST', body });
    if (!resp.ok) { alert('Mislukt: ' + (await extractError(resp))); return; }
    location.reload();
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
