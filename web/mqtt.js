'use strict';
let mqttPopulated = false;
function fillMqtt(s) {
  for (const field of ['host','port','serial','username','enabled','tls_enabled','verify_hostname']) el('mqtt-'+field).value=String(s[field]);
  el('mqtt-password').value='';
  el('mqtt-ca_certificate').value='';
  el('mqtt-clear_ca').checked=false;
  el('mqtt-advanced').value=JSON.stringify(s.advanced,null,2);
  el('mqtt-password-help').textContent=s.password_saved ? 'Leave blank to keep the saved password.' : 'Enter the broker password.';
  el('mqtt-ca-help').textContent=s.ca_saved ? 'Custom CA saved. Leave blank to keep it.' : 'Leave blank to use the system certificate authorities.';
  mqttPopulated=true;
}
function showMqtt(s) {
  el('mqtt-panel').hidden=!s?.available;
  if (s?.available) {
    el('mqtt-state').textContent=s.state;
    if (!mqttPopulated) fillMqtt(s);
  }
}
el('mqtt-form').addEventListener('submit',async event=>{
  event.preventDefault(); el('save-mqtt').disabled=true;
  el('mqtt-message').textContent='Saving MQTT settings…';
  try {
    const data={};
    for (const field of ['host','serial','username','password','ca_certificate']) data[field]=el('mqtt-'+field).value;
    for (const field of ['enabled','tls_enabled','verify_hostname']) data[field]=el('mqtt-'+field).value==='true';
    data.port=Number(el('mqtt-port').value);
    data.clear_ca=el('mqtt-clear_ca').checked;
    data.advanced=JSON.parse(el('mqtt-advanced').value || '{}');
    const result=await api('mqtt',data);
    fillMqtt(result.mqtt); showMqtt(result.mqtt);
    el('mqtt-message').textContent=result.message;
  } catch(error) { el('mqtt-message').textContent=error.message; }
  finally { el('save-mqtt').disabled=false; }
});
new MutationObserver(()=>{
  if (el('dashboard').hidden) {
    mqttPopulated=false;
    el('mqtt-password').value=''; el('mqtt-ca_certificate').value='';
  }
}).observe(el('dashboard'),{attributes:true,attributeFilter:['hidden']});
