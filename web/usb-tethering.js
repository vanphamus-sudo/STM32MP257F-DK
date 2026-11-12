'use strict';
let usbState=null, usbBusy=false;
function showUsbTethering(available){
  el('usb-panel').hidden=!available;
  if(available&&!usbState&&!usbBusy)usbLoad();
}
async function usbLoad(){
  if(!csrf||usbBusy)return;
  usbBusy=true;el('usb-fields').disabled=true;
  try{
    usbState=await api('usb-tethering');
    el('usb-enabled').value=String(usbState.enabled);
    el('usb-message').textContent=usbState.available?
      'Saved configuration for '+usbState.device+'. Changes take effect at the next reboot.':
      'USB management is unavailable. Hold USER1 for eight seconds, then release to recover it.';
  }catch(error){el('usb-message').textContent=error.message;}
  finally{usbBusy=false;el('usb-fields').disabled=!usbState||!usbState.available;}
}
el('usb-reload').addEventListener('click',usbLoad);
navigation.querySelector('a[href="#usb-panel"]').addEventListener('click',usbLoad);
el('usb-form').addEventListener('submit',async event=>{
  event.preventDefault();if(!usbState||usbBusy)return;
  usbBusy=true;el('usb-fields').disabled=true;
  try{
    const result=await api('usb-tethering',{enabled:el('usb-enabled').value==='true',revision:usbState.revision});
    usbState=result.usb;el('usb-message').textContent=result.message;
  }catch(error){el('usb-message').textContent=error.message;}
  finally{usbBusy=false;el('usb-fields').disabled=!usbState||!usbState.available;}
});
new MutationObserver(()=>{if(el('dashboard').hidden){usbState=null;el('usb-fields').disabled=true;}}).observe(el('dashboard'),{attributes:true,attributeFilter:['hidden']});
