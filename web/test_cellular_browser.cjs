const fs=require('node:fs'),path=require('node:path'),{spawnSync}=require('node:child_process');
const target=path.resolve('local/cellular-browser');fs.mkdirSync(target,{recursive:true});
for(const name of ['cellular.js','style.css'])fs.copyFileSync('web/'+name,path.join(target,name));
const html=fs.readFileSync('web/index.html','utf8');
const panel=html.match(/<section id="cellular-panel"[\s\S]*?<\/section>/)[0];
if(!html.includes('href="#cellular-panel"')||!html.includes('href="#account-panel">Webpage login'))throw Error('Missing navigation');
const fixture=`<script>
const el=id=>document.getElementById(id);let csrf='test',last,refreshes=0;
const state={apn:'telstra.internet',username:'',auth:'none',iptype:'ipv4v6',password_saved:true};
async function api(route,data){if(route!=='cellular')throw Error('Unexpected route');if(data===undefined)return state;last=data;return {settings:{...data,password_saved:true},message:'Saved'};}
async function refresh(){refreshes++;}
</script><script src="cellular.js"></script><script>
window.addEventListener('load',async()=>{try{
const check=(value,message)=>{if(!value)throw Error(message);},wait=()=>new Promise(r=>setTimeout(r,50));
await wait();check(el('cellular-apn').value==='telstra.internet','Load APN');
check(el('cellular-password').value==='','Secret must stay blank');
el('cellular-username').value='test-user';el('cellular-auth').value='chap';
el('cellular-password').value='new-secret';el('cellular-form').requestSubmit();await wait();
check(last.username==='test-user'&&last.password==='new-secret'&&last.auth==='chap','Save credentials');
check(el('cellular-password').value===''&&refreshes===1,'Clear secret after saving');
el('cellular-clear-password').checked=true;el('cellular-form').requestSubmit();await wait();
check(last.clear_password===true&&last.password==='','Clear saved password');
el('cellular-apn').value='edited.apn';await loadCellular();check(el('cellular-apn').value==='edited.apn','Preserve edits');
el('cellular-password').value='discard';el('dashboard').hidden=true;await wait();check(el('cellular-password').value==='','Logout clears secret');
el('dashboard').hidden=false;await wait();check(el('cellular-apn').value==='telstra.internet','Reload on next login');
check(document.documentElement.scrollWidth<=innerWidth,'Horizontal overflow');
document.documentElement.dataset.smoke='pass';
}catch(error){document.documentElement.dataset.smoke='fail';document.documentElement.dataset.failure=error.message;}});
</script>`;
fs.writeFileSync(path.join(target,'index.html'),`<!doctype html><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="style.css"><div id="dashboard">${panel}</div>${fixture}`);
for(const width of [1440,390]){
const result=spawnSync('C:/Program Files/Google/Chrome/Application/chrome.exe',['--headless','--disable-gpu','--no-sandbox','--no-first-run','--no-default-browser-check','--user-data-dir='+path.join(target,'chrome-'+width),'--window-size='+width+',1000','--virtual-time-budget=2000','--dump-dom','file:///'+path.join(target,'index.html').replaceAll('\\','/')],{encoding:'utf8',windowsHide:true,timeout:30000,maxBuffer:2e6});
if(result.error||!result.stdout.includes('data-smoke="pass"')){fs.writeFileSync(path.join(target,'failure.txt'),String(result.stdout)+String(result.stderr));throw Error('Cellular browser test failed: '+width);}
console.log('PASS '+width+': load, save, credential clearing, edit preservation, login reload and layout');
}
