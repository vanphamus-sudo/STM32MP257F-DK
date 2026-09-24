// Development PC: requires the temporary SSH tunnel and headless Chrome on 9225.
const fs = require('node:fs');
const {execFileSync} = require('node:child_process');
(async () => {
  const tabs = await (await fetch('http://127.0.0.1:9225/json')).json();
  const tab = tabs.find(t => t.type === 'page' && t.url.startsWith('http://192.168.10.1'));
  if (!tab) throw new Error('Router browser tab not found');
  const socket = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen=resolve; socket.onerror=reject; });
  let sequence=0;
  const pending=new Map(), errors=[];
  socket.onmessage = event => {
    const message=JSON.parse(event.data);
    if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails.text);
    if (message.id && pending.has(message.id)) {
      const {resolve,reject}=pending.get(message.id); pending.delete(message.id);
      if(message.error) reject(new Error(JSON.stringify(message.error))); else resolve(message.result);
    }
  };
  const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}));});
  const evaluate=async expression=>{
    const result=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});
    if(result.exceptionDetails) throw new Error(result.exceptionDetails.text);
    return result.result.value;
  };
  await send('Runtime.enable');
  await send('Page.enable');
  const login=await evaluate('document.querySelector("#login-panel") !== null');
  if(!login) throw new Error('Login page did not render');
  fs.writeFileSync('logs/router-web-login.png',Buffer.from((await send('Page.captureScreenshot')).data,'base64'));
  const password=execFileSync('ssh',['-F','NUL','-o','UserKnownHostsFile=local/board-known-hosts','-o','HostKeyAlias=192.168.40.102','-o','StrictHostKeyChecking=yes','-o','BatchMode=yes','root@192.168.7.1','cat /var/lib/router-web/initial-password'],{encoding:'utf8'}).trim();
  await evaluate(`document.getElementById('password').value=${JSON.stringify(password)}; document.querySelector('#login-form button').click();`);
  const waitFor=async expression=>{
    for(let attempt=0;attempt<30;attempt++) {if(await evaluate(expression)) return; await new Promise(resolve=>setTimeout(resolve,300));}
    throw new Error('Browser check timed out: '+expression);
  };
  await waitFor("!document.getElementById('dashboard').hidden && document.getElementById('start').value !== ''");
  await waitFor("!document.getElementById('wifi-panel').hidden && document.getElementById('wifi-state').textContent === 'enabled'");
  await evaluate("document.getElementById('current-password').value='incorrect-password'; document.getElementById('save-account').click()");
  await waitFor("document.getElementById('account-message').textContent === 'Current password is incorrect.'");
  await evaluate("document.getElementById('current-password').value=''");
  await evaluate("document.getElementById('save').click()");
  await waitFor("document.getElementById('save-message').textContent.startsWith('Settings applied.')");
  fs.writeFileSync('logs/router-web-desktop.png',Buffer.from((await send('Page.captureScreenshot',{captureBeyondViewport:true})).data,'base64'));
  const desktop=await evaluate("({title:document.title,clients:document.getElementById('client-count').textContent,save:document.getElementById('save-message').textContent,overflow:document.documentElement.scrollWidth > innerWidth})");
  await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  const mobileOverflow=await evaluate('document.documentElement.scrollWidth > innerWidth');
  fs.writeFileSync('logs/router-web-mobile.png',Buffer.from((await send('Page.captureScreenshot',{captureBeyondViewport:true})).data,'base64'));
  if(errors.length || desktop.overflow || mobileOverflow) throw new Error(JSON.stringify({errors,desktop,mobileOverflow}));
  console.log(JSON.stringify({result:'PASS: browser login, dashboard, settings save, desktop and mobile layout',desktop,mobileOverflow,errors}));
  await send('Browser.close');
  socket.close();
})().catch(error=>{console.error(error.message);process.exit(1);});
