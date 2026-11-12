const fs=require('node:fs'),path=require('node:path'),{spawnSync}=require('node:child_process');
const target=path.resolve('local/router-features-browser');fs.mkdirSync(target,{recursive:true});
for(const file of ['router-features.js','style.css'])fs.copyFileSync('web/'+file,path.join(target,file));
const source=fs.readFileSync('web/index.html','utf8');
const panel=source.match(/<section id="router-features-panel"[\s\S]*?<\/section>/)[0].replace(' hidden','');
const fixture=`<script>
const el=id=>document.getElementById(id);let csrf='token',saves=0,reject=false,smsLoads=0,smsHold=false,smsFail=false,smsResolve=null;
const smsResult={messages:[{id:1,number:'+10000000000',text:'Incoming test <img src=x>',state:'received',time:'2026-11-12'},{id:2,number:'+10000000000',text:'Sent test only',state:'sent',time:'2026-11-12'}],total:2,failed:0,truncated:false};
let smsDeletes=0,allowDelete=false;window.confirm=()=>allowDelete;
let state={settings:{},revision:'one',cellular_choices:{source:{edition:'2023-11-15'},countries:[{mcc:'505',name:'Australia',networks:[{mnc:'01',name:'Telstra'},{mnc:'02',name:'Optus'}]},{mcc:'310',name:'United States',networks:[{mnc:'260',name:'T-Mobile'}]}],current:{code:'50501',name:'Telstra'}},capabilities:{hardware_note:'Hardware support required',dual_sim:false,band_options:[{value:'eutran-3',label:'LTE BAND 3: downlink 1805-1880 MHz'},{value:'eutran-28',label:'LTE BAND 28: downlink 758-803 MHz'}]},runtime:{active_uplink:'wan'},events:[{time:1000,kind:'test',message:'<img src=x onerror=alert(1)>'}],signal:[{time:1000,rsrp:'-100 dBm',rsrq:'-10 dB',sinr:'15 dB',cell_id:'123'}],pending:null};
async function api(route,data){
 if(route==='features'&&!data){if(!Object.keys(state.settings).length)for(const [section,[,,fields]] of Object.entries(routerFeatureSections)){state.settings[section]={};for(const [name,[,type]] of Object.entries(fields))state.settings[section][name]=type==='boolean'?false:type==='number'?60:type==='list'?['any']:'';}return JSON.parse(JSON.stringify(state));}
 if(route==='features'&&data){if(reject)throw Error('stale settings');if(data.revision!==state.revision)throw Error('bad revision');state.settings[data.section]=data.settings;state.revision=String(++saves);return {message:'Saved'};}
 if(route==='features/diagnostics')return {output:'diagnostic output'};
 if(route==='features/action'){state.pending=null;return {message:'Confirmed'};}
 if(route==='features/sms'&&data.action==='list'){smsLoads++;if(smsFail)throw Error('Modem unavailable');if(smsHold)return new Promise(resolve=>smsResolve=resolve);return structuredClone(smsResult);}
 if(route==='features/sms'&&data.action==='delete'){smsDeletes++;checkDeleteId=data.id;smsResult.messages=smsResult.messages.filter(message=>message.id!==data.id);smsResult.total--;return {message:'Deleted'};}
 throw Error('Unexpected API '+route);
}
let checkDeleteId=null;
</script><script src="router-features.js"></script><script>
window.addEventListener('load',async()=>{try{
const check=(ok,message)=>{if(!ok)throw Error(message);},wait=()=>new Promise(r=>setTimeout(r,30));
showRouterFeatures(true);await wait();
check(routerFeatureForms.size===13,'all feature forms');
check(el('rf-watchdog-enabled').value==='false','features disabled by default');
el('rf-watchdog-enabled').value='true';showRouterFeatures(true);await wait();
check(el('rf-watchdog-enabled').value==='true','refresh preserves edits');
routerFeatureForms.get('watchdog').form.requestSubmit();await wait();
check(saves===1&&state.settings.watchdog.enabled,'save feature');
reject=true;routerFeatureForms.get('watchdog').form.requestSubmit();await wait();
check(routerFeatureForms.get('watchdog').message.textContent==='stale settings','stale error visible');
reject=false;el('rf-passthrough-enabled').value='true';el('rf-passthrough-client_mac').value='02:11:22:33:44:55';
routerFeatureForms.get('passthrough').form.requestSubmit();await wait();
check(saves===2&&state.settings.passthrough.enabled&&state.settings.passthrough.client_mac==='02:11:22:33:44:55','passthrough settings submit');
const cellular=routerFeatureForms.get('cellular').form;
check(el('rf-cellular-mcc').value===''&&el('rf-cellular-current').textContent.includes('Telstra'),'current registration does not change automatic selection');
check(el('rf-cellular-mcc').textContent.includes('Australia')&&el('rf-cellular-band-options').textContent.includes('MHz'),'named country and MHz labels');
el('rf-cellular-mcc').value='505';el('rf-cellular-mcc').dispatchEvent(new Event('change'));el('rf-cellular-mnc').value='01';
check(cellular.readCellularOperator()==='50501','preserve two-digit MNC zero');
el('rf-feature-cellular').open=true;
check(el('rf-cellular-mcc').getClientRects().length&&getComputedStyle(el('rf-cellular-mcc')).visibility==='visible','MCC dropdown is displayed');
const bandList=el('rf-cellular-band-options');
check(bandList.textContent.includes('MHz')&&cellular.readCellularBands()==='any','named LTE band list with automatic default');
el('rf-cellular-band-eutran-3').closest('label').click();check(cellular.readCellularBands()==='eutran-3','specific LTE band clears automatic');
cellular.requestSubmit();await wait();check(state.settings.cellular.operator==='50501','save named operator as existing PLMN schema');
check(state.settings.cellular.bands.join(',')==='eutran-3','selected LTE bands submitted');
el('rf-cellular-band-eutran-28').closest('label').click();check(cellular.readCellularBands()==='eutran-3,eutran-28','multiple LTE bands retained');
await routerLoad(false);check(cellular.readCellularBands()==='eutran-3,eutran-28','refresh preserves unsaved multiple bands');
el('rf-cellular-band-any').closest('label').click();check(cellular.readCellularBands()==='any','automatic clears band restrictions');
el('rf-cellular-mcc').value='310';el('rf-cellular-mcc').dispatchEvent(new Event('change'));el('rf-cellular-mnc').value='260';check(cellular.readCellularOperator()==='310260','three-digit MNC');
el('rf-cellular-mcc').value='custom';el('rf-cellular-mcc').dispatchEvent(new Event('change'));el('rf-cellular-custom-mcc').value='999';el('rf-cellular-custom-mnc').value='001';check(cellular.readCellularOperator()==='999001','custom leading zeros');
el('rf-cellular-custom-mnc').value='bad';el('rf-cellular-mcc').value='';el('rf-cellular-mcc').dispatchEvent(new Event('change'));check(cellular.readCellularOperator()===''&&cellular.checkValidity(),'automatic ignores hidden invalid custom fields');
el('rf-sms-list').click();await wait();check(smsLoads===0&&el('rf-sms-result').textContent.includes('SMS is off'),'SMS disabled guidance');
state.settings.sms.enabled=true;await routerLoad(false);smsHold=true;el('rf-sms-list').click();await wait();check(el('rf-sms-list').disabled&&el('rf-sms-result').textContent.includes('Please wait'),'SMS visible loading feedback');
smsResolve(structuredClone(smsResult));await wait();check(el('rf-sms-result').textContent.includes('Incoming test')&&!el('rf-sms-result').textContent.includes('Sent test only')&&!el('rf-sms-result').querySelector('img'),'received-only inbox and safe text');
el('rf-sms-view').value='all';el('rf-sms-view').dispatchEvent(new Event('change'));check(el('rf-sms-result').textContent.includes('Sent test only'),'all stored view');
smsHold=false;smsFail=true;el('rf-sms-list').click();await wait();check(el('rf-sms-status').textContent.includes('Could not read SMS')&&el('rf-sms-result').textContent.includes('Incoming test')&&!el('rf-sms-list').disabled,'SMS error retains messages and permits retry');
smsFail=false;const priorLoads=smsLoads;el('rf-sms-panel').open=true;await wait();check(smsLoads>priorLoads&&el('rf-sms-result').textContent.includes('Incoming test'),'inbox opens and refreshes');
el('rf-sms-delete-controls').querySelector('button').click();await wait();check(smsDeletes===0,'cancel deletion retains SMS');
allowDelete=true;el('rf-sms-delete-controls').querySelector('button').click();await wait();check(smsDeletes===1&&checkDeleteId===1&&!el('rf-sms-result').textContent.includes('Incoming test')&&el('rf-sms-result').textContent.includes('Sent test only'),'delete one selected SMS and refresh');
check(el('rf-events').textContent.includes('<img')&&!el('rf-events').querySelector('img'),'event text cannot inject HTML');
check(el('rf-chart').querySelectorAll('path').length===3,'signal graph');
el('rf-diagnostics').requestSubmit();await wait();check(el('rf-diagnostic-result').textContent==='diagnostic output','diagnostics result');
state.pending={token:'abc',deadline:Date.now()/1000+180};await routerLoad(false);check(!el('rf-pending').hidden,'confirmation prompt');
el('rf-confirm').click();await wait();check(el('rf-pending').hidden,'confirm network settings');
el('rf-wireguard-private_key').value='secret';el('dashboard').hidden=true;await wait();check(!el('rf-wireguard-private_key').value&&!routerFeatureState,'logout clears private key');
el('dashboard').hidden=false;
check(document.documentElement.scrollWidth<=innerWidth,'mobile layout overflow');
document.documentElement.dataset.smoke='pass';
}catch(e){document.documentElement.dataset.smoke='fail';document.documentElement.dataset.failure=e.message;}});
</script>`;
fs.writeFileSync(path.join(target,'index.html'),`<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="style.css"><div id="dashboard">${panel}</div>${fixture}`);
for(const width of [1440,390]){
 const result=spawnSync('C:/Program Files/Google/Chrome/Application/chrome.exe',['--headless','--disable-gpu','--no-sandbox','--no-first-run','--no-default-browser-check','--user-data-dir='+path.join(target,'chrome-'+width),'--window-size='+width+',1200','--virtual-time-budget=3000','--dump-dom','file:///'+path.join(target,'index.html').replaceAll('\\','/')],{encoding:'utf8',windowsHide:true,timeout:30000,maxBuffer:2e6});
 if(result.error||!result.stdout.includes('data-smoke="pass"')){fs.writeFileSync(path.join(target,'failure.txt'),String(result.stdout)+String(result.stderr));throw Error('Router features browser test failed: '+width+' '+String(result.error||''));}
 console.log('PASS '+width+': feature forms, save, stale errors, graph, XSS, diagnostics, confirmation, logout and layout');
}
