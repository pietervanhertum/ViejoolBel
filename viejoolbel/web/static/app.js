// Progressive-enhancement helpers. The UI works as plain HTML forms; these make
// it feel snappier by submitting via fetch and reloading, with clear errors.

async function postForm(form) {
  const btn = form.querySelector('button[type=submit]');
  if (btn) btn.disabled = true;
  try {
    const resp = await fetch(form.action, { method: form.method || 'POST', body: new FormData(form) });
    if (!resp.ok) {
      const msg = await extractError(resp);
      alert('Mislukt: ' + msg);
      if (btn) btn.disabled = false;
      return false;
    }
    location.reload();
  } catch (e) {
    alert('Netwerkfout: ' + e);
    if (btn) btn.disabled = false;
  }
  return false;
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
