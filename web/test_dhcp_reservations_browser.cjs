// Isolated browser fixture; never contacts or changes the router.
const fs=require('node:fs'),path=require('node:path'),{spawnSync}=require('node:child_process');
const target=path.resolve('local/dhcp-bindings-browser');fs.mkdirSync(target,{recursive:true});
for(const name of ['app.js','port-forwarding.js','dhcp-reservations.js','style.css'])fs.copyFileSync(path.resolve('web',name),path.join(target,name));
const fixture={hostname:'OpenWrt',uptime:3600,modem:{state:'connected',operator:'Telstra',signal:80},wan_addresses:['198.51.100.2'],addresses:{},leases:[],services:{dnsmasq:'active','router-firewall':'active'},settings:{start:'192.168.10.50',end:'192.168.10.200',lease_hours:12,dns:['1.1.1.1']},wifi:{available:false},ddns:{available:false},openvpn:{available:false},at_available:true,port_forwarding_available:false,dhcp_reservations_available:true};
const injection=`<script>
const fixture=${JSON.stringify(fixture)};
let saves=0, rejectSave=false, state={available:true,revision:'one',bindings:[],leases:[{hostname:'server',mac:'00:11:22:33:44:55',ip:'192.168.10.100'}],unmanaged:[{hostname:'Camera',mac:'02:aa:bb:cc:dd:ee',ip:'192.168.10.200'}],lan_enabled:true,limit:100};
window.confirm=()=>true;window.addEventListener('error',e=>document.documentElement.dataset.drError=e.message);
window.fetch=async(url,options={})=>{
 let data={},code=200;
 if(url==='/api/session')data={csrf:'test-token',username:'admin'};
 if(url==='/api/status')data=fixture;
 if(url==='/api/dhcp-reservations'){
  if(options.method==='POST'){
   const input=JSON.parse(options.body);
   if(input.revision!==state.revision||options.headers['X-CSRF-Token']!=='test-token')throw new Error('Bad request');
   if(rejectSave){data={error:'DHCP settings changed. Reload bindings before saving.'};code=409;}
   else{state={...state,bindings:input.bindings,revision:String(++saves)};data={reservations:state,message:'DHCP bindings saved.'};}
  }else data=state;
 }
 return new Response(JSON.stringify(data),{status:code});
};
window.addEventListener('load',async()=>{
 try{
  const check=(ok,message)=>{if(!ok)throw new Error(message);};
  await new Promise(resolve=>setTimeout(resolve,100));
  check(!document.getElementById('dhcp-bindings').hidden,'Feature visibility');await drLoad();
  document.getElementById('dr-add').click();document.getElementById('dr-client').value='0';document.getElementById('dr-client').dispatchEvent(new Event('change'));
  check(document.getElementById('dr-mac').value==='00:11:22:33:44:55','Lease prefill');
  document.getElementById('dr-ip').value='192.168.10.20';document.getElementById('dr-form').requestSubmit();
  check(drDirty&&drItems.length===1&&saves===0,'Staging');
  document.getElementById('dr-save').click();await new Promise(resolve=>setTimeout(resolve,50));
  check(saves===1&&!drDirty&&state.bindings[0].ip==='192.168.10.20','Save payload');
  document.querySelector('#dr-bindings button').click();document.getElementById('dr-ip').value='192.168.10.21';document.getElementById('dr-form').requestSubmit();
  rejectSave=true;document.getElementById('dr-save').click();await new Promise(resolve=>setTimeout(resolve,50));
  check(drDirty&&drItems[0].ip==='192.168.10.21'&&document.getElementById('dr-message').textContent.includes('retained'),'Failure retains edits');
  rejectSave=false;await drLoad();check(drItems[0].ip==='192.168.10.20'&&!drDirty,'Reload');
  check(document.getElementById('dr-unmanaged').textContent.includes('Camera'),'Unmanaged visibility');
  document.querySelectorAll('#dr-bindings button')[1].click();document.getElementById('dr-save').click();await new Promise(resolve=>setTimeout(resolve,50));
  check(saves===2&&state.bindings.length===0,'Remove');
  state.lan_enabled=false;await drLoad();check(!document.getElementById('dr-dhcp-note').hidden,'Disabled DHCP notice');
  drEdit();document.getElementById('dhcp-bindings').scrollIntoView();
  check(document.documentElement.scrollWidth<=innerWidth,'Overflow');check(!document.documentElement.dataset.drError,'JavaScript error');
  document.documentElement.dataset.drSmoke='pass';
 }catch(error){document.documentElement.dataset.drSmoke='fail';document.documentElement.dataset.drFailure=error.message;}
});
</script>`;
let html=fs.readFileSync('web/index.html','utf8').replace('href="/style.css"','href="style.css"');
for(const name of ['app.js','port-forwarding.js','dhcp-reservations.js'])html=html.replace('src="/'+name+'"','src="'+name+'"');
html=html.replace('<script src="app.js"',injection+'<script src="app.js"');fs.writeFileSync(path.join(target,'index.html'),html);
for(const[label,width,height]of[['desktop',1440,1300],['mobile',390,1800]]){
 const result=spawnSync('C:/Program Files/Google/Chrome/Application/chrome.exe',['--headless','--disable-gpu','--no-first-run','--no-default-browser-check','--user-data-dir='+path.join(target,'chrome-'+label),'--window-size='+width+','+height,'--virtual-time-budget=2500','--dump-dom','--screenshot='+path.resolve('logs/dhcp-bindings-'+label+'.png'),'file:///'+path.join(target,'index.html').replaceAll('\\','/')],{encoding:'utf8',windowsHide:true,timeout:30000,maxBuffer:2e6});
 if(result.error||!result.stdout.includes('data-dr-smoke="pass"')){fs.writeFileSync(path.join(target,'failure-'+label+'.txt'),String(result.stdout)+'\n'+String(result.stderr));throw new Error('DHCP browser check failed: '+label);}
 console.log('PASS '+label+': lease prefill, add/edit/remove, staging, CSRF payload, stale save recovery and layout');
}
