const fs=require('node:fs'),path=require('node:path'),{spawnSync}=require('node:child_process');
const target=path.resolve('local/usb-tethering-browser');fs.mkdirSync(target,{recursive:true});
for(const file of ['usb-tethering.js','style.css'])fs.copyFileSync('web/'+file,path.join(target,file));
const source=fs.readFileSync('web/index.html','utf8');
const panel=source.match(/<section id="usb-panel"[\s\S]*?<\/section>/)[0].replace(' hidden','');
const fixture=`<script>
const el=id=>document.getElementById(id),navigation=el('router-navigation');let csrf='token',saves=0,reject=false;
let state={available:true,device:'usb0',enabled:false,revision:'one'};
async function api(route,data){if(route!=='usb-tethering')throw Error('Bad route');if(data){if(reject)throw Error('Network settings changed');if(data.revision!==state.revision)throw Error('Bad revision');state={...state,...data,revision:String(saves+2)};saves++;return {usb:state,message:'Saved for next reboot'};}return {...state};}
</script><script src="usb-tethering.js"></script><script>
window.addEventListener('load',async()=>{try{
const check=(ok,message)=>{if(!ok)throw Error(message);},wait=()=>new Promise(r=>setTimeout(r,30));
showUsbTethering(true);await wait();
check(!el('usb-fields').disabled&&el('usb-enabled').value==='false','Load management mode');
el('usb-enabled').value='true';showUsbTethering(true);await wait();
check(el('usb-enabled').value==='true','Periodic refresh preserves unsaved changes');
el('usb-form').requestSubmit();await wait();check(saves===1&&state.enabled,'Enable tethering');
el('usb-enabled').value='false';el('usb-form').requestSubmit();await wait();check(saves===2&&!state.enabled,'Disable tethering');
reject=true;el('usb-form').requestSubmit();await wait();
check(saves===2&&el('usb-message').textContent.includes('changed')&&!el('usb-fields').disabled,'Stale save error');
state.available=false;el('usb-reload').click();await wait();
check(el('usb-fields').disabled&&el('usb-message').textContent.includes('USER1'),'Missing USB recovery guidance');
check(document.documentElement.scrollWidth<=innerWidth,'Layout overflow');
document.documentElement.dataset.smoke='pass';
}catch(e){document.documentElement.dataset.smoke='fail';document.documentElement.dataset.failure=e.message;}});
</script>`;
fs.writeFileSync(path.join(target,'index.html'),`<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="style.css"><div id="dashboard"><nav id="router-navigation"><a href="#usb-panel">USB</a></nav>${panel}</div>${fixture}`);
for(const width of [1440,390]){
  const result=spawnSync('C:/Program Files/Google/Chrome/Application/chrome.exe',['--headless','--disable-gpu','--no-sandbox','--no-first-run','--no-default-browser-check','--user-data-dir='+path.join(target,'chrome-'+width),'--window-size='+width+',1200','--virtual-time-budget=2000','--dump-dom','file:///'+path.join(target,'index.html').replaceAll('\\','/')],{encoding:'utf8',windowsHide:true,timeout:30000,maxBuffer:2e6});
  if(result.error||!result.stdout.includes('data-smoke="pass"')){fs.writeFileSync(path.join(target,'failure.txt'),String(result.stdout)+String(result.stderr));throw Error('USB browser test failed: '+width);}
  console.log('PASS '+width+': load, enable/disable, unsaved changes, stale error, recovery guidance, layout');
}
