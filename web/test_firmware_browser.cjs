const fs=require('node:fs'),path=require('node:path'),{spawnSync}=require('node:child_process');
const target=path.resolve('local/firmware-browser');fs.mkdirSync(target,{recursive:true});
for(const file of ['firmware.js','style.css'])fs.copyFileSync('web/'+file,path.join(target,file));
const panel=fs.readFileSync('web/index.html','utf8').match(/<section id="firmware-panel"[\s\S]*?<\/section>/)[0];
const fixture=`<script>
const el=id=>document.getElementById(id);let saves=0,updates=0,last;
let state={available:true,enabled:false,public_key:'PUBLIC',allowed_hosts:['updates.test'],job:{state:'idle'},system:{ready:false,reason:'A/B provisioning required'}};
async function api(route,data){last=data;if(route==='firmware/settings'){saves++;state={...state,...data};return {firmware:state,message:'Saved'};}if(route==='firmware/update'){updates++;return {firmware:{id:'1'},message:'Queued'};}throw Error('Wrong route');}
</script><script src="firmware.js"></script><script>
window.addEventListener('load',async()=>{try{
const check=(ok,message)=>{if(!ok)throw Error(message);};showFirmware(state);
check(!el('firmware-panel').hidden&&el('start-firmware').disabled,'Disabled state');
check(el('firmware-system-ready').textContent.includes('provisioning'),'OS readiness');
el('firmware-enabled').value='true';el('firmware-hosts').value='updates.test\\nmirror.test';el('firmware-settings-form').requestSubmit();await new Promise(r=>setTimeout(r,20));
check(saves===1&&last.enabled&&last.allowed_hosts.length===2&&!el('start-firmware').disabled,'Save settings');
el('firmware-url').value='https://updates.test/release.rupdate';el('firmware-update-form').requestSubmit();await new Promise(r=>setTimeout(r,20));
check(updates===1&&last.firmware.includes('release.rupdate')&&el('start-firmware').disabled,'Submit update');
showFirmware({...state,job:{state:'installing'}});check(el('start-firmware').disabled,'Busy state');
showFirmware({...state,job:{state:'failed',error:'Bad signature',rolled_back:true}});
check(el('firmware-result').textContent.includes('Bad signature')&&el('firmware-result').textContent.includes('restored'),'Failure result');
check(document.documentElement.scrollWidth<=innerWidth,'Layout overflow');
document.documentElement.dataset.smoke='pass';
}catch(error){document.documentElement.dataset.smoke='fail';document.documentElement.dataset.failure=error.message;}});
</script>`;
fs.writeFileSync(path.join(target,'index.html'),`<!doctype html><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="style.css"><div id="dashboard">${panel}</div>${fixture}`);
for(const width of [1440,390]){
const result=spawnSync('C:/Program Files/Google/Chrome/Application/chrome.exe',['--headless','--disable-gpu','--no-sandbox','--no-first-run','--no-default-browser-check','--user-data-dir='+path.join(target,'chrome-'+width),'--window-size='+width+',1200','--virtual-time-budget=2000','--dump-dom','file:///'+path.join(target,'index.html').replaceAll('\\','/')],{encoding:'utf8',windowsHide:true,timeout:30000,maxBuffer:2e6});
if(result.error||!result.stdout.includes('data-smoke="pass"')){fs.writeFileSync(path.join(target,'failure.txt'),String(result.stdout)+String(result.stderr));throw Error('Firmware browser test failed: '+width);}
console.log('PASS '+width+': settings, update submission, busy/error states and layout');
}
