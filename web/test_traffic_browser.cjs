const fs=require('node:fs'),path=require('node:path'),{spawnSync}=require('node:child_process');
const target=path.resolve('local/traffic-browser');fs.mkdirSync(target,{recursive:true});
fs.copyFileSync('web/style.css',path.join(target,'style.css'));
const panel=fs.readFileSync('web/index.html','utf8').match(/<section id="traffic-panel"[\s\S]*?<\/section>/)[0];
const fn=fs.readFileSync('web/app.js','utf8').match(/function showTraffic\(s\) \{[\s\S]*$/)[0];
const helpers=fs.readFileSync('web/app.js','utf8').split('function statusText')[1].split('let csrf')[0];
const script=`const el=id=>document.getElementById(id);function statusText${helpers}${fn}
try{const check=(ok,message)=>{if(!ok)throw Error(message);};
showTraffic({available:true,stale_seconds:0,roles:{wan:{device:'wwan0',total_tx_bytes:1048576,total_rx_bytes:1073741824,tx_bytes_per_second:1024,rx_bytes_per_second:2048}}});
check(!el('traffic-panel').hidden,'Visible');check(el('traffic-rows').textContent.includes('1.00 MiB')&&el('traffic-rows').textContent.includes('1.00 GiB'),'Byte units');
check(el('traffic-rows').textContent.includes('1.00 KiB/s'),'Rates');
showTraffic({available:true,stale_seconds:30,roles:{}});check(el('traffic-state').textContent.includes('Last recorded'),'Stale state');
check(document.documentElement.scrollWidth<=innerWidth,'Overflow');
showTraffic({available:false});check(el('traffic-panel').hidden,'Unavailable');
document.documentElement.dataset.smoke='pass';}catch(e){document.documentElement.dataset.smoke='fail';document.documentElement.dataset.failure=e.message;}`;
fs.writeFileSync(path.join(target,'index.html'),`<!doctype html><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="style.css">${panel}<script>${script}</script>`);
for(const width of [1440,390]){
const result=spawnSync('C:/Program Files/Google/Chrome/Application/chrome.exe',['--headless','--disable-gpu','--no-sandbox','--no-first-run','--no-default-browser-check','--user-data-dir='+path.join(target,'chrome-'+width),'--window-size='+width+',1200','--virtual-time-budget=1000','--dump-dom','file:///'+path.join(target,'index.html').replaceAll('\\','/')],{encoding:'utf8',windowsHide:true,timeout:30000,maxBuffer:2e6});
if(result.error||!result.stdout.includes('data-smoke="pass"')){fs.writeFileSync(path.join(target,'failure.txt'),String(result.stdout)+String(result.stderr));throw Error('Traffic browser test failed: '+width);}
console.log('PASS '+width+': byte units, rates, freshness and availability');
}
