'use strict';
let routerFeatureState = null, routerFeatureBusy = false;
const routerFeatureForms = new Map();
// [label, input type, optional help]; list fields use comma-separated values.
const routerFeatureSections = {
  passthrough: ['IP passthrough', 'Give the LTE IPv4 address to one downstream router Ethernet WAN port. Set that router to DHCP. This hands LTE exclusively to that client: Wi-Fi clients and router VPN/telemetry cannot share it. Keep USB management at 192.168.7.1 connected. Your downstream router must provide its own firewall and support DHCP classless routes. Carrier NAT still applies.', {
    enabled:['Exclusive IPv4 passthrough','boolean'], client_mac:['Downstream Ethernet WAN MAC address','text','Example: 02:11:22:33:44:55. Disable conflicting services first, then renew the downstream DHCP lease.']}],
  watchdog: ['Connection watchdog', 'Reconnect LTE after repeated failures. Checks succeed when either target replies. Recovery attempts use increasing delays.', {
    enabled:['Watchdog','boolean'], targets:['Health-check IPv4 addresses','list'], interval:['Check interval (seconds)','number'],
    failures:['Failures before recovery','number'], cooldown:['Initial recovery delay (seconds)','number'], reset_after:['Reset modem every N recovery attempts','number']}],
  failover: ['WAN failover', 'Prefer healthy Ethernet Internet and use LTE as backup. Existing sessions may reconnect when the uplink changes. IPv4 failover only.', {
    enabled:['Automatic failover','boolean'], primary:['Primary interface','fixed'], backup:['Backup interface','fixed'], recoveries:['Successful checks before returning to Ethernet','number']}],
  allowance: ['Cellular data allowance', 'Counts cellular upload and download in decimal MB. Billing cycles reset at midnight UTC. Cutoff blocks client forwarding over LTE; router management and telemetry can still use data. Counters may differ from carrier billing.', {
    enabled:['Allowance monitoring','boolean'], limit_mb:['Monthly allowance (MB)','number'], warning_percent:['Warn at (%)','number'], billing_day:['Billing day (1–28)','number'], cutoff:['Block client LTE traffic at limit','boolean']}],
  alerts: ['Alerts and event history', 'Keep local events and optionally send acknowledged alarms through the existing MQTT client.', {
    enabled:['Notifications','boolean'], mqtt:['Send MQTT alarms','boolean'], weak_rsrp:['Weak signal threshold RSRP (dBm)','number']}],
  signal: ['LTE signal history', 'Record signal strength, quality, SINR and serving cell. History is held in memory and resets at reboot.', {
    enabled:['Record signal history','boolean'], interval:['Sample interval (seconds)','number'], samples:['Maximum saved samples','number']}],
  wireguard: ['WireGuard VPN', 'Connect to one peer. Add remote subnets under allowed networks; use 0.0.0.0/0 only when the peer provides an Internet exit. Keep USB management connected while testing routes.', {
    enabled:['WireGuard','boolean'], private_key:['Router private key','password','Leave blank to keep the saved key.'], address:['Tunnel address and prefix','text'],
    peer_key:['Peer public key','text'], endpoint:['Peer endpoint hostname / IPv4','text'], port:['Peer UDP port','number'],
    allowed_ips:['Remote networks','list'], keepalive:['Keepalive (seconds, 0 disables)','number'], access_lan:['Allow peer access to LAN devices','boolean']}],
  guest: ['Isolated guest / device VLAN', 'Add a separate tagged Ethernet network with Internet, DHCP and DNS access. LAN, Wi-Fi and management access are blocked. Requires Ethernet trunk mode and a managed switch.', {
    enabled:['Isolated network','boolean'], vlan:['VLAN ID','number'], subnet:['Gateway address and /24 prefix','text']}],
  sqm: ['Traffic priority / SQM', 'Shape traffic using CAKE. Set rates below measured LTE capacity, then tune as radio conditions change.', {
    enabled:['Smart queue management','boolean'], interface:['WAN Linux device','text'], download:['Download rate (kbit/s)','number'], upload:['Upload rate (kbit/s)','number']}],
  ipv6: ['IPv6', 'Request dual-stack LTE and an IPv6 prefix for LAN clients. Requires carrier/APN prefix delegation. Incoming connections remain filtered.', {enabled:['IPv6 routing','boolean']}],
  cellular: ['Cellular selection', 'Select roaming policy, operator and LTE bands. These changes can disconnect LTE; unconfirmed changes restore the previous settings.', {
    roaming:['Allow roaming','boolean'], operator:['Operator MCC/MNC (blank = automatic)','text'], bands:['LTE bands (any, or eutran-3, eutran-28, …)','list']}],
  sms: ['SMS', 'Read carrier messages or send a short message through the modem. Carrier charges may apply. Remote commands by SMS are disabled.', {
    enabled:['SMS access','boolean'], alert_number:['Alert telephone number (optional)','text']}],
  gnss: ['GNSS location', 'Enable location fixes if the modem reports raw GPS support. Requires a suitable antenna and sky view. Coordinates are visible only after sign-in.', {enabled:['GNSS receiver','boolean']}]
};

function routerNode(tag, text, parent) {
  const node=document.createElement(tag); if(text!==undefined) node.textContent=text; if(parent)parent.append(node); return node;
}
function routerText(id,value){const node=el(id),text=String(value??'');if(node.textContent!==text)node.textContent=text;}
function routerBuildCellularControls(form){
  form.elements.namedItem('operator').closest('label').hidden=true;
  form.elements.namedItem('bands').closest('label').hidden=true;
  const operators=routerNode('fieldset',undefined,form);operators.className='cellular-operator-controls';
  routerNode('legend','Country (MCC) and mobile network (MNC)',operators);
  function select(label,id){const wrapper=routerNode('label',label,operators),input=routerNode('select',undefined,wrapper);input.id=id;return input;}
  const country=select('Country / network area (MCC)','rf-cellular-mcc');
  const network=select('Mobile network (MNC)','rf-cellular-mnc');
  const australia=routerNode('button','Choose Australia (MCC 505)',operators);australia.type='button';australia.className='secondary';
  australia.addEventListener('click',()=>{country.value='505';networks();network.focus();});
  const bandGroup=routerNode('fieldset',undefined,form);bandGroup.className='cellular-band-controls';
  routerNode('legend','LTE bands — click or tap to select',bandGroup);
  routerNode('p','Automatic uses all supported bands. Click a band row to tick it; several bands can be selected. Click Automatic to clear restrictions. Apply and confirm after checking connectivity.',bandGroup);
  const bandList=routerNode('div',undefined,bandGroup);bandList.id='rf-cellular-band-options';
  const bandValues=()=>[...bandList.querySelectorAll('input:checked')].map(input=>input.value);
  function addBand(value,label,checked){
    const row=routerNode('label',undefined,bandList);row.className='cellular-band-row';
    const input=routerNode('input',undefined,row);input.type='checkbox';input.value=value;input.checked=checked;
    input.id='rf-cellular-band-'+value;input.setAttribute('aria-label',label);
    routerNode('span',label,row);
    const help=routerNode('small',value==='any'?'Let the modem choose from all supported bands.':'Click this row to include or remove this band. Several bands can be ticked.',row);
    help.className='field-guide';help.id='guide-field-'+input.id;input.setAttribute('aria-describedby',help.id);input.dataset.manualHelp='true';
    input.addEventListener('change',()=>{
      const automatic=bandList.querySelector('input[value="any"]');
      if(value==='any'&&input.checked)for(const other of bandList.querySelectorAll('input'))other.checked=other===input;
      else if(value!=='any'&&input.checked)automatic.checked=false;
      if(!bandValues().length)automatic.checked=true;
    });
  }
  form.readCellularBands=()=>{
    const values=bandValues();
    if(!values.length)throw Error('Select Automatic or at least one LTE band.');
    return values.join(',');
  };
  const custom=routerNode('div',undefined,form);custom.className='pair';custom.hidden=true;
  for(const [id,label,max] of [['rf-cellular-custom-mcc','Other MCC (3 digits)',3],['rf-cellular-custom-mnc','Other MNC (2 or 3 digits)',3]]){
    const wrapper=routerNode('label',label,custom),input=routerNode('input',undefined,wrapper);input.id=id;input.type='text';input.inputMode='numeric';input.maxLength=max;input.pattern=id.endsWith('mcc')?'[0-9]{3}':'[0-9]{2,3}';
  }
  routerNode('p','',form).id='rf-cellular-current';
  routerNode('p','Choose Automatic for normal operation. Named choices are a dated directory, not a coverage scan or a promise that your SIM can use that network.',form).id='rf-cellular-directory-note';
  routerNode('p','Downlink is received from the tower; uplink is sent to it. MHz labels describe band ranges. Modem status shows the current downlink channel frequency when available.',bandGroup);
  form.cellularChoices=[];
  function networks(selected=''){
    network.replaceChildren();const blank=routerNode('option',country.value?'Choose a mobile network':'Automatic network',network);blank.value='';
    const entry=form.cellularChoices.find(entry=>entry.mcc===country.value);
    for(const item of entry?.networks||[]){const option=routerNode('option',item.name+' — MNC '+item.mnc,network);option.value=item.mnc;}
    network.value=selected;network.required=!!country.value&&country.value!=='custom';network.disabled=!country.value||country.value==='custom';
    custom.hidden=country.value!=='custom';for(const input of custom.querySelectorAll('input')){input.required=!custom.hidden;input.disabled=custom.hidden;}
  }
  country.addEventListener('change',()=>networks());
  form.populateCellular=(state,populate)=>{
    const choices=state.cellular_choices;
    if(populate||!form.cellularReady){
      form.cellularChoices=choices?.countries||[];country.replaceChildren();
      const auto=routerNode('option','Automatic — use SIM / home network',country);auto.value='';
      for(const item of form.cellularChoices){const option=routerNode('option',item.name+' — MCC '+item.mcc,country);option.value=item.mcc;}
      const other=routerNode('option','Other MCC/MNC — enter supplied codes',country);other.value='custom';
      const code=form.elements.namedItem('operator').value;
      if(code&&form.cellularChoices.some(item=>item.mcc===code.slice(0,3))){country.value=code.slice(0,3);networks(code.slice(3));}
      else if(code){country.value='custom';networks();el('rf-cellular-custom-mcc').value=code.slice(0,3);el('rf-cellular-custom-mnc').value=code.slice(3);}
      else{country.value='';networks();}
      const saved=form.elements.namedItem('bands').value.split(',').map(value=>value.trim()).filter(Boolean);
      bandList.replaceChildren();
      addBand('any','Automatic — all supported bands',!saved.length||saved.includes('any'));
      for(const band of state.capabilities.band_options||[])addBand(band.value,band.label,saved.includes(band.value)&&!saved.includes('any'));
      for(const value of saved)if(value!=='any'&&![...bandList.querySelectorAll('input')].some(input=>input.value===value))addBand(value,value+' (saved; support not reported)',!saved.includes('any'));
      form.cellularReady=true;
    }
    const current=choices?.current||state.capabilities.registered_operator;
    el('rf-cellular-current').textContent=current?.code?'Current registration: '+(current.name||'Network')+' — MCC '+current.code.slice(0,3)+', MNC '+current.code.slice(3)+'. This is separate from your saved automatic/manual choice.':'Current network registration is not available.';
    el('rf-cellular-directory-note').textContent='Automatic is recommended for normal operation. '+(choices?.source?.edition?'Named directory edition: '+choices.source.edition+'. ':'')+'Names and assignments can change. A listed network may be unavailable or not permitted by your SIM.';
  };
  form.readCellularOperator=()=>{
    if(!country.value)return '';
    const mcc=country.value==='custom'?el('rf-cellular-custom-mcc').value:country.value;
    const mnc=country.value==='custom'?el('rf-cellular-custom-mnc').value:network.value;
    if(!/^[0-9]{3}$/.test(mcc)||!/^[0-9]{2,3}$/.test(mnc))throw Error('Choose a named mobile network, or enter the supplied 3-digit MCC and 2/3-digit MNC. Keep leading zeros.');
    return mcc+mnc;
  };
}
function routerBuildForms() {
  const parent=el('router-feature-forms');
  for(const [section,[title,help,fields]] of Object.entries(routerFeatureSections)) {
    const details=routerNode('details',undefined,parent);details.id='rf-feature-'+section;routerNode('summary',title,details);
    routerNode('p',help,details).className='muted';
    const form=routerNode('form',undefined,details);form.dataset.section=section;
    for(const [name,[label,type,hint]] of Object.entries(fields)) {
      const wrapper=routerNode('label',label,form);
      let input;
      if(type==='boolean') {input=routerNode('select',undefined,wrapper);for(const [value,label] of [['false','Off'],['true','On']]){const option=routerNode('option',label,input);option.value=value;}}
      else {input=routerNode('input',undefined,wrapper);input.type=['fixed','list'].includes(type)?'text':type;input.maxLength=1024;if(type==='fixed')input.readOnly=true;}
      input.name=name;input.id='rf-'+section+'-'+name;input.autocomplete=type==='password'?'new-password':'off';
      if(hint)routerNode('small',hint,wrapper);
    }
    if(section==='cellular')routerBuildCellularControls(form);
    const availability=routerNode('p','',form);availability.className='muted';availability.dataset.availability='true';
    const button=routerNode('button','Apply '+title,form);button.type='submit';
    const message=routerNode('p','',form);message.setAttribute('role','status');
    routerFeatureForms.set(section,{form,button,message,availability});
    form.addEventListener('submit',async event=>{
      event.preventDefault();if(routerFeatureBusy||!routerFeatureState)return;
      const settings={};
      if(section==='cellular'){
        try{form.elements.namedItem('operator').value=form.readCellularOperator();form.elements.namedItem('bands').value=form.readCellularBands();}
        catch(error){message.textContent=error.message;return;}
      }
      for(const [name,[,type]] of Object.entries(fields)){
        const value=form.elements.namedItem(name).value;
        settings[name]=type==='boolean'?value==='true':type==='number'?Number(value):type==='list'?value.split(',').map(x=>x.trim()).filter(Boolean):value.trim();
      }
      routerFeatureBusy=true;button.disabled=true;
      try{const result=await api('features',{section,settings,revision:routerFeatureState.revision});message.textContent=result.message;await routerLoad(false);}
      catch(error){message.textContent=error.message;}
      finally{routerFeatureBusy=false;button.disabled=false;}
    });
  }
}
function showRouterFeatures(available){
  const wasHidden=el('router-features-panel').hidden;
  el('router-features-panel').hidden=!available;
  if(available&&wasHidden&&typeof openNavigationTarget==='function')openNavigationTarget(location.hash);
  if(available&&!routerFeatureState&&!routerFeatureBusy)routerLoad(true);
}
function routerPending(pending){
  el('rf-pending').hidden=!pending;
  if(pending)el('rf-pending-text').textContent='Confirm you can still reach the router before '+new Date(pending.deadline*1000).toLocaleTimeString()+'. Otherwise the previous network settings will be restored.';
}
async function routerLoad(populate=true){
  if(!csrf)return;
  try{
    const state=await api('features');routerFeatureState=state;
    for(const [section,group] of routerFeatureForms){
      if(populate)for(const [name,[,type]] of Object.entries(routerFeatureSections[section][2])){
        const input=group.form.elements.namedItem(name),value=state.settings[section][name];
        input.value=type==='password'?'':Array.isArray(value)?value.join(', '):String(value??'');
      }
      if(section==='cellular')group.form.populateCellular(state,populate);
      group.availability.textContent=section in state.capabilities&&!state.capabilities[section]?'Unavailable: install the feature packages or connect a modem that supports this function.':section==='wireguard'&&state.settings.wireguard.private_key_saved?'A private key is saved.':'';
      if(section==='passthrough'&&state.capabilities.passthrough){
        const runtime=state.runtime?.passthrough;
        group.availability.textContent=runtime?'Status: '+runtime.state+(runtime.address?' · '+runtime.address:'')+(runtime.reason?' · '+runtime.reason:''):'Passthrough is available. LTE must be connected before activation.';
      }
    }
    routerPending(state.pending);routerRenderHistory(state);
    el('rf-runtime').textContent=JSON.stringify(state.runtime,null,2);
    el('rf-hardware').textContent=state.capabilities.hardware_note;
    el('rf-slot-form').hidden=!state.capabilities.dual_sim;
    el('rf-message').textContent='Updated '+new Date().toLocaleTimeString();
    if(el('rf-sms-panel').open&&state.settings.sms.enabled&&!routerSmsBusy)routerReadSms(true);
  }catch(error){el('rf-message').textContent=error.message;}
}
function routerRenderHistory(state){
  const rows=el('rf-events');rows.replaceChildren();
  for(const entry of [...state.events].reverse()){
    const row=routerNode('tr',undefined,rows);for(const value of [new Date(entry.time*1000).toLocaleString(),entry.kind,entry.message])routerNode('td',value,row);
  }
  const svg=el('rf-chart');svg.replaceChildren();
  const ns='http://www.w3.org/2000/svg',points=state.signal||[];
  for(const [field,color,low,high] of [['rsrp','#187a45',-140,-40],['rsrq','#9c4b00',-30,0],['sinr','#2355ab',-20,40]]){
    let path='';let previous=false;
    points.forEach((point,i)=>{const n=parseFloat(point[field]);if(!Number.isFinite(n)){previous=false;return;}const x=10+i*580/Math.max(points.length-1,1),y=150-Math.max(0,Math.min(1,(n-low)/(high-low)))*135;path+=(previous?' L':' M')+x+','+y;previous=true;});
    const line=document.createElementNS(ns,'path');line.setAttribute('d',path);line.setAttribute('fill','none');line.setAttribute('stroke',color);line.setAttribute('stroke-width','2');svg.append(line);
  }
  el('rf-chart-note').textContent=points.length?`${points.length} samples. Green RSRP −140…−40 dBm; brown RSRQ −30…0 dB; blue SINR −20…40 dB. Each line uses its stated scale.`:'Signal samples will appear here after collection starts.';
  const table=el('rf-signals');table.replaceChildren();
  for(const sample of [...points].slice(-12).reverse()){
    const row=routerNode('tr',undefined,table);for(const value of [new Date(sample.time*1000).toLocaleTimeString(),sample.rsrp,sample.rsrq,sample.sinr,sample.cell_id])routerNode('td',value??'Unavailable',row);
  }
}
function routerDownload(name,data){
  const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
  const anchor=routerNode('a');anchor.href=url;anchor.download=name;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
routerBuildForms();
if(typeof openNavigationTarget==='function')openNavigationTarget(location.hash);
el('rf-reload').addEventListener('click',()=>routerLoad(true));
for(const action of ['confirm','rollback'])el('rf-'+action).addEventListener('click',async()=>{
  if(!routerFeatureState)return;
  try{const data={action};if(action==='confirm')data.token=routerFeatureState.pending?.token;const result=await api('features/action',data);await routerLoad(true);el('rf-message').textContent=result.message;}
  catch(error){el('rf-message').textContent=error.message;}
});
el('rf-diagnostics').addEventListener('submit',async event=>{
  event.preventDefault();const button=event.submitter||event.target.querySelector('button[type=submit]');button.disabled=true;
  try{el('rf-diagnostic-result').textContent=(await api('features/diagnostics',{tool:el('rf-tool').value,target:el('rf-target').value.trim()})).output;}
  catch(error){el('rf-diagnostic-result').textContent=error.message;}finally{button.disabled=false;}
});
for(const kind of ['backup','support'])el('rf-'+kind).addEventListener('click',async()=>{
  try{routerDownload('router-'+kind+'.json',await api('features/'+kind));}catch(error){el('rf-message').textContent=error.message;}
});
el('rf-restore').addEventListener('change',async event=>{
  const file=event.target.files[0];if(!file)return;
  try{if(file.size>1048576)throw Error('Backup exceeds 1 MiB.');const result=await api('features/restore',JSON.parse(await file.text()));await routerLoad(true);el('rf-message').textContent=result.message;}
  catch(error){el('rf-message').textContent=error.message;}finally{event.target.value='';}
});
let routerSmsBusy=false,routerSmsData=null,routerSmsControlsSignature='';
function routerRenderSms(){
  if(!routerSmsData)return;
  const all=routerSmsData.messages||[],received=all.filter(message=>['received','receiving'].includes(message.state));
  const messages=el('rf-sms-view').value==='inbox'?received:all;
  const controls=el('rf-sms-delete-controls'),signature=JSON.stringify(messages);
  if(signature!==routerSmsControlsSignature||controls.children.length!==messages.length){
  const fragment=document.createDocumentFragment();
  for(const message of messages){
    const row=routerNode('div',undefined,fragment);
    routerNode('span','SMS #'+message.id+' · '+message.state+' · '+(message.number||'No number')+' ',row);
    const button=routerNode('button','Delete SMS #'+message.id,row);button.type='button';button.className='secondary';
    button.addEventListener('click',()=>routerDeleteSms(message.id));
  }
  controls.replaceChildren(fragment);routerSmsControlsSignature=signature;
  }
  const checked=routerSmsData.updated_at?new Date(routerSmsData.updated_at*1000):new Date(routerSmsData.checkedAt);
  const heading=received.length+' received, '+all.length+' readable stored messages.';
  routerText('rf-sms-status','Last checked '+checked.toLocaleTimeString()+'.');
  let notice=messages.length?'':el('rf-sms-view').value==='inbox'?'No received messages found. Choose All stored to inspect sent/draft messages.':'No SMS messages are stored on this modem.';
  if(routerSmsData.failed)notice+=' '+routerSmsData.failed+' message(s) could not be read; retry.';
  if(routerSmsData.truncated)notice+=' Showing a limited batch of '+all.length+' out of '+routerSmsData.total+' stored messages.';
  routerText('rf-sms-result',[heading,notice,...messages.map(message=>['SMS #'+message.id,'From / to: '+(message.number||'Not supplied'),'Time: '+(message.time||'Not supplied'),'State: '+message.state,message.text||'(No text content)'].join('\n'))].filter(Boolean).join('\n\n'));
}
async function routerDeleteSms(id){
  if(routerSmsBusy||!csrf||!confirm('Permanently delete SMS #'+id+' from the modem? This cannot be undone.'))return;
  const token=csrf;routerSmsBusy=true;el('rf-sms-list').disabled=true;
  for(const button of el('rf-sms-delete-controls').querySelectorAll('button'))button.disabled=true;
  let deleted=false;
  try{await api('features/sms',{action:'delete',id});deleted=true;}
  catch(error){if(token===csrf&&!el('dashboard').hidden)el('rf-sms-result').textContent='Could not delete SMS: '+error.message;}
  finally{routerSmsBusy=false;el('rf-sms-list').disabled=false;for(const button of el('rf-sms-delete-controls').querySelectorAll('button'))button.disabled=false;}
  if(deleted&&token===csrf&&!el('dashboard').hidden){routerSmsData=null;el('rf-sms-delete-controls').replaceChildren();await routerReadSms();}
}
async function routerReadSms(background=false){
  if(routerSmsBusy||!csrf)return;
  if(!routerFeatureState){el('rf-sms-result').textContent='SMS settings are still loading. Wait a moment or reload router settings, then try again.';return;}
  if(!routerFeatureState.settings.sms.enabled){el('rf-sms-result').textContent='SMS is off. Open Cellular → SMS settings, switch SMS access On and apply, then read again.';return;}
  routerSmsBusy=true;
  if(!background){el('rf-sms-list').disabled=true;routerText('rf-sms-status','Reading stored messages from the modem. Please wait…');}
  if(!routerSmsData)routerText('rf-sms-result','Reading stored messages from the modem. Please wait…');
  const token=csrf;
  try{const data=await api('features/sms',{action:'list'});if(token!==csrf||el('dashboard').hidden)return;routerSmsData={...data,checkedAt:Date.now()};routerRenderSms();}
  catch(error){if(token===csrf&&!el('dashboard').hidden){routerText('rf-sms-status','Could not read SMS: '+error.message);if(!routerSmsData)routerText('rf-sms-result','Could not read SMS: '+error.message);}}
  finally{routerSmsBusy=false;el('rf-sms-list').disabled=false;el('rf-sms-list').textContent='Read inbox';}
}
el('rf-sms-list').addEventListener('click',()=>routerReadSms());
el('rf-sms-view').addEventListener('change',routerRenderSms);
el('rf-sms-panel').addEventListener('toggle',()=>{if(el('rf-sms-panel').open)routerReadSms();});
setInterval(()=>{if(!el('dashboard').hidden&&el('rf-sms-panel').open&&routerFeatureState?.settings.sms.enabled)routerReadSms(true);},15000);
el('rf-sms-form').addEventListener('submit',async event=>{
  event.preventDefault();const button=event.submitter||event.target.querySelector('button[type=submit]');button.disabled=true;
  try{el('rf-sms-result').textContent=(await api('features/sms',{action:'send',number:el('rf-sms-number').value,text:el('rf-sms-text').value})).message;}
  catch(error){el('rf-sms-result').textContent=error.message;}finally{button.disabled=false;}
});
el('rf-slot-form').addEventListener('submit',async event=>{
  event.preventDefault();try{el('rf-message').textContent=(await api('features/action',{action:'sim-slot',slot:Number(el('rf-slot').value)})).message;}catch(error){el('rf-message').textContent=error.message;}
});
new MutationObserver(()=>{if(el('dashboard').hidden){routerFeatureState=null;routerSmsData=null;routerSmsControlsSignature='';el('rf-sms-status').textContent='';for(const group of routerFeatureForms.values())for(const input of group.form.querySelectorAll('input[type=password]'))input.value='';el('rf-sms-result').textContent='';el('rf-sms-delete-controls').replaceChildren();el('rf-runtime').textContent='';}}).observe(el('dashboard'),{attributes:true,attributeFilter:['hidden']});
