const fs=require('node:fs'),path=require('node:path'),{spawnSync}=require('node:child_process');
const target=path.resolve('local/modbus-browser');fs.mkdirSync(target,{recursive:true});
for(const file of ['modbus.js','style.css'])fs.copyFileSync('web/'+file,path.join(target,file));
const assignmentPanel=fs.readFileSync('web/index.html','utf8').match(/<section id="serial-assignment-panel"[\s\S]*?<\/section>/)[0];
const panel=fs.readFileSync('web/index.html','utf8').match(/<section id="modbus-panel"[\s\S]*?<\/section>/)[0];
const fixture=`<script>
const el=id=>document.getElementById(id);let saves=0,last,assignmentLast;
const state={available:true,enabled:false,serial:'BOARD001',interval_minutes:1,upload_time:'14:55',retention_days:1,save_mode:'memory',usb_mount:'/mnt/modbus',max_storage_mb:64,debug:false,password_saved:true,state:'disabled',serial_port:{device:'/dev/ttyUSB0',baud:9600,parity:'none',data_bits:8,stop_bits:1,timeout_seconds:2},ftp:{host:'ftp.test',port:21,username:'meter',password:'',directory:'/',tls:false},devices:[{name:'<img src=x onerror=alert(1)>',id:1,data_mode:'little',registers:[{description:'Voltage',address:0,format:'FLOAT32',unit:'V',function:4}]}],files:[{id:'a'.repeat(32),name:'BOARD001_meter.csv',status:'pending',bytes:123}]};
async function api(route,data){if(route==='serial-assignment'){assignmentLast=data;return {serial_assignment:{available:true,mode:data.mode,device:data.device,tcp_baud:data.tcp_baud,tcp_port:data.tcp_port,tcp_running:true,modbus_running:false},message:'Switched'};}if(data===undefined)return state;if(route!=='modbus')throw Error('Wrong route');last=data;saves++;return {modbus:{...state,...data,ftp:{...data.ftp,password:''}},message:'Saved'};}
</script><script src="modbus.js"></script><script>
window.addEventListener('load',async()=>{try{
const check=(ok,message)=>{if(!ok)throw Error(message);};showModbus(state);
check(!el('modbus-panel').hidden&&el('modbus-ftp-host').value==='ftp.test','Load settings');
showSerialAssignment({available:true,mode:'modbus',device:'usb:067b:2303',tcp_baud:9600,tcp_port:5000,tcp_running:false,modbus_running:true});
check(el('serial-assignment-mode').value==='modbus','Assignment load');
el('serial-assignment-mode').value='tcp';el('serial-assignment-form').requestSubmit();await new Promise(r=>setTimeout(r,30));
check(assignmentLast.mode==='tcp'&&assignmentLast.tcp_baud===9600&&assignmentLast.tcp_port===5000,'Assignment submit');
check(!el('save-serial-assignment').disabled,'Assignment button restored');
check(!document.querySelector('img'),'Untrusted labels must remain text');
check(el('modbus-ftp-password').value===''&&el('modbus-password-help').textContent.includes('keep'),'Secret handling');
el('modbus-ftp-host').value='edited.test';showModbus({...state,ftp:{...state.ftp,host:'refreshed.test'}});
check(el('modbus-ftp-host').value==='edited.test','Refresh preserves edits');
check(el('modbus-files').querySelector('a').getAttribute('href')==='/api/modbus/files/'+'a'.repeat(32),'CSV export link');
el('modbus-add-device').click();let devices=el('modbus-devices').children;
check(devices.length===2,'Add device');devices[1].querySelector('[data-field=id]').value='0x39';
[...devices[1].querySelectorAll('button')].find(b=>b.textContent==='Add register').click();
check(devices[1].querySelectorAll('.modbus-register').length===1,'Add register');
el('modbus-enabled').value='true';el('modbus-ftp-password').value='new secret';el('modbus-form').requestSubmit();await new Promise(r=>setTimeout(r,30));
check(saves===1&&last.enabled===true&&last.ftp.port===21&&last.ftp.password==='new secret'&&last.devices[1].id==='0x39','Save');
check(last.devices[0].registers[0].function===4&&last.devices[0].data_mode==='little','Register configuration');
check(el('modbus-ftp-password').value===''&&!el('save-modbus').disabled,'Clear secret after save');
devices=el('modbus-devices').children;
[...devices[1].querySelectorAll('button')].find(b=>b.textContent==='Remove device').click();check(devices.length===1,'Remove device');
check(document.documentElement.scrollWidth<=innerWidth,'Layout overflow');
el('modbus-ftp-password').value='secret';el('dashboard').hidden=true;await new Promise(r=>setTimeout(r,20));
check(el('modbus-ftp-password').value===''&&!modbusPopulated,'Logout clears secret');
document.documentElement.dataset.smoke='pass';
}catch(error){document.documentElement.dataset.smoke='fail';document.documentElement.dataset.failure=error.message;}});
</script>`;
fs.writeFileSync(path.join(target,'index.html'),`<!doctype html><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="style.css"><div id="dashboard">${assignmentPanel}${panel}</div>${fixture}`);
for(const width of [1440,390]){
const result=spawnSync('C:/Program Files/Google/Chrome/Application/chrome.exe',['--headless','--disable-gpu','--no-sandbox','--no-first-run','--no-default-browser-check','--user-data-dir='+path.join(target,'chrome-'+width),'--window-size='+width+',1200','--virtual-time-budget=2000','--dump-dom','file:///'+path.join(target,'index.html').replaceAll('\\','/')],{encoding:'utf8',windowsHide:true,timeout:30000,maxBuffer:2e6});
if(result.error||!result.stdout.includes('data-smoke="pass"')){fs.writeFileSync(path.join(target,'failure.txt'),String(result.stdout)+String(result.stderr));throw Error('Modbus browser test failed: '+width);}
console.log('PASS '+width+': device/register editor, save, export, secret handling, refresh and logout');
}
