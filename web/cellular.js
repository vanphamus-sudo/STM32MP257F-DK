'use strict';
let cellularLoaded = false, cellularBusy = false;
function fillCellular(s) {
  el('cellular-apn').value = s.apn;
  el('cellular-username').value = s.username;
  el('cellular-password').value = '';
  el('cellular-clear-password').checked = false;
  el('cellular-auth').value = s.auth;
  el('cellular-iptype').value = s.iptype;
  el('cellular-password-help').textContent = s.password_saved ? 'A password is saved. Leave blank to keep it.' : 'No password saved. Leave blank if your provider does not require one.';
}
async function loadCellular() {
  if (!csrf || cellularLoaded || cellularBusy || el('dashboard').hidden) return;
  cellularBusy = true;
  try { fillCellular(await api('cellular')); cellularLoaded = true; }
  catch (error) { el('cellular-message').textContent = error.message; }
  finally { cellularBusy = false; }
}
el('cellular-form').addEventListener('submit', async event => {
  event.preventDefault();
  el('cellular-save').disabled = true;
  el('cellular-message').textContent = 'Saving and reconnecting cellular uplink…';
  try {
    const result = await api('cellular', {apn:el('cellular-apn').value.trim(), username:el('cellular-username').value,
      password:el('cellular-password').value, clear_password:el('cellular-clear-password').checked,
      auth:el('cellular-auth').value, iptype:el('cellular-iptype').value});
    fillCellular(result.settings); el('cellular-message').textContent = result.message; await refresh();
  } catch (error) { el('cellular-message').textContent = error.message; }
  finally { el('cellular-save').disabled = false; }
});
new MutationObserver(() => {
  if (el('dashboard').hidden) { cellularLoaded = false; el('cellular-password').value = ''; }
  else loadCellular();
}).observe(el('dashboard'), {attributes:true, attributeFilter:['hidden']});
loadCellular();
