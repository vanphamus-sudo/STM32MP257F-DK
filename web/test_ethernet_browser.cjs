const fs=require('node:fs'),path=require('node:path'),{spawnSync}=require('node:child_process');
const target=path.resolve('local/ethernet-browser');fs.mkdirSync(target,{recursive:true});
for(const file of ['ethernet.js','style.css'])fs.copyFileSync('web/'+file,path.join(target,file));
const source=fs.readFileSync('web/index.html','utf8');
const panel=source.match(/<section id="ethernet-panel"[\s\S]*?<\/section>/)[0].replace(' hidden','');
const fixture=`<script>
const el=id=>document.getElementById(id),navigation=el('router-navigation');let csrf='token',saves=0,reject=false;
let state={device:'end0',mode:'lan',lan_vlan:10,wan_vlan:20,revision:'one'};
async function api(route,data){if(route!=='ethernet')throw Error('Bad route');if(data){if(reject)throw Error('Network settings changed');if(data.revision!==state.revision)throw Error('Bad revision');state={...state,...data,revision:'two'};saves++;return {ethernet:state,message:'Saved for next reboot'};}return {...state};}
</script><script src="ethernet.js"></script><script>
window.addEventListener('load',async()=>{try{
const check=(ok,message)=>{if(!ok)throw Error(message);};
showEthernet(true);await new Promise(r=>setTimeout(r,30));
check(!el('eth-fields').disabled&&el('eth-mode').value==='lan','Load');
el('eth-mode').value='both';el('eth-mode').dispatchEvent(new Event('change'));
showEthernet(true);await new Promise(r=>setTimeout(r,30));
check(el('eth-mode').value==='both','Status refresh preserves unsaved mode');
check(!el('eth-vlans').hidden,'VLAN controls');el('eth-lan').value=100;el('eth-wan').value=200;
el('eth-form').requestSubmit();await new Promise(r=>setTimeout(r,30));
check(saves===1&&state.mode==='both'&&state.lan_vlan===100&&state.wan_vlan===200,'Save VLANs');
reject=true;el('eth-mode').value='wan';el('eth-mode').dispatchEvent(new Event('change'));el('eth-form').requestSubmit();await new Promise(r=>setTimeout(r,30));
check(saves===1&&el('eth-message').textContent.includes('changed')&&!el('eth-fields').disabled,'Save error');
check(el('eth-vlans').hidden&&el('eth-help').textContent.includes('Wi-Fi'),'WAN guidance');
check(document.documentElement.scrollWidth<=innerWidth,'Layout overflow');
document.documentElement.dataset.smoke='pass';
}catch(e){document.documentElement.dataset.smoke='fail';document.documentElement.dataset.failure=e.message;}});
</script>`;
fs.writeFileSync(path.join(target,'index.html'),`<!doctype html><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="style.css"><div id="dashboard"><nav id="router-navigation"><a href="#ethernet-panel">Ethernet</a></nav>${panel}</div>${fixture}`);
for(const width of [1440,390]){
const result=spawnSync('C:/Program Files/Google/Chrome/Application/chrome.exe',['--headless','--disable-gpu','--no-sandbox','--no-first-run','--no-default-browser-check','--user-data-dir='+path.join(target,'chrome-'+width),'--window-size='+width+',1200','--virtual-time-budget=2000','--dump-dom','file:///'+path.join(target,'index.html').replaceAll('\\','/')],{encoding:'utf8',windowsHide:true,timeout:30000,maxBuffer:2e6});
if(result.error||!result.stdout.includes('data-smoke="pass"')){fs.writeFileSync(path.join(target,'failure.txt'),String(result.stdout)+String(result.stderr));throw Error('Ethernet browser test failed: '+width);}
console.log('PASS '+width+': load, VLAN selection/save, stale save error and layout');
}
