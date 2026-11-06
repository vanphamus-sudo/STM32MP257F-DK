'use strict';
let drState=null, drItems=[], drDirty=false, drBusy=false, drEditing=null;
function drMessage(message){el('dr-message').textContent=message;}
function drRender(){
  el('dr-bindings').replaceChildren();
  for(const item of drItems){
    const row=document.createElement('tr');
    for(const value of [item.hostname||'—',item.mac,item.ip]){const cell=document.createElement('td');cell.textContent=value;row.append(cell);}
    const actions=document.createElement('td');
    for(const [label,action]of [['Edit',()=>drEdit(item)],['Remove',()=>{drItems=drItems.filter(r=>r.id!==item.id);if(drEditing===item.id)drCancel();drChanged();}]]){
      const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent=label;button.disabled=drBusy;button.addEventListener('click',action);actions.append(button);
    }
    actions.className='pf-actions';row.append(actions);el('dr-bindings').append(row);
  }
  if(!drItems.length){const row=document.createElement('tr'),cell=document.createElement('td');cell.colSpan=4;cell.textContent='No MAC-to-IP bindings configured.';row.append(cell);el('dr-bindings').append(row);}
  el('dr-save').disabled=drBusy||!drState||!drDirty||!el('dr-form').hidden;
  el('dr-add').disabled=drBusy||!drState;el('dr-reload').disabled=drBusy;
  el('dr-editor').disabled=drBusy;
}
function drChanged(){drDirty=true;drMessage('Unsaved DHCP bindings. Apply bindings to activate.');drRender();}
function drCancel(){drEditing=null;el('dr-form').hidden=true;drRender();}
function drEdit(item){
  if(drBusy||!drState)return;
  if(!item&&drItems.length>=100){drMessage('Maximum 100 bindings.');return;}
  drEditing=item?.id||Array.from(crypto.getRandomValues(new Uint8Array(8)),v=>v.toString(16).padStart(2,'0')).join('');
  for(const field of ['hostname','mac','ip'])el('dr-'+field).value=item?.[field]||'';
  el('dr-client').value='';el('dr-form').hidden=false;drRender();el('dr-mac').focus();
}
async function drLoad(){
  if(!csrf||drBusy)return;
  if((drDirty||!el('dr-form').hidden)&&!confirm('Discard staged DHCP binding edits and reload?'))return;
  drBusy=true;drRender();drMessage('Reading DHCP bindings…');
  try{
    const state=await api('dhcp-reservations');drState=state;drItems=structuredClone(state.bindings);drDirty=false;
    el('dr-client').replaceChildren();const blank=document.createElement('option');blank.value='';blank.textContent='Enter a device manually';el('dr-client').append(blank);
    for(const [index,lease]of state.leases.entries()){const option=document.createElement('option');option.value=String(index);option.textContent=(lease.hostname||'Unnamed device')+' / '+lease.mac+' / '+lease.ip;el('dr-client').append(option);}
    el('dr-unmanaged').textContent=state.unmanaged.length?'Existing static leases managed in LuCI (preserved): '+state.unmanaged.map(r=>(r.hostname||'Device')+' / '+r.mac+' / '+r.ip).join('; '):'';
    el('dr-dhcp-note').hidden=state.lan_enabled;
    drCancel();drMessage(state.bindings.length+' DHCP bindings loaded.');
  }catch(error){drMessage(error.message);}
  finally{drBusy=false;drRender();}
}
el('dr-reload').addEventListener('click',drLoad);
navigation.querySelector('a[href="#dhcp-bindings"]').addEventListener('click',()=>{if(!drState)drLoad();});
el('dr-add').addEventListener('click',()=>drEdit());el('dr-cancel').addEventListener('click',drCancel);
el('dr-client').addEventListener('change',()=>{
  const value=el('dr-client').value;if(value==='')return;const item=drState.leases[Number(value)];
  for(const field of ['mac','ip','hostname'])el('dr-'+field).value=item[field];
});
el('dr-form').addEventListener('submit',event=>{
  event.preventDefault();if(drBusy)return;
  const item={id:drEditing};for(const field of ['mac','ip','hostname'])item[field]=el('dr-'+field).value.trim();
  const index=drItems.findIndex(r=>r.id===item.id);if(index<0)drItems.push(item);else drItems[index]=item;drCancel();drChanged();
});
el('dr-save').addEventListener('click',async()=>{
  if(drBusy||!drState||!drDirty||!el('dr-form').hidden)return;
  drBusy=true;drRender();drMessage('Validating bindings and restarting DHCP/DNS…');
  try{
    const result=await api('dhcp-reservations',{revision:drState.revision,bindings:drItems});
    drState=result.reservations;drItems=structuredClone(drState.bindings);drDirty=false;drMessage(result.message);
  }catch(error){drMessage(error.message+' Staged edits are retained.');}
  finally{drBusy=false;drRender();}
});
new MutationObserver(()=>{if(el('dashboard').hidden){drState=null;drItems=[];drDirty=false;drCancel();}}).observe(el('dashboard'),{attributes:true,attributeFilter:['hidden']});
drRender();
