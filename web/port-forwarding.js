'use strict';
let pfState = null, pfRules = [], pfDirty = false, pfEditing = null, pfBusy = false;
const pfFields = ['name','protocol','source_zone','external_port','destination_zone','destination_ip','internal_port','source_ip','external_ip','enabled','reflection'];
function pfDmz() { return {enabled:el('pf-dmz-enabled').value==='true',destination_zone:el('pf-dmz-zone').value,destination_ip:el('pf-dmz-ip').value.trim()}; }
function pfFillDmz(dmz) {
  dmz=dmz || {enabled:false,destination_zone:'lan',destination_ip:''};
  el('pf-dmz-enabled').value=String(dmz.enabled);el('pf-dmz-zone').value=dmz.destination_zone;el('pf-dmz-ip').value=dmz.destination_ip;
}
function pfMessage(message) { el('pf-message').textContent = message; }
function pfRender() {
  el('pf-rules').replaceChildren();
  for (const rule of pfRules) {
    const row = document.createElement('tr');
    const values = [(rule.enabled ? 'On' : 'Off') + ' / ' + rule.name,
      rule.source_zone + ' / ' + rule.protocol.toUpperCase() + ' / ' + rule.external_port,
      rule.destination_zone + ' / ' + rule.destination_ip + ':' + rule.internal_port,
      (rule.source_ip || 'Any source') + (rule.external_ip ? ' → ' + rule.external_ip : '') + (rule.reflection ? ' / loopback' : '')];
    for (const value of values) { const cell=document.createElement('td'); cell.textContent=value; row.append(cell); }
    const actions=document.createElement('td');
    for (const [label, action] of [['Edit',()=>pfEdit(rule)], [rule.enabled ? 'Disable' : 'Enable',()=>{rule.enabled=!rule.enabled;pfChanged();}], ['Duplicate',()=>pfEdit({...rule,id:pfId(),name:rule.name.slice(0,55)+' copy'})], ['Delete',()=>{pfRules=pfRules.filter(item=>item.id!==rule.id);if(pfEditing===rule.id)pfCancel();pfChanged();}]]) {
      const button=document.createElement('button'); button.type='button'; button.className='secondary'; button.textContent=label; button.disabled=pfBusy;
      button.addEventListener('click',action); actions.append(button);
    }
    actions.className='pf-actions';row.append(actions);el('pf-rules').append(row);
  }
  if (!pfRules.length) { const row=document.createElement('tr'), cell=document.createElement('td');cell.colSpan=5;cell.textContent='No managed forwarding rules.';row.append(cell);el('pf-rules').append(row); }
  const unmanaged=pfState?.unmanaged || [];
  el('pf-unmanaged').textContent=unmanaged.length ? 'Existing rules managed in LuCI (preserved): '+unmanaged.map(r=>r.name+' ['+r.source_zone+':'+(r.external_port||'all ports')+']').join(', ') : '';
  el('pf-save').disabled=pfBusy || !pfDirty || !pfState || !el('pf-form').hidden;
  for (const id of ['pf-add','pf-export','pf-import']) el(id).disabled=pfBusy || !pfState;
  el('pf-reload').disabled=pfBusy;
  el('pf-dmz').disabled=pfBusy || !pfState;
}
function pfId() { return Array.from(crypto.getRandomValues(new Uint8Array(8)),v=>v.toString(16).padStart(2,'0')).join(''); }
function pfChanged() { pfDirty=true;pfMessage(pfRules.length+' rules. Unsaved changes — Apply all changes to activate.');pfRender(); }
function pfCancel() { pfEditing=null;el('pf-form').hidden=true;pfRender(); }
function pfEdit(rule) {
  if (!pfState || pfBusy) return;
  pfEditing=rule?.id || pfId();
  const defaults={name:'',protocol:'tcp',source_zone:'wan',external_port:'',destination_zone:'lan',destination_ip:'',internal_port:'',source_ip:'',external_ip:'',enabled:true,reflection:false};
  for (const field of pfFields) el('pf-'+field).value=String((rule || defaults)[field]);
  el('pf-preset').value='';el('pf-editor-title').textContent=rule ? 'Edit forwarding rule' : 'Add forwarding rule';
  el('pf-editor-message').textContent='Save to stage this rule, then apply the list.';el('pf-form').hidden=false;pfRender();el('pf-name').focus();
}
async function pfLoad() {
  if (!csrf || pfBusy) return;
  if ((pfDirty || !el('pf-form').hidden) && !confirm('Discard staged forwarding changes and reload?')) return;
  pfBusy=true;pfRender();pfMessage('Reading forwarding rules…');
  try {
    const state=await api('port-forwards');pfState=state;pfRules=structuredClone(state.rules);pfDirty=false;
    for (const [field,options] of [['source_zone',state.source_zones],['destination_zone',state.destination_zones],['dmz-zone',state.destination_zones]]) {
      el('pf-'+field).replaceChildren(...options.map(value=>{const option=document.createElement('option');option.value=value;option.textContent=value==='wan'?'WAN / LTE':value==='router_vpn'?'OpenVPN client':value;return option;}));
    }
    pfFillDmz(state.dmz);
    el('pf-clients').replaceChildren(...Array.from(el('clients').rows).map(row=>{const option=document.createElement('option');option.value=row.cells[1]?.textContent || '';option.label=row.cells[0]?.textContent || '';return option;}));
    pfCancel();pfMessage(pfRules.length+' managed rules loaded.');
  } catch(error) { pfMessage(error.message); }
  finally { pfBusy=false;pfRender(); }
}
el('pf-reload').addEventListener('click',pfLoad);
navigation.querySelectorAll('a[href="#port-forwarding-panel"], a[href="#pf-dmz"]').forEach(link=>link.addEventListener('click',()=>{if(!pfState)pfLoad();}));
el('pf-add').addEventListener('click',()=>{if(pfRules.length>=100){pfMessage('Maximum 100 rules.');return;}pfEdit();});
el('pf-cancel').addEventListener('click',pfCancel);
for (const id of ['pf-dmz-enabled','pf-dmz-zone','pf-dmz-ip']) el(id).addEventListener('input',pfChanged);
el('pf-preset').addEventListener('change',()=>{
  const port=el('pf-preset').value;if(!port)return;
  el('pf-external_port').value=port;el('pf-internal_port').value=port;
  el('pf-protocol').value=port==='51820'?'udp':port==='3389'?'tcp udp':'tcp';
});
el('pf-form').addEventListener('submit',event=>{
  event.preventDefault();if(pfBusy)return;
  const rule={id:pfEditing};for(const field of pfFields)rule[field]=['enabled','reflection'].includes(field)?el('pf-'+field).value==='true':el('pf-'+field).value.trim();
  const previous=pfRules.findIndex(item=>item.id===rule.id);
  if(previous<0)pfRules.push(rule);else pfRules[previous]=rule;
  pfCancel();pfChanged();
});
el('pf-save').addEventListener('click',async()=>{
  if(!pfState || pfBusy || !pfDirty || !el('pf-form').hidden)return;
  pfBusy=true;pfRender();pfMessage('Validating and applying firewall rules…');
  try {
    const result=await api('port-forwards',{revision:pfState.revision,rules:pfRules,dmz:pfDmz()});
    pfState=result.port_forwarding;pfRules=structuredClone(pfState.rules);pfFillDmz(pfState.dmz);pfDirty=false;pfMessage(result.message);
  } catch(error) {pfMessage(error.message+' Staged edits are retained.');}
  finally {pfBusy=false;pfRender();}
});
el('pf-export').addEventListener('click',()=>{
  const url=URL.createObjectURL(new Blob([JSON.stringify({version:2,rules:pfRules,dmz:pfDmz()},null,2)],{type:'application/json'}));
  const link=document.createElement('a');link.href=url;link.download='stm32-port-forwards.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
el('pf-import').addEventListener('change',async()=>{
  try {
    const file=el('pf-import').files[0];if(!file)return;
    if(file.size>60000)throw new Error('Choose a JSON file smaller than 60 KB.');
    const imported=JSON.parse(await file.text());
    const fields=['id',...pfFields].sort().join(',');
    if(![1,2].includes(imported.version) || !Array.isArray(imported.rules) || imported.rules.length>100 || imported.rules.some(r=>!r || typeof r!=='object' || Object.keys(r).sort().join(',')!==fields || pfFields.some(f=>typeof r[f]!==(['enabled','reflection'].includes(f)?'boolean':'string')) || typeof r.id!=='string'))throw new Error('Invalid forwarding export. Use a version 1 or 2 file with up to 100 rules.');
    if(imported.version===2 && (!imported.dmz || Object.keys(imported.dmz).sort().join(',')!=='destination_ip,destination_zone,enabled' || typeof imported.dmz.enabled!=='boolean' || typeof imported.dmz.destination_zone!=='string' || typeof imported.dmz.destination_ip!=='string'))throw new Error('Invalid DMZ settings in import.');
    if(!confirm('Replace the staged forwarding list'+(imported.version===2?' and DMZ settings':'')+' with this import?'))return;
    if(imported.version===2)pfFillDmz(imported.dmz);
    pfRules=imported.rules;pfCancel();pfChanged();
  }catch(error){pfMessage(error.message);}
  finally{el('pf-import').value='';}
});
new MutationObserver(()=>{
  if(el('dashboard').hidden){pfState=null;pfRules=[];pfDirty=false;pfFillDmz();pfCancel();}
}).observe(el('dashboard'),{attributes:true,attributeFilter:['hidden']});
pfRender();
