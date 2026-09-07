// Minimal progressive-enhancement helper: submit a form via fetch and reload.
async function postForm(form) {
  try {
    const resp = await fetch(form.action, { method: form.method, body: new FormData(form) });
    if (!resp.ok) {
      const txt = await resp.text();
      alert("Mislukt: " + resp.status + " " + txt);
      return false;
    }
    location.reload();
  } catch (e) {
    alert("Netwerkfout: " + e);
  }
  return false;
}
