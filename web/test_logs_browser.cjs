const fs=require('node:fs'),path=require('node:path'),{spawnSync}=require('node:child_process');
const target=path.resolve('local/logs-browser');fs.mkdirSync(target,{recursive:true});
for(const name of ['logs.js','style.css'])fs.copyFileSync('web/'+name,path.join(target,name));
const html=fs.readFileSync('web/index.html','utf8');
const local=html.match(/<section id="local-log-panel"[\s\S]*?<\/section>/)[0],remote=html.match(/<section id="remote-log-panel"[\s\S]*?<\/section>/)[0];
const fixture=`<script>
let reads=0,lastQuery,lastSave,opened,expire=false;
let settings={local:{buffer_kib:128,file_enabled:false,storage:'memory',file_kib:1024,file_supported:true},remote:{enabled:false,host:'',port:514,protocol:'udp'}};
window.open=(url,name)=>{opened={url,name};return {};};
HTMLAnchorElement.prototype.click=function(){window.downloadName=this.download;};
window.fetch=async(url,options={})=>{
 let value,status=200;
 if(expire){status=401;value={error:'Sign in'};}
 else if(url==='/api/session')value={csrf:'test'};
 else if(url==='/api/logs/settings'){
   if(options.method==='POST'){if(options.headers['X-CSRF-Token']!=='test')throw Error('Missing CSRF');lastSave=JSON.parse(options.body);settings=lastSave;value={settings,message:'Saved'};}
   else value=settings;
 }else if(url.startsWith('/api/logs?')){reads++;lastQuery=new URL('http://router'+url).searchParams;value={lines:['<img src=x onerror=alert(1)>','newest record'],updated_at:1700000000,note:'Test buffer',truncated:false};}
 else throw Error('Unexpected URL '+url);
 return {ok:status===200,status,json:async()=>structuredClone(value)};
};
</script>`;
const tests=`<script>
window.addEventListener('load',async()=>{try{
 const el=id=>document.getElementById(id),check=(v,m)=>{if(!v)throw Error(m);},wait=ms=>new Promise(r=>setTimeout(r,ms));
 await wait(100);el('logs-refresh').click();await wait(100);
 check(reads>0&&el('logs-output').textContent.includes('newest record'),'Live log load');
 check(!el('logs-output').querySelector('img'),'Log text interpreted as HTML');
 el('logs-category').value='kernel';el('logs-category').dispatchEvent(new Event('change'));await wait(100);check(lastQuery.get('category')==='kernel','Category');
 el('logs-search').value='USB';el('logs-search').dispatchEvent(new Event('input'));await wait(400);check(lastQuery.get('search')==='USB','Search');
 el('logs-live').checked=false;el('logs-live').dispatchEvent(new Event('change'));const before=reads;await wait(2200);check(reads===before,'Pause did not stop polling');
 el('logs-refresh').click();await wait(100);check(reads===before+1,'Refresh while paused');
 el('logs-download').click();check(window.downloadName.endsWith('.log'),'Download');
 el('logs-window').click();check(opened.url==='/logs.html#kernel','Live window');
 el('logs-remote-enabled').checked=true;el('logs-host').value='collector.example.com';el('logs-port').value='1514';el('logs-protocol').value='tcp';el('logs-remote-form').requestSubmit();await wait(100);
 check(lastSave.remote.host==='collector.example.com'&&lastSave.remote.protocol==='tcp','Remote save');
 el('logs-file-enabled').checked=true;el('logs-storage').value='persistent';el('logs-local-form').requestSubmit();await wait(100);
 check(lastSave.local.storage==='persistent'&&lastSave.remote.host==='collector.example.com','Local save preserves remote');
 check(document.documentElement.scrollWidth<=innerWidth,'Horizontal overflow');
 el('dashboard').hidden=true;await wait(100);check(el('logs-output').textContent==='','Logout clears records');
 document.documentElement.dataset.smoke='pass';
 }catch(error){document.documentElement.dataset.smoke='fail';document.documentElement.dataset.failure=error.message;}});
</script>`;
fs.writeFileSync(path.join(target,'index.html'),`<!doctype html><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="style.css"><div id="dashboard">${local}${remote}</div>${fixture}<script src="logs.js"></script>${tests}`);
const popup=fs.readFileSync('web/logs.html','utf8').replace('href="/style.css"','href="style.css"').replace('<script src="/logs.js" defer></script>','').replace('</body>',fixture+`<script src="logs.js"></script><script>window.addEventListener('load',async()=>{await new Promise(r=>setTimeout(r,100));document.documentElement.dataset.smoke=document.getElementById('logs-output').textContent.includes('newest record')?'pass':'fail';});</script></body>`);
fs.writeFileSync(path.join(target,'popup.html'),popup);
for(const [name,width] of [['index.html',1440],['index.html',390],['popup.html',1000]]){
 const result=spawnSync('C:/Program Files/Google/Chrome/Application/chrome.exe',['--headless','--disable-gpu','--no-sandbox','--no-first-run','--no-default-browser-check','--user-data-dir='+path.join(target,'chrome-'+name+'-'+width),'--window-size='+width+',1000','--virtual-time-budget=6000','--dump-dom','file:///'+path.join(target,name).replaceAll('\\','/')],{encoding:'utf8',windowsHide:true,timeout:30000,maxBuffer:2e6});
 if(result.error||!result.stdout.includes('data-smoke="pass"')){fs.writeFileSync(path.join(target,'failure.txt'),String(result.stdout)+String(result.stderr));throw Error('Log browser test failed '+name+' '+width);}
 console.log('PASS '+name+' '+width+': log UI, safe text, filters, pause, export, popup, syslog settings and logout');
}
