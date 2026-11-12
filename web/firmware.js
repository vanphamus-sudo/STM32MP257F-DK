'use strict';
let firmwarePopulated=false;
function showFirmware(s) {
  el('firmware-panel').hidden=!s?.available;
  if(!s?.available)return;
  {const node=el('firmware-state'),text=String(s.job.state);if(node.textContent!==text)node.textContent=text;}
  {const node=el('firmware-system-ready'),text=String(s.system?.ready?'OS/kernel updates: A/B profile ready.':'OS/kernel updates: '+(s.system?.reason||'A/B provisioning required.'));if(node.textContent!==text)node.textContent=text;}
  {const node=el('firmware-result'),text=String([s.job.version,s.job.error,s.job.rolled_back?'Previous application restored.':''].filter(Boolean).join(' · '));if(node.textContent!==text)node.textContent=text;}
  if(!firmwarePopulated){
    el('firmware-enabled').value=String(s.enabled);
    el('firmware-key').value=s.public_key;
    el('firmware-hosts').value=s.allowed_hosts.join('\n');
    firmwarePopulated=true;
  }
  el('start-firmware').disabled=!s.enabled||['queued','downloading','verifying','installing','checking','rolling-back','rebooting'].includes(s.job.state);
}
el('firmware-settings-form').addEventListener('submit',async event=>{
  event.preventDefault();el('save-firmware').disabled=true;
  try{
    const result=await api('firmware/settings',{enabled:el('firmware-enabled').value==='true',public_key:el('firmware-key').value,allowed_hosts:el('firmware-hosts').value.split(/[\s,]+/).filter(Boolean)});
    firmwarePopulated=false;showFirmware(result.firmware);el('firmware-message').textContent=result.message;
  }catch(error){el('firmware-message').textContent=error.message;}
  finally{el('save-firmware').disabled=false;}
});
el('firmware-update-form').addEventListener('submit',async event=>{
  event.preventDefault();el('start-firmware').disabled=true;
  try{
    const result=await api('firmware/update',{firmware:el('firmware-url').value.trim()});
    el('firmware-message').textContent=result.message+' The settings page will briefly reconnect during installation.';
    el('firmware-state').textContent='queued';
  }catch(error){el('firmware-message').textContent=error.message;el('start-firmware').disabled=false;}
});
new MutationObserver(()=>{if(el('dashboard').hidden)firmwarePopulated=false;}).observe(el('dashboard'),{attributes:true,attributeFilter:['hidden']});
