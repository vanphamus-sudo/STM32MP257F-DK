'use strict';
let serialAssignmentPopulated=false;
function showSerialAssignment(s) {
  el('serial-assignment-panel').hidden=!s?.available;
  if(!s?.available)return;
  if(!serialAssignmentPopulated) {
    el('serial-assignment-mode').value=s.mode;
    el('serial-assignment-device').value=s.device;
    el('serial-assignment-baud').value=String(s.tcp_baud);
    el('serial-assignment-port').value=String(s.tcp_port);
    serialAssignmentPopulated=true;
  }
  el('serial-assignment-state').textContent=`TCP bridge: ${s.tcp_running?'running':'stopped'}. Modbus: ${s.modbus_running?'running':'stopped'}.`;
}
el('serial-assignment-form')?.addEventListener('submit',async event=>{
  event.preventDefault();el('save-serial-assignment').disabled=true;
  el('serial-assignment-message').textContent='Switching serial port...';
  try {
    const result=await api('serial-assignment',{mode:el('serial-assignment-mode').value,device:el('serial-assignment-device').value,tcp_baud:Number(el('serial-assignment-baud').value),tcp_port:Number(el('serial-assignment-port').value)});
    serialAssignmentPopulated=false;showSerialAssignment(result.serial_assignment);
    const state=await api('modbus');fillModbus(state);showModbus(state);
    el('serial-assignment-message').textContent=result.message;
  } catch(error){el('serial-assignment-message').textContent=error.message;}
  finally {el('save-serial-assignment').disabled=false;}
});
new MutationObserver(()=>{if(el('dashboard').hidden)serialAssignmentPopulated=false;}).observe(el('dashboard'),{attributes:true,attributeFilter:['hidden']});
let modbusPopulated=false;
const modbusFormats=['FLOAT32','UINT16','INT16','UINT32','INT32','BIN16','BIN32','HEX16','HEX32'];
function mbInput(label,value,type='text',options=null) {
  const wrapper=document.createElement('label'); wrapper.textContent=label;
  const input=document.createElement(options?'select':'input');
  if(options) for(const [key,name] of options) { const option=document.createElement('option'); option.value=key; option.textContent=name; input.append(option); }
  else input.type=type;
  input.value=String(value); wrapper.append(input);
  return {wrapper,input};
}
function mbButton(label,action) {
  const button=document.createElement('button'); button.type='button'; button.className='secondary'; button.textContent=label; button.addEventListener('click',action); return button;
}
function addModbusDevice(device={name:'Meter',id:1,data_mode:'big',registers:[]}) {
  const card=document.createElement('fieldset'); card.className='modbus-device';
  const legend=document.createElement('legend'); legend.textContent='Modbus device'; card.append(legend);
  const pair=document.createElement('div'); pair.className='pair';
  for(const [key,label,options] of [['name','Device name',null],['id','Device ID (decimal or 0x hex)',null],['data_mode','32-bit word order',[['big','Big-endian (ABCD)'],['little','Little-endian words (CDAB)']]]]) {
    const field=mbInput(label,device[key],'text',options); field.input.dataset.field=key; if(key==='name')field.input.maxLength=64; pair.append(field.wrapper);
  }
  card.append(pair);
  const rows=document.createElement('div'); rows.className='modbus-registers'; card.append(rows);
  function addRegister(register={description:'Voltage',address:'0x0000',format:'FLOAT32',unit:'V',function:4}) {
    const row=document.createElement('fieldset'); row.className='modbus-register';
    const group=document.createElement('div'); group.className='pair';
    for(const [key,label,options] of [['description','Description',null],['address','Register address (zero-based)',null],['format','Format',modbusFormats.map(f=>[f,f])],['unit','Unit',null],['function','Read function',[[3,'03 - Holding registers'],[4,'04 - Input registers']]]]) {
      const field=mbInput(label,register[key],'text',options); field.input.dataset.register=key;
      if(key==='description')field.input.maxLength=80;
      if(key==='unit')field.input.maxLength=24;
      group.append(field.wrapper);
    }
    row.append(group,mbButton('Remove register',()=>row.remove())); rows.append(row);
  }
  for(const register of device.registers) addRegister(register);
  const actions=document.createElement('div'); actions.className='form-footer';
  actions.append(mbButton('Add register',()=>addRegister()),mbButton('Remove device',()=>card.remove()));
  card.append(actions); el('modbus-devices').append(card);
}
function fillModbus(s) {
  for(const field of ['enabled','serial','interval_minutes','upload_time','retention_days','save_mode','usb_mount','max_storage_mb','debug']) el('modbus-'+field).value=String(s[field]);
  for(const [key,value] of Object.entries(s.serial_port)) el('modbus-port-'+key).value=String(value);
  for(const [key,value] of Object.entries(s.ftp)) el('modbus-ftp-'+key).value=key==='password'?'':String(value);
  el('modbus-password-help').textContent=s.password_saved?'Leave blank to keep the saved password.':'Enter the FTP password.';
  el('modbus-devices').replaceChildren(); for(const device of s.devices) addModbusDevice(device);
  modbusPopulated=true;
}
function showModbus(s) {
  el('modbus-panel').hidden=!s?.available;
  if(!s?.available)return;
  if(!modbusPopulated)fillModbus(s);
  if(el('modbus-state').textContent!==s.state)el('modbus-state').textContent=s.state;
  const r=s.runtime;
  const runtimeText=[s.storage_error,r?.collection_error,r?.upload_error,r?`Serial TX: ${r.tx_bytes} bytes / RX: ${r.rx_bytes} bytes; read errors: ${r.read_errors}.`:'',r?.last_collection?'Last collection: '+r.last_collection:'',r?.last_upload?'Last upload: '+r.last_upload:''].filter(Boolean).join(' ');
  if(el('modbus-runtime').textContent!==runtimeText)el('modbus-runtime').textContent=runtimeText;
  const files=el('modbus-files'),signature=JSON.stringify(s.files||[]);
  if(files.modbusSignature===signature&&files.modbusFirst===files.firstChild)return;
  const fragment=document.createDocumentFragment();
  for(const file of s.files||[]) {
    const row=document.createElement('tr');
    for(const value of [file.name,file.status,Math.ceil(file.bytes/1024)+' KiB']) {const cell=document.createElement('td');cell.textContent=value;row.append(cell);}
    const cell=document.createElement('td'),link=document.createElement('a');link.href='/api/modbus/files/'+file.id;link.textContent='Export CSV';link.download=file.name;cell.append(link);row.append(cell);fragment.append(row);
  }
  files.replaceChildren(fragment);files.modbusSignature=signature;files.modbusFirst=files.firstChild;
}
function readModbusForm() {
  const data={serial_port:{},ftp:{},devices:[]};
  for(const field of ['serial','upload_time','save_mode','usb_mount'])data[field]=el('modbus-'+field).value;
  for(const field of ['interval_minutes','retention_days','max_storage_mb'])data[field]=Number(el('modbus-'+field).value);
  for(const field of ['enabled','debug'])data[field]=el('modbus-'+field).value==='true';
  for(const field of ['device','parity'])data.serial_port[field]=el('modbus-port-'+field).value;
  for(const field of ['baud','data_bits','stop_bits','timeout_seconds'])data.serial_port[field]=Number(el('modbus-port-'+field).value);
  for(const field of ['host','username','password','directory'])data.ftp[field]=el('modbus-ftp-'+field).value;
  data.ftp.port=Number(el('modbus-ftp-port').value);data.ftp.tls=el('modbus-ftp-tls').value==='true';
  for(const card of el('modbus-devices').children) {
    const device={registers:[]};
    for(const field of card.querySelectorAll('[data-field]'))device[field.dataset.field]=field.value;
    for(const row of card.querySelectorAll('.modbus-register')) {
      const register={}; for(const field of row.querySelectorAll('[data-register]'))register[field.dataset.register]=field.dataset.register==='function'?Number(field.value):field.value;
      device.registers.push(register);
    }
    data.devices.push(device);
  }
  return data;
}
el('modbus-add-device').addEventListener('click',()=>addModbusDevice());
el('modbus-form').addEventListener('submit',async event=>{
  event.preventDefault();el('save-modbus').disabled=true;
  el('modbus-message').textContent='Saving collection settings...';
  try {const result=await api('modbus',readModbusForm());fillModbus(result.modbus);showModbus(result.modbus);serialAssignmentPopulated=false;el('modbus-message').textContent=result.message;}
  catch(error){el('modbus-message').textContent=error.message;}
  finally {el('save-modbus').disabled=false;}
});
new MutationObserver(()=>{if(el('dashboard').hidden){modbusPopulated=false;el('modbus-ftp-password').value='';}}).observe(el('dashboard'),{attributes:true,attributeFilter:['hidden']});
