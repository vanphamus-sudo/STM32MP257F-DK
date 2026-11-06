const fs=require('node:fs'),path=require('node:path'),{spawnSync}=require('node:child_process');
const target=path.resolve('local/mqtt-browser');fs.mkdirSync(target,{recursive:true});
for(const file of ['mqtt.js','style.css'])fs.copyFileSync('web/'+file,path.join(target,file));
const panel=fs.readFileSync('web/index.html','utf8').match(/<section id="mqtt-panel"[\s\S]*?<\/section>/)[0];
const fixture=`<script>
const el=id=>document.getElementById(id);let saves=0,last;
const state={available:true,enabled:false,host:'broker.test',port:8883,serial:'BOARD001',username:'user',tls_enabled:true,verify_hostname:true,password_saved:true,ca_saved:true,advanced:{tcp_proxy_targets:[]},state:'disabled'};
async function api(route,data){if(route!=='mqtt')throw Error('Wrong route');last=data;saves++;return {mqtt:{...state,...data},message:'Saved'};}
</script><script src="mqtt.js"></script><script>
window.addEventListener('load',async()=>{try{
const check=(ok,message)=>{if(!ok)throw Error(message);};showMqtt(state);
check(!el('mqtt-panel').hidden&&el('mqtt-host').value==='broker.test','Load settings');
check(el('mqtt-password').value===''&&el('mqtt-password-help').textContent.includes('keep'),'Secret handling');
el('mqtt-host').value='edited.test';showMqtt({...state,host:'refreshed.test'});
check(el('mqtt-host').value==='edited.test','Refresh preserves edits');
el('mqtt-enabled').value='true';el('mqtt-password').value='new secret';el('mqtt-form').requestSubmit();await new Promise(r=>setTimeout(r,20));
check(saves===1&&last.enabled===true&&last.port===8883&&last.password==='new secret','Save');
check(el('mqtt-password').value===''&&!el('save-mqtt').disabled,'Clear secret after save');
el('mqtt-advanced').value='bad json';el('mqtt-form').requestSubmit();await new Promise(r=>setTimeout(r,20));
check(saves===1&&!el('save-mqtt').disabled&&el('mqtt-message').textContent!=='Saved','Invalid JSON');
check(document.documentElement.scrollWidth<=innerWidth,'Layout overflow');
el('mqtt-password').value='secret';el('dashboard').hidden=true;await new Promise(r=>setTimeout(r,20));
check(el('mqtt-password').value===''&&!mqttPopulated,'Logout clears secret');
document.documentElement.dataset.smoke='pass';
}catch(error){document.documentElement.dataset.smoke='fail';document.documentElement.dataset.failure=error.message;}});
</script>`;
fs.writeFileSync(path.join(target,'index.html'),`<!doctype html><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="style.css"><div id="dashboard">${panel}</div>${fixture}`);
for(const width of [1440,390]){
const result=spawnSync('C:/Program Files/Google/Chrome/Application/chrome.exe',['--headless','--disable-gpu','--no-sandbox','--no-first-run','--no-default-browser-check','--user-data-dir='+path.join(target,'chrome-'+width),'--window-size='+width+',1200','--virtual-time-budget=2000','--dump-dom','file:///'+path.join(target,'index.html').replaceAll('\\','/')],{encoding:'utf8',windowsHide:true,timeout:30000,maxBuffer:2e6});
if(result.error||!result.stdout.includes('data-smoke="pass"')){fs.writeFileSync(path.join(target,'failure.txt'),String(result.stdout)+String(result.stderr));throw Error('MQTT browser test failed: '+width);}
console.log('PASS '+width+': load, save, validation, secret handling, refresh and logout');
}
