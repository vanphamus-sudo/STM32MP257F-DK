const fs=require('node:fs'),path=require('node:path'),{spawn}=require('node:child_process');
const target=path.resolve('local/navigation-browser');fs.mkdirSync(target,{recursive:true});
for(const file of ['app.js','router-features.js','user-guide.js','style.css'])fs.copyFileSync('web/'+file,path.join(target,file));
let html=fs.readFileSync('web/index.html','utf8').replace(/<script src="\/(?!app.js|router-features.js|user-guide.js)[^"]+" defer><\/script>/g,'').replaceAll('src="/','src="').replace('href="/style.css"','href="style.css"');
const fixture=`<script>
const refreshFixture={hostname:'Test router',software:{string:'Test version'},uptime:3600,modem:{state:'connected',operator:'Test network',signal:80},services:{dnsmasq:'active','router-firewall':'active'},wan_addresses:['10.0.0.2'],settings:{start:100,end:200,lease_hours:12,dns:['1.1.1.1']},leases:Array.from({length:12},(_,i)=>({name:'Client '+i,address:'192.168.10.'+(i+2),mac:'02:00:00:00:00:'+String(i).padStart(2,'0')})),router_features_available:true,traffic:{available:true,stale_seconds:0,roles:{wan:{device:'wwan0',total_tx_bytes:1024,total_rx_bytes:2048,tx_bytes_per_second:12,rx_bytes_per_second:24}}}};
window.fetch=async url=>{
 if(url==='/api/status')return {ok:true,json:async()=>structuredClone(refreshFixture)};
 if(url==='/api/features/sms'){await new Promise(resolve=>setTimeout(resolve,100));return {ok:true,json:async()=>({messages:[{id:1,number:'+10000000000',text:'Test message line\\n'.repeat(40),state:'received',time:'2026-11-12'}],total:1,failed:0,truncated:false,updated_at:Date.now()/1000})};}
 if(url==='/api/session')return {ok:false,status:401,json:async()=>({error:'Sign in'})};
 if(url==='/api/features'){
  const settings={};for(const [section,[,,fields]] of Object.entries(routerFeatureSections)){settings[section]={};for(const [name,[,type]] of Object.entries(fields))settings[section][name]=type==='boolean'?false:type==='number'?60:type==='list'?['any']:'';}
  return {ok:true,status:200,json:async()=>({settings,revision:'one',cellular_choices:${JSON.stringify(JSON.parse(fs.readFileSync('web/mobile-networks.json','utf8')))},capabilities:{wireguard:true,passthrough:true,dual_sim:false,hardware_note:'',band_options:[{value:'eutran-3',label:'LTE BAND 3: downlink 1805-1880 MHz; uplink 1710-1785 MHz'},{value:'eutran-28',label:'LTE BAND 28: downlink 758-803 MHz; uplink 703-748 MHz'}]},runtime:{},events:[],signal:[],pending:null})};
 }
 throw Error('Unexpected network request '+url);
};
</script>`;
const tests=`<script>
window.addEventListener('load',async()=>{try{
 const check=(ok,message)=>{if(!ok)throw Error(message);},wait=()=>new Promise(r=>setTimeout(r,50));
 await wait();csrf='fixture';el('login-panel').hidden=true;el('dashboard').hidden=false;showRouterFeatures(true);await wait();
 const headings=Array.from(navigation.querySelectorAll('[data-nav-group]>summary')).map(n=>n.textContent);
 check(headings.join('|')==='Status|Internet|Local network|Firewall|VPN|Cellular|Services|System','group ordering');
 for(const link of navigation.querySelectorAll('a[href^="#"]'))check(document.getElementById(link.hash.slice(1)),'missing target '+link.hash);
 const wg=navigation.querySelector('a[href="#rf-feature-wireguard"]'),ov=navigation.querySelector('a[href="#openvpn-panel"]'),vpn=wg.closest('details');
 check(ov.closest('details')===vpn&&vpn.querySelector('summary').textContent==='VPN','shared VPN group');
 check(!vpn.hidden&&!wg.hidden&&ov.hidden,'WireGuard visible without OpenVPN');
 el('openvpn-panel').hidden=false;await wait();check(!ov.hidden,'OpenVPN available');
 el('router-features-panel').hidden=true;await wait();check(!vpn.hidden&&wg.hidden,'VPN group follows remaining child');
 el('openvpn-panel').hidden=true;await wait();check(vpn.hidden,'hide empty VPN group');
 showRouterFeatures(true);await wait();
 el('rf-wireguard-peer_key').value='unsaved-peer';el('rf-feature-wireguard').open=false;
 el('menu-toggle').click();wg.click();await wait();
 check(el('rf-feature-wireguard').open&&document.activeElement===el('rf-feature-wireguard'),'open and focus WireGuard');
 check(wg.getAttribute('aria-current')==='location'&&el('rf-wireguard-peer_key').value==='unsaved-peer','selection preserves edits');
 check(el('menu-toggle').getAttribute('aria-expanded')==='false','mobile menu closes');
 el('rf-feature-guest').open=false;location.hash='#rf-feature-guest';await wait();
 check(el('rf-feature-guest').open&&navigation.querySelector('a[href="#rf-feature-guest"]').hasAttribute('aria-current'),'hash navigation opens and selects target');

 const topics=Object.entries(routerManualTopics);check(topics.length>=35,'manual covers all router areas');
 for(const [id] of topics)check(document.getElementById(id)?.querySelector('[data-manual-topic]')||id==='software-version'&&document.getElementById(id).nextElementSibling?.dataset.manualTopic===id,'topic guide missing '+id);

 el('rf-feature-cellular').open=true;
 el('rf-cellular-mcc').scrollIntoView({block:'center'});
 check(el('rf-cellular-mcc').getBoundingClientRect().height>20&&getComputedStyle(el('rf-cellular-mcc')).visibility==='visible','MCC dropdown displayed');
 check(el('rf-cellular-mcc').options.length>200,'full MCC directory loaded');
 el('rf-cellular-mcc').value='505';el('rf-cellular-mcc').dispatchEvent(new Event('change'));
 check(el('rf-cellular-mnc').textContent.includes('Optus')&&!el('rf-cellular-mnc').disabled,'Australian MNC dropdown displayed');
 el('rf-cellular-band-eutran-3').closest('label').click();
 el('rf-cellular-band-eutran-28').closest('label').click();
 check(routerFeatureForms.get('cellular').form.readCellularBands()==='eutran-3,eutran-28','click band rows selects multiple');
 el('rf-cellular-band-any').closest('label').click();
 check(routerFeatureForms.get('cellular').form.readCellularBands()==='any','click Automatic clears restrictions');
 const inputs=Array.from(document.querySelectorAll('input[id],select[id],textarea[id]')).filter(input=>input.id!=='manual-search');
 check(inputs.every(input=>input.dataset.manualHelp==='true'),'missing field explanation '+inputs.filter(input=>!input.dataset.manualHelp).map(input=>input.id));
 check(el('rf-wireguard-peer_key').value==='unsaved-peer','help preserves unsaved values');
 check(el('rf-wireguard-address').value===''&&el('rf-passthrough-client_mac').value==='','manual examples do not populate settings');
 for(const input of inputs){const help=document.getElementById(input.getAttribute('aria-describedby').split(' ').at(-1));check(help?.classList.contains('field-guide'),'accessible field help '+input.id);}
 el('manual-search').value='certificate';el('manual-search').dispatchEvent(new Event('input'));await wait();
 check(Array.from(el('manual-topic-list').children).some(item=>!item.hidden&&item.textContent.includes('OpenVPN')),'manual search uses setup details');
 el('manual-search').value='keepalive';el('manual-search').dispatchEvent(new Event('input'));
 check(Array.from(el('manual-topic-list').children).some(item=>!item.hidden&&item.textContent.includes('OpenVPN')),'search finds individual setting explanations');
 el('manual-search').value='wifi';el('manual-search').dispatchEvent(new Event('input'));
 check(Array.from(el('manual-topic-list').children).some(item=>!item.hidden&&item.textContent.includes('Wi-Fi')),'search tolerates punctuation');
 el('manual-search').value='no-such-help-topic-xyz';el('manual-search').dispatchEvent(new Event('input'));check(el('manual-search-result').textContent.startsWith('0 help topics'),'search empty state');
 const wrapper=document.createElement('label'),meter=document.createElement('input');meter.dataset.register='format';wrapper.append(meter);el('modbus-devices').append(wrapper);await wait();
 check(meter.dataset.manualHelp==='true'&&wrapper.textContent.includes('FLOAT32'),'dynamic meter help');
 el('openvpn-panel').hidden=true;el('manual-topic-list').querySelector('a[href="#openvpn-panel"]').click();await wait();
 check(!el('manual-topic-preview').hidden&&el('manual-topic-preview').textContent.includes('not currently available'),'unavailable feature help stays readable');
 const ids=Array.from(document.querySelectorAll('[id]')).map(n=>n.id);check(new Set(ids).size===ids.length,'unique help identifiers');
 check(document.documentElement.scrollWidth<=innerWidth,'layout overflow');
 await refresh();await wait();
 el('rf-feature-cellular').open=true;el('rf-cellular-mcc').scrollIntoView({block:'center'});el('rf-cellular-mcc').focus({preventScroll:true});
 const stableY=scrollY,clientRow=el('clients').firstChild,trafficRow=el('traffic-rows').firstChild,versionText=el('software-version').firstChild;
 for(let i=0;i<4;i++){await refresh();await wait();check(Math.abs(scrollY-stableY)<2,'periodic status refresh moved page');}
 check(el('clients').firstChild===clientRow&&el('traffic-rows').firstChild===trafficRow&&el('software-version').firstChild===versionText,'unchanged status keeps existing DOM');
 check(document.activeElement===el('rf-cellular-mcc')&&el('rf-cellular-mcc').value==='505','refresh preserves focus and edits');
 refreshFixture.leases[0].name='Updated client';await refresh();await wait();check(el('clients').textContent.includes('Updated client'),'changed status still renders');
 routerFeatureState.settings.sms.enabled=true;el('rf-sms-panel').open=true;await new Promise(resolve=>setTimeout(resolve,150));
 const marker=document.createElement('div');marker.style.height='1200px';marker.textContent='After inbox';el('rf-sms-panel').after(marker);marker.scrollIntoView({block:'start'});await wait();
 const smsY=scrollY,smsText=el('rf-sms-result').firstChild,deleteButton=el('rf-sms-delete-controls').querySelector('button');
 const pendingRead=routerReadSms(true);await wait();check(Math.abs(scrollY-smsY)<2&&el('rf-sms-result').firstChild===smsText,'in-flight SMS poll keeps inbox and scroll');
 await pendingRead;await wait();check(Math.abs(scrollY-smsY)<2&&el('rf-sms-result').firstChild===smsText&&el('rf-sms-delete-controls').querySelector('button')===deleteButton,'unchanged SMS poll preserves scroll and controls');
 marker.remove();
 document.documentElement.dataset.smoke='pass';
}catch(error){document.documentElement.dataset.smoke='fail';document.documentElement.dataset.failure=error.message;}});
</script>`;
html=html.replace('<script src="app.js"',fixture+'<script src="app.js"').replace('</body>',tests+'</body>');fs.writeFileSync(path.join(target,'index.html'),html);
(async()=>{
 const profile=path.join(target,'chrome-cdp');fs.mkdirSync(profile,{recursive:true});
 const portFile=path.join(profile,'DevToolsActivePort');if(fs.existsSync(portFile))fs.unlinkSync(portFile);
 const browser=spawn('C:/Program Files/Google/Chrome/Application/chrome.exe',['--headless','--disable-gpu','--no-sandbox','--no-first-run','--no-default-browser-check','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],{windowsHide:true,stdio:'ignore'});
 let socket;
 try{
  const delay=ms=>new Promise(r=>setTimeout(r,ms));
  for(let i=0;i<100&&!fs.existsSync(portFile);i++)await delay(50);
  const port=fs.readFileSync(portFile,'utf8').split('\n')[0].trim();
  const tabs=await(await fetch('http://127.0.0.1:'+port+'/json')).json();
  socket=new WebSocket(tabs.find(t=>t.type==='page').webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject;});
  let seq=0;const pending=new Map();
  socket.onmessage=event=>{const r=JSON.parse(event.data);if(r.id&&pending.has(r.id)){const p=pending.get(r.id);pending.delete(r.id);r.error?p.reject(Error(JSON.stringify(r.error))):p.resolve(r.result);}};
  const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}));});
  const evaluate=async expression=>{const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.text);return r.result.value;};
  await send('Page.enable');await send('Runtime.enable');
  for(const width of [1440,390]){
   await send('Emulation.setDeviceMetricsOverride',{width,height:1000,deviceScaleFactor:1,mobile:width===390});
   await send('Page.navigate',{url:'file:///'+path.join(target,'index.html').replaceAll('\\','/')});
   let result;
   for(let i=0;i<160;i++){result=await evaluate('({smoke:document.documentElement.dataset.smoke,failure:document.documentElement.dataset.failure,width:innerWidth})');if(result.smoke)break;await delay(50);}
   if(result.smoke!=='pass'||result.width!==width){fs.writeFileSync(path.join(target,'failure.txt'),await evaluate('document.documentElement.outerHTML'));throw Error('Navigation/manual test failed '+width+': '+JSON.stringify(result));}
   for(const value of ['eutran-3','eutran-28','any']){
    const point=await evaluate(`(()=>{const input=document.getElementById('rf-cellular-band-${value}');input.closest('label').scrollIntoView({block:'center'});const r=input.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()`);
    await send('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,...point});
    await send('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,...point});
    const selected=await evaluate("routerFeatureForms.get('cellular').form.readCellularBands()");
    const expected=value==='any'?'any':value==='eutran-3'?'eutran-3':'eutran-3,eutran-28';
    if(selected!==expected)throw Error('Real pointer band click failed '+width+': '+selected);
   }
   await evaluate('document.getElementById("rf-cellular-mcc").scrollIntoView({block:"center"})');
   const dropdown=await evaluate("(()=>{const input=document.getElementById('rf-cellular-mcc'),r=input.getBoundingClientRect();return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===input;})()");
   if(!dropdown)throw Error('MCC dropdown obscured at '+width);
   fs.writeFileSync(path.join(target,'cellular-real-'+width+'.png'),Buffer.from((await send('Page.captureScreenshot',{format:'png'})).data,'base64'));
   await evaluate('document.getElementById("router-user-guide").scrollIntoView({block:"start"})');
   fs.writeFileSync(path.join(target,'manual-real-'+width+'.png'),Buffer.from((await send('Page.captureScreenshot',{format:'png'})).data,'base64'));
   console.log('PASS actual viewport '+width+': navigation, all manual topics/fields, search, dynamic help, preserved edits and layout');
  }
  await send('Browser.close');
 }finally{if(socket)socket.close();browser.kill();}
})().catch(error=>{console.error(error);process.exitCode=1;});
