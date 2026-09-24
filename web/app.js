'use strict';
const el = id => document.getElementById(id);
let csrf = '', populated = false, refreshing = false, wifiPopulated = false;
async function api(path, data) {
  const options = {credentials: 'same-origin', headers: {}};
  if (data !== undefined) {
    options.method = 'POST'; options.headers['Content-Type'] = 'application/json';
    options.headers['X-CSRF-Token'] = csrf; options.body = JSON.stringify(data);
  }
  const response = await fetch('/api/' + path, options);
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 401 && path !== 'login') showLogin();
    throw new Error(result.error || 'Request failed.');
  }
  return result;
}
function showLogin() { csrf = ''; populated = false; wifiPopulated=false; el('dashboard').hidden = true; el('login-panel').hidden = false; for (const id of ['current-password','new-password','confirm-password','wifi-password']) el(id).value=''; }
function fillSettings(s) { el('start').value=s.start; el('end').value=s.end; el('lease').value=s.lease_hours; el('dns').value=s.dns.join(', '); }
async function refresh() {
  if (!csrf || refreshing) return;
  refreshing = true;
  try {
    const s = await api('status');
    el('status-error').hidden = true;
    if (s.wifi && s.wifi.available) {
      el('wifi-panel').hidden=false; el('wifi-state').textContent=s.wifi.state;
      el('wifi-clients').textContent=s.wifi.clients;
      if (!wifiPopulated) { fillWifi(s.wifi); wifiPopulated=true; }
    }
    el('board-name').textContent = s.hostname + ' · STM32MP257F-DK';
    el('lte-state').textContent = s.modem.state === 'connected' ? 'Connected' : s.modem.state;
    el('lte-detail').textContent = s.modem.operator || 'Mobile network';
    el('client-count').textContent = s.leases.length;
    el('wan-address').textContent = (s.addresses.wwu1u1i8 || []).join(', ') || 'No address';
    el('signal').textContent = s.modem.signal == null ? 'Unavailable' : s.modem.signal + '%';
    el('dhcp-state').textContent = s.services.dnsmasq === 'active' ? 'DHCP active' : 'DHCP ' + s.services.dnsmasq;
    el('firewall-state').textContent = s.services['router-firewall'] === 'active' ? 'Active · IPv4 NAT' : s.services['router-firewall'];
    el('uptime').textContent = Math.floor(s.uptime / 3600) + 'h ' + Math.floor(s.uptime % 3600 / 60) + 'm';
    el('clients').replaceChildren();
    for (const client of s.leases) {
      const row=document.createElement('tr');
      for (const value of [client.name === '*' ? 'Unnamed device' : client.name, client.address, client.mac]) {
        const cell=document.createElement('td'); cell.textContent=value; row.append(cell);
      }
      el('clients').append(row);
    }
    if (!s.leases.length) { const row=document.createElement('tr'), cell=document.createElement('td'); cell.colSpan=3; cell.textContent='No active DHCP leases yet.'; row.append(cell); el('clients').append(row); }
    if (!populated) { fillSettings(s.settings); populated = true; }
  } catch (error) { el('status-error').textContent = error.message; el('status-error').hidden=false; }
  finally { refreshing=false; }
}
async function showDashboard() { el('login-panel').hidden=true; el('dashboard').hidden=false; await refresh(); }
el('login-form').addEventListener('submit', async event => {
  event.preventDefault(); const button=event.submitter; button.disabled=true; el('login-message').textContent='';
  try { const result=await api('login', {username:el('username').value,password:el('password').value}); csrf=result.csrf; el('account-username').value=result.username; el('password').value=''; await showDashboard(); }
  catch(error) { el('login-message').textContent=error.message; }
  finally { button.disabled=false; }
});
el('logout').addEventListener('click', async () => { try { await api('logout', {}); showLogin(); } catch(error) { el('status-error').textContent=error.message; el('status-error').hidden=false; } });
el('settings-form').addEventListener('submit', async event => {
  event.preventDefault(); el('save').disabled=true; el('save-message').textContent='Applying settings…';
  try {
    const result=await api('settings', {start:el('start').value.trim(),end:el('end').value.trim(),lease_hours:Number(el('lease').value),dns:el('dns').value.split(',').map(s=>s.trim()).filter(Boolean)});
    fillSettings(result.settings); el('save-message').textContent=result.message; await refresh();
  } catch(error) { el('save-message').textContent=error.message; }
  finally { el('save').disabled=false; }
});
el('account-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (el('new-password').value !== el('confirm-password').value) { el('account-message').textContent='New passwords do not match.'; return; }
  el('save-account').disabled=true; el('account-message').textContent='Saving login details…';
  try {
    const result=await api('account', {username:el('account-username').value,current_password:el('current-password').value,new_password:el('new-password').value,confirm_password:el('confirm-password').value});
    showLogin(); el('username').value=result.username; el('login-message').textContent=result.message; el('password').focus();
  } catch(error) { el('account-message').textContent=error.message; }
  finally { el('save-account').disabled=false; }
});
api('session').then(s=>{csrf=s.csrf;el('account-username').value=s.username;return showDashboard();}).catch(()=>showLogin());
setInterval(refresh, 15000);
function fillWifi(s) { el('wifi-ssid').value=s.ssid; el('wifi-channel').value=s.channel; el('wifi-enabled').value=String(s.enabled); }
el('wifi-form').addEventListener('submit', async event => {
  event.preventDefault(); el('save-wifi').disabled=true; el('wifi-message').textContent='Applying Wi-Fi settings…';
  try {
    const result=await api('wifi', {enabled:el('wifi-enabled').value==='true',ssid:el('wifi-ssid').value,channel:Number(el('wifi-channel').value),password:el('wifi-password').value});
    fillWifi(result.wifi); el('wifi-password').value=''; el('wifi-message').textContent=result.message; await refresh();
  } catch(error) { el('wifi-message').textContent=error.message; }
  finally { el('save-wifi').disabled=false; }
});
