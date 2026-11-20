'use strict';
(() => {
  const node = id => document.getElementById(id), popup = document.body.dataset.logWindow === 'true';
  let busy = false, allowed = true, visible = popup, loaded = false, savedSettings = null, configBusy = false;
  const dashboard = node('dashboard'), output = node('logs-output');
  const signedIn = () => popup || (dashboard && !dashboard.hidden);
  async function request(path, data) {
    const options = {credentials:'same-origin', cache:'no-store', headers:{}};
    if (data !== undefined) {
      const session = await request('/api/session');
      options.method = 'POST'; options.headers = {'Content-Type':'application/json', 'X-CSRF-Token':session.csrf};
      options.body = JSON.stringify(data);
    }
    const response = await fetch(path, options), value = await response.json();
    if (!response.ok) { const error = new Error(value.error || 'Log request failed.'); error.status=response.status; throw error; }
    return value;
  }
  async function update(manual=false) {
    if (busy || !allowed || !signedIn() || (!manual && (!visible || document.hidden || !node('logs-live').checked))) return;
    busy = true; node('logs-refresh').disabled = true;
    try {
      const query = new URLSearchParams({category:node('logs-category').value, source:node('logs-source').value,
        limit:node('logs-lines').value, search:node('logs-search').value});
      const data = await request('/api/logs?' + query);
      if (!signedIn() || !allowed) return;
      const text = data.lines.join('\n');
      if (output.textContent !== text) {
        output.textContent = text;
        if (node('logs-autoscroll').checked) output.scrollTop = output.scrollHeight;
      }
      node('logs-note').textContent = data.note;
      node('logs-status').textContent = `${node('logs-live').checked ? 'Live' : 'Paused'} · ${data.lines.length} lines · ${new Date(data.updated_at*1000).toLocaleTimeString()}${data.truncated ? ' · older lines omitted' : ''}`;
    } catch (error) {
      node('logs-status').textContent = error.status === 401 ? 'Sign in on the router settings page, then refresh this window.' : error.message;
      if (error.status === 401) { allowed=false; output.textContent=''; }
    } finally { busy=false; node('logs-refresh').disabled=false; }
  }
  node('logs-refresh').addEventListener('click',()=>{allowed=true;update(true);});
  for (const id of ['logs-category','logs-source','logs-lines']) node(id).addEventListener('change',()=>update(true));
  let searchTimer;
  node('logs-search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>update(true),300);});
  node('logs-live').addEventListener('change',()=>{
    if (node('logs-live').checked) update(true); else node('logs-status').textContent='Paused; displayed records are retained.';
  });
  node('logs-download').addEventListener('click',()=>{
    const url=URL.createObjectURL(new Blob([output.textContent+'\n'],{type:'text/plain;charset=utf-8'}));
    const link=document.createElement('a');link.href=url;link.download='router-'+node('logs-category').value+'-'+new Date().toISOString().replace(/[:.]/g,'-')+'.log';link.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  node('logs-window')?.addEventListener('click',()=>{
    const category=node('logs-category').value;
    const opened=window.open('/logs.html#'+category,'router-live-'+category,'width=1000,height=700');
    if (!opened) node('logs-status').textContent='Allow pop-ups for this router to open the live log window.';
  });
  if (popup) {
    const category=location.hash.slice(1);
    if (['message','application','kernel','audit'].includes(category)) node('logs-category').value=category;
    document.title='Router live log'; update(true);
  } else {
    if (typeof IntersectionObserver === 'function') {
      new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;if(visible)update();}).observe(node('logs-viewer'));
    } else visible=true;
    const localForm=node('logs-local-form'), remoteForm=node('logs-remote-form');
    function fill(settings, which) {
      savedSettings=settings;
      if (!which || which==='local') {
        node('logs-buffer-kib').value=settings.local.buffer_kib; node('logs-file-kib').value=settings.local.file_kib;
        node('logs-file-enabled').checked=settings.local.file_enabled; node('logs-storage').value=settings.local.storage;
      }
      if (!which || which==='remote') {
        node('logs-remote-enabled').checked=settings.remote.enabled;node('logs-host').value=settings.remote.host;
        node('logs-port').value=settings.remote.port;node('logs-protocol').value=settings.remote.protocol;
      }
      node('logs-local-save').disabled=false;node('logs-remote-save').disabled=false;
    }
    async function loadSettings() {
      if (loaded || configBusy || !signedIn()) return;
      configBusy=true;
      try { const value=await request('/api/logs/settings');if(signedIn()){fill(value);loaded=true;} }
      catch(error){node('logs-settings-message').textContent=error.message;}
      finally{configBusy=false;}
    }
    async function save(event, which) {
      event.preventDefault(); if (!savedSettings || configBusy) return;
      const data=structuredClone(savedSettings); delete data.local.file_supported;
      if (which==='local') data.local={buffer_kib:Number(node('logs-buffer-kib').value),file_enabled:node('logs-file-enabled').checked,
        storage:node('logs-storage').value,file_kib:Number(node('logs-file-kib').value)};
      else data.remote={enabled:node('logs-remote-enabled').checked,host:node('logs-host').value.trim(),
        port:Number(node('logs-port').value),protocol:node('logs-protocol').value};
      configBusy=true;node('logs-'+which+'-save').disabled=true;
      const message=node(which==='local'?'logs-settings-message':'logs-remote-message');message.textContent='Saving logging settings…';
      try{const result=await request('/api/logs/settings',data);fill(result.settings,which);message.textContent=result.message;await update(true);}
      catch(error){message.textContent=error.message;}
      finally{configBusy=false;node('logs-'+which+'-save').disabled=false;}
    }
    localForm.addEventListener('submit',event=>save(event,'local')); remoteForm.addEventListener('submit',event=>save(event,'remote'));
    new MutationObserver(()=>{
      if (!signedIn()) {loaded=false;allowed=false;savedSettings=null;output.textContent='';}
      else {allowed=true;loadSettings();update();}
    }).observe(dashboard,{attributes:true,attributeFilter:['hidden']});
    loadSettings();
  }
  const interval=setInterval(()=>update(),2000);
  window.addEventListener('pagehide',()=>clearInterval(interval),{once:true});
})();
