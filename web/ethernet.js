'use strict';
let ethState=null, ethBusy=false;
function showEthernet(available){
  el('ethernet-panel').hidden=!available;
  if(available&&!ethState&&!ethBusy)ethLoad();
}
function ethHelp(){
  const mode=el('eth-mode').value;
  el('eth-vlans').hidden=mode!=='both';
  el('eth-help').textContent=mode==='both'?
    'Requires a managed switch: tag both selected VLANs on the port to this board. Assign client ports to LAN and the upstream modem/router port to WAN. No untagged LAN on this trunk.':
    mode==='wan'?'Connect Ethernet to your upstream router. Ethernet LAN access ends after reboot; use the enabled Wi-Fi hotspot or USB management. The hotspot settings address remains http://192.168.10.1:8081.':
    'Connect local clients to Ethernet. LTE remains the Internet uplink.';
}
async function ethLoad(){
  if(!csrf||ethBusy)return;
  ethBusy=true;el('eth-fields').disabled=true;
  el('eth-message').textContent='Loading Ethernet settings...';
  try{
    ethState=await api('ethernet');
    el('eth-mode').value=ethState.mode;
    el('eth-lan').value=ethState.lan_vlan;el('eth-wan').value=ethState.wan_vlan;
    ethHelp();el('eth-message').textContent='Saved configuration for '+ethState.device+'. Changes take effect at the next reboot.';
  }catch(error){el('eth-message').textContent=error.message;}
  finally{ethBusy=false;el('eth-fields').disabled=!ethState;}
}
el('eth-mode').addEventListener('change',ethHelp);
el('eth-reload').addEventListener('click',ethLoad);
navigation.querySelector('a[href="#ethernet-panel"]').addEventListener('click',ethLoad);
el('eth-form').addEventListener('submit',async event=>{
  event.preventDefault();if(!ethState||ethBusy)return;
  ethBusy=true;el('eth-fields').disabled=true;
  try{
    const result=await api('ethernet',{mode:el('eth-mode').value,lan_vlan:Number(el('eth-lan').value),wan_vlan:Number(el('eth-wan').value),revision:ethState.revision});
    ethState=result.ethernet;el('eth-message').textContent=result.message;
  }catch(error){el('eth-message').textContent=error.message;}
  finally{ethBusy=false;el('eth-fields').disabled=false;}
});
new MutationObserver(()=>{if(el('dashboard').hidden){ethState=null;el('eth-fields').disabled=true;}}).observe(el('dashboard'),{attributes:true,attributeFilter:['hidden']});
ethHelp();
