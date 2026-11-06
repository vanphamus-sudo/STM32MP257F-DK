// Standalone browser checks; uses mocked APIs and never changes the router.
const fs=require('node:fs'),path=require('node:path'),{spawnSync}=require('node:child_process');
const target=path.resolve('local/port-forwarding-browser');fs.mkdirSync(target,{recursive:true});
for(const name of ['app.js','port-forwarding.js','dhcp-reservations.js','style.css'])fs.copyFileSync(path.resolve('web',name),path.join(target,name));
const fixture={hostname:'OpenWrt',uptime:3600,modem:{state:'connected',operator:'Telstra',signal:80},wan_addresses:['198.51.100.2'],addresses:{},leases:[{name:'Server',address:'192.168.10.100',mac:'00:11:22:33:44:55'}],services:{dnsmasq:'active','router-firewall':'active'},settings:{start:'192.168.10.50',end:'192.168.10.200',lease_hours:12,dns:['1.1.1.1']},wifi:{available:false},ddns:{available:false},openvpn:{available:false},at_available:true,port_forwarding_available:true};
const injection=`<script>
const fixture=${JSON.stringify(fixture)};
let saved=0, state={available:true,revision:'one',rules:[],dmz:{enabled:false,destination_zone:'lan',destination_ip:''},unmanaged:[{name:'Existing camera',source_zone:'wan',external_port:'9000'}],source_zones:['wan','router_vpn'],destination_zones:['lan','hotspot'],limit:100};
window.confirm=()=>true;
window.addEventListener('error',e=>document.documentElement.dataset.pfError=e.message);
window.fetch=async(url,options={})=>{
 let data={};
 if(url==='/api/session')data={csrf:'test-token',username:'admin'};
 if(url==='/api/status')data=fixture;
 if(url==='/api/port-forwards'){
  if(options.method==='POST'){
   const input=JSON.parse(options.body);
   if(options.headers['X-CSRF-Token']!=='test-token'||input.revision!==state.revision)throw new Error('Bad save request');
   state={...state,rules:input.rules,dmz:input.dmz,revision:String(++saved)};data={port_forwarding:state,message:'Port forwarding saved and firewall reloaded.'};
  }else data=state;
 }
 return new Response(JSON.stringify(data),{status:200});
};
window.addEventListener('load',async()=>{
 try{
  const check=(condition,message)=>{if(!condition)throw new Error(message);};
  const wait=async condition=>{for(let i=0;i<40;i++){if(condition())return;await new Promise(resolve=>setTimeout(resolve,25));}throw new Error('Timed out waiting for async browser operation');};
  await new Promise(resolve=>setTimeout(resolve,100));
  check(!document.getElementById('port-forwarding-panel').hidden,'Feature visibility');
  await pfLoad();
  check(!pfDmz().enabled,'DMZ defaults off');
  document.getElementById('pf-dmz-enabled').value='true';document.getElementById('pf-dmz-ip').value='192.168.10.200';
  document.getElementById('pf-dmz-enabled').dispatchEvent(new Event('input'));
  check(pfDirty&&saved===0,'DMZ must be staged');
  document.getElementById('pf-add').click();
  document.getElementById('pf-name').value='<img src=x onerror=alert(1)>';
  document.getElementById('pf-preset').value='443';document.getElementById('pf-preset').dispatchEvent(new Event('change'));
  document.getElementById('pf-destination_ip').value='192.168.10.100';
  document.getElementById('pf-source_ip').value='203.0.113.0/24';
  document.getElementById('pf-reflection').value='true';
  document.getElementById('pf-form').requestSubmit();
  check(pfRules.length===1&&pfRules[0].external_port==='443'&&pfDirty,'Stage and preset');
  check(!document.querySelector('#pf-rules img'),'Rule name must be text');
  document.getElementById('pf-save').click();await new Promise(resolve=>setTimeout(resolve,50));
  check(saved===1&&!pfDirty&&state.rules[0].source_ip==='203.0.113.0/24'&&state.rules[0].reflection,'Save payload');
  check(state.dmz.enabled&&state.dmz.destination_ip==='192.168.10.200','DMZ save payload');
  document.querySelectorAll('#pf-rules button')[1].click();check(!pfRules[0].enabled&&pfDirty,'Disable');
  document.getElementById('pf-save').click();await new Promise(resolve=>setTimeout(resolve,50));
  document.querySelectorAll('#pf-rules button')[2].click();document.getElementById('pf-form').requestSubmit();
  check(pfRules.length===2&&pfRules[0].id!==pfRules[1].id,'Duplicate identity');
  document.querySelectorAll('#pf-rules button')[3].click();check(pfRules.length===1,'Delete');
  const transfer=new DataTransfer();transfer.items.add(new File([JSON.stringify({version:1,rules:[]})],'rules.json',{type:'application/json'}));
  document.getElementById('pf-import').files=transfer.files;document.getElementById('pf-import').dispatchEvent(new Event('change'));
  await wait(()=>pfRules.length===0);check(pfDirty,'Import staged replacement');
  check(saved===2,'Import must not apply automatically');
  check(pfDmz().enabled,'Legacy import must preserve DMZ');
  const second=new DataTransfer();second.items.add(new File([JSON.stringify({version:2,rules:[],dmz:{enabled:false,destination_zone:'hotspot',destination_ip:'192.168.20.100'}})],'dmz.json',{type:'application/json'}));
  document.getElementById('pf-import').files=second.files;document.getElementById('pf-import').dispatchEvent(new Event('change'));
  await wait(()=>!pfDmz().enabled);check(pfDmz().destination_zone==='hotspot'&&saved===2,'Version 2 DMZ import staging');
  check(document.getElementById('pf-unmanaged').textContent.includes('Existing camera'),'Unmanaged visibility');
  pfEdit();document.getElementById('pf-name').value='Test service';document.getElementById('pf-external_port').value='8000-8010';document.getElementById('pf-internal_port').value='9000-9010';document.getElementById('pf-destination_ip').value='192.168.10.100';document.getElementById('pf-form').requestSubmit();
  pfEdit(pfRules[0]);document.getElementById('port-forwarding-panel').scrollIntoView();
  check(!document.documentElement.dataset.pfError,'JavaScript error');
  check(document.documentElement.scrollWidth<=innerWidth,'Mobile overflow');
  document.documentElement.dataset.pfSmoke='pass';
 }catch(error){document.documentElement.dataset.pfSmoke='fail';document.documentElement.dataset.pfFailure=error.message;}
});
</script>`;
let html=fs.readFileSync('web/index.html','utf8').replace('href="/style.css"','href="style.css"').replace('src="/app.js"','src="app.js"').replace('src="/port-forwarding.js"','src="port-forwarding.js"');
html=html.replace('src="/dhcp-reservations.js"','src="dhcp-reservations.js"');
html=html.replace('<script src="app.js"',injection+'<script src="app.js"');fs.writeFileSync(path.join(target,'index.html'),html);
for(const [label,width,height]of [['desktop',1440,1300],['mobile',390,1800]]){
 const result=spawnSync('C:/Program Files/Google/Chrome/Application/chrome.exe',['--headless','--disable-gpu','--no-first-run','--no-default-browser-check','--user-data-dir='+path.join(target,'chrome-'+label),'--window-size='+width+','+height,'--virtual-time-budget=2500','--dump-dom','--screenshot='+path.resolve('logs/port-forwarding-'+label+'.png'),'file:///'+path.join(target,'index.html').replaceAll('\\','/')],{encoding:'utf8',windowsHide:true,timeout:30000,maxBuffer:2e6});
 if(result.error||!result.stdout.includes('data-pf-smoke="pass"')){fs.writeFileSync(path.join(target,'failure-'+label+'.txt'),String(result.stdout)+'\n'+String(result.stderr));throw new Error('Browser check failed: '+label+' '+(result.error?.message||''));}
 console.log('PASS '+label+': DMZ staging/save, legacy preservation, version 2 import, forwarding CRUD and responsive layout');
}
