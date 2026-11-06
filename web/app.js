'use strict';
const el = id => document.getElementById(id);
let csrf = '', populated = false, refreshing = false, wifiPopulated = false, ddnsPopulated = false, openvpnPopulated = false;
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
function showLogin() { csrf = ''; populated = false; wifiPopulated=false; ddnsPopulated=false; openvpnPopulated=false; el('dashboard').hidden = true; for (const item of document.querySelectorAll('.modem-information dd')) item.textContent = 'Not available'; el('login-panel').hidden = false; for (const id of ['current-password','new-password','confirm-password','wifi-password','ddns-password']) el(id).value=''; }
function fillSettings(s) { el('start').value=s.start; el('end').value=s.end; el('lease').value=s.lease_hours; el('dns').value=s.dns.join(', '); }
async function refresh() {
  if (!csrf || refreshing) return;
  refreshing = true;
  try {
    const s = await api('status');
    if (typeof showMqtt === 'function') showMqtt(s.mqtt);
    if (typeof showModbus === 'function') showModbus(s.modbus);
    if (typeof showSerialAssignment === 'function') showSerialAssignment(s.serial_assignment);
    if (typeof showFirmware === 'function') showFirmware(s.firmware);
    showTraffic(s.traffic);
    el('at-panel').hidden = !s.at_available;
    el('port-forwarding-panel').hidden = !s.port_forwarding_available;
    el('dhcp-bindings').hidden = !s.dhcp_reservations_available;
    if (typeof showEthernet === 'function') showEthernet(s.ethernet_available);
    el('modem-panel').hidden = !s.at_available;
    el('software-version').textContent=s.software?.string || 'Version unavailable';
    el('status-error').hidden = true;
    el('ddns-panel').hidden = !s.ddns?.available;
    if (s.ddns?.available) {
      el('ddns-state').textContent=s.ddns.state;
      if (!ddnsPopulated) { fillDdns(s.ddns); ddnsPopulated=true; }
    }
    if (s.wifi && s.wifi.available) {
      el('wifi-panel').hidden=false; el('wifi-state').textContent=s.wifi.state;
      el('wifi-clients').textContent=s.wifi.clients;
      if (!wifiPopulated) { fillWifi(s.wifi); wifiPopulated=true; }
    }
    el('openvpn-panel').hidden = !s.openvpn?.available;
    if (s.openvpn?.available) {
      showOpenvpnStatus(s.openvpn);
      if (!openvpnPopulated) { fillOpenvpn(s.openvpn); openvpnPopulated=true; }
    }
    el('board-name').textContent = s.hostname + ' · STM32MP257F-DK';
    el('lte-state').textContent = s.modem.state === 'connected' ? 'Connected' : s.modem.state;
    el('lte-detail').textContent = s.modem.operator || 'Mobile network';
    el('client-count').textContent = s.leases.length;
    el('wan-address').textContent = (s.wan_addresses || s.addresses.wwu1u1i8 || []).join(', ') || 'No address';
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
el('at-form').addEventListener('submit', async event => {
  event.preventDefault(); el('send-at').disabled=true; el('at-message').textContent='Waiting for the LTE module…';
  try {
    const result=await api('modem/at', {command:el('at-command').value.trim()});
    el('at-response').textContent=result.command+'\n'+result.response;
    el('at-message').textContent=(result.ok ? 'Response received.' : 'The modem command returned an error.')+(result.truncated ? ' Response truncated at 8192 characters.' : '');
  } catch(error) { el('at-message').textContent=error.message; el('at-response').textContent='No response received for this request.'; }
  finally { el('send-at').disabled=false; }
});
function fillDdns(s) {
  el('ddns-enabled').value=String(s.enabled); el('ddns-provider').value=s.provider;
  el('ddns-hostname').value=s.hostname; el('ddns-username').value=s.username;
  el('ddns-password').value='';
  el('ddns-secret-help').textContent=s.password_saved ? 'Leave blank to keep the saved password. Enter it again when changing providers.' : 'Enter your provider credentials.';
}
el('ddns-form').addEventListener('submit', async event => {
  event.preventDefault(); el('save-ddns').disabled=true;
  el('ddns-message').textContent='Applying DDNS settings…';
  try {
    const result=await api('ddns', {enabled:el('ddns-enabled').value==='true',provider:el('ddns-provider').value,hostname:el('ddns-hostname').value.trim(),username:el('ddns-username').value.trim(),password:el('ddns-password').value});
    fillDdns(result.ddns); el('ddns-message').textContent=result.message; await refresh();
  } catch(error) { el('ddns-message').textContent=error.message; }
  finally { el('save-ddns').disabled=false; }
});
el('wifi-form').addEventListener('submit', async event => {
  event.preventDefault(); el('save-wifi').disabled=true; el('wifi-message').textContent='Applying Wi-Fi settings…';
  try {
    const result=await api('wifi', {enabled:el('wifi-enabled').value==='true',ssid:el('wifi-ssid').value,channel:Number(el('wifi-channel').value),password:el('wifi-password').value});
    fillWifi(result.wifi); el('wifi-password').value=''; el('wifi-message').textContent=result.message; await refresh();
  } catch(error) { el('wifi-message').textContent=error.message; }
  finally { el('save-wifi').disabled=false; }
});

const vpnFields = ['enabled','remote','port','protocol','cipher','auth','keepalive','nobind','tls_mode','server_fingerprint','vpn_subnet'];
let openvpnEnabled = null, openvpnBusy = false;
function setOpenvpnBusy(busy) {
  openvpnBusy=busy;
  el('toggle-openvpn').disabled=busy || openvpnEnabled===null;
  el('save-openvpn').disabled=busy;
}
function showOpenvpnStatus(s) {
  openvpnEnabled=s.enabled;
  el('toggle-openvpn').textContent=s.enabled ? 'Disable OpenVPN' : 'Enable OpenVPN';
  el('toggle-openvpn').setAttribute('aria-pressed',String(s.enabled));
  el('toggle-openvpn').disabled=openvpnBusy;
  el('openvpn-state').textContent=s.state;
  el('openvpn-ip').textContent=s.local_ip || 'No address';
  el('openvpn-certificates').replaceChildren();
  for (const [kind, item] of Object.entries(s.certificates)) {
    const row=document.createElement('li');
    row.textContent=item.name + ': ' + (item.present ? (item.details || 'Imported') : 'Not imported');
    el('openvpn-certificates').append(row);
  }
}
function fillOpenvpn(s) {
  for (const field of vpnFields) el('openvpn-'+field).value=String(s[field]);
  showOpenvpnStatus(s);
}
el('openvpn-form').addEventListener('submit', async event => {
  event.preventDefault(); if (openvpnBusy) return; setOpenvpnBusy(true);
  el('openvpn-message').textContent='Applying OpenVPN settings…';
  const data=Object.fromEntries(vpnFields.map(field=>[field, el('openvpn-'+field).value]));
  data.enabled=data.enabled==='true'; data.nobind=data.nobind==='true'; data.port=Number(data.port);
  try {
    const result=await api('openvpn',data); fillOpenvpn(result.openvpn);
    el('openvpn-message').textContent=result.message; await refresh();
  } catch(error) { el('openvpn-message').textContent=error.message; }
  finally { setOpenvpnBusy(false); }
});
el('toggle-openvpn').addEventListener('click', async () => {
  if (openvpnBusy || openvpnEnabled===null) return;
  const enabled=!openvpnEnabled;
  setOpenvpnBusy(true);
  el('openvpn-message').textContent=enabled ? 'Enabling OpenVPN…' : 'Disabling OpenVPN…';
  try {
    const result=await api('openvpn/toggle',{enabled});
    showOpenvpnStatus(result.openvpn);
    el('openvpn-enabled').value=String(result.openvpn.enabled);
    el('openvpn-message').textContent=result.message;
    await refresh();
  } catch(error) { el('openvpn-message').textContent=error.message; }
  finally { setOpenvpnBusy(false); }
});
el('openvpn-certificate-form').addEventListener('submit', async event => {
  event.preventDefault(); el('import-openvpn').disabled=true;
  try {
    const file=el('openvpn-file').files[0];
    if (!file || file.size>16384) throw new Error('Choose a certificate or key up to 16 KB.');
    const result=await api('openvpn/certificate',{kind:el('openvpn-kind').value,content:await file.text()});
    showOpenvpnStatus(result.openvpn); el('openvpn-file').value='';
    el('openvpn-certificate-message').textContent=result.message;
  } catch(error) { el('openvpn-certificate-message').textContent=error.message; }
  finally { el('import-openvpn').disabled=false; }
});

// Match navigation links to the features available on this router.
const navigation = el('router-navigation');
function syncNavigation() {
  navigation.querySelectorAll('[data-feature]').forEach(item => {
    const hidden = el(item.dataset.feature).hidden;
    if (item.hidden !== hidden) item.hidden = hidden;
  });
}
new MutationObserver(syncNavigation).observe(el('dashboard'), {
  subtree: true, attributes: true, attributeFilter: ['hidden']
});
el('menu-toggle').addEventListener('click', () => {
  const expanded = el('menu-toggle').getAttribute('aria-expanded') !== 'true';
  el('menu-toggle').setAttribute('aria-expanded', String(expanded));
  navigation.classList.toggle('is-open', expanded);
});
navigation.addEventListener('click', event => {
  const link = event.target.closest('a');
  if (!link) return;
  navigation.querySelectorAll('a').forEach(item => item.removeAttribute('aria-current'));
  link.setAttribute('aria-current', 'location');
  navigation.classList.remove('is-open');
  el('menu-toggle').setAttribute('aria-expanded', 'false');
  const target = document.getElementById(link.hash.slice(1));
  if (target) { target.tabIndex = -1; target.focus({preventScroll: true}); }
});

let modemRefreshing = false;
async function refreshModem() {
  if (!csrf || modemRefreshing) return;
  modemRefreshing = true;
  el('refresh-modem').disabled = true;
  el('modem-message').textContent = 'Reading modem information?';
  try {
    const details = await api('modem/details');
    for (const [field, value] of Object.entries(details)) {
      const target = el('modem-' + field);
      if (target) target.textContent = value == null ? 'Not available' : String(value);
    }
    const seconds = Number(details.uptime);
    if (details.uptime != null && Number.isFinite(seconds)) {
      el('modem-uptime').textContent = Math.floor(seconds / 3600) + 'h ' + Math.floor(seconds % 3600 / 60) + 'm ' + seconds % 60 + 's';
    }
    el('modem-message').textContent = 'Updated ' + new Date().toLocaleTimeString() + '. Up Time is the active LTE connection duration.';
  } catch (error) {
    el('modem-message').textContent = 'Refresh failed: ' + error.message + ' Displayed values may be out of date.';
  } finally {
    modemRefreshing = false;
    el('refresh-modem').disabled = false;
  }
}
el('refresh-modem').addEventListener('click', refreshModem);
navigation.querySelectorAll('a[href="#modem-panel"]').forEach(link => link.addEventListener('click', refreshModem));

function showTraffic(s) {
  el('traffic-panel').hidden=!s?.available;
  if(!s?.available)return;
  el('traffic-state').textContent=s.stale_seconds>20?'Last recorded sample':'Recording';
  el('traffic-rows').replaceChildren();
  const size=value=>{const units=['B','KiB','MiB','GiB','TiB'];let n=Number(value||0),i=0;while(n>=1024&&i<4){n/=1024;i++;}return n.toFixed(i?2:0)+' '+units[i];};
  for(const [role,item] of Object.entries(s.roles)){
    const row=document.createElement('tr');
    for(const value of [role.toUpperCase()+' / '+(item.device||'unavailable'),size(item.total_tx_bytes),size(item.total_rx_bytes),size(item.tx_bytes_per_second)+'/s',size(item.rx_bytes_per_second)+'/s']){const cell=document.createElement('td');cell.textContent=value;row.append(cell);}
    el('traffic-rows').append(row);
  }
}
