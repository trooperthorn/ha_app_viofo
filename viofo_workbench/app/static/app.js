'use strict';
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state, clips = [], selected = new Set(), segments = [], playing = null, gps = [], currentPage = 'overview';
let noticeTimer;
let routeMap, routeLine, routeMarker, routeTiles;
const bytes = n => (n / 1024 ** 3).toFixed(2) + ' GB';
function notice(text, error=false) { $('notice').textContent=text; $('notice').className=error?'error':''; $('notice').hidden=false; clearTimeout(noticeTimer); noticeTimer=setTimeout(()=>$('notice').hidden=true,12000); }
async function api(path, method='GET', body) {
  const options={method,headers:{'X-Viofo-Request':'1'}};
  if(body instanceof FormData) options.body=body;
  else if(body!==undefined) {options.body=JSON.stringify(body);options.headers['Content-Type']='application/json';}
  const r=await fetch('api/'+path,options); const data=await r.json();
  if(!r.ok) throw new Error(data.error || `Request failed: ${r.status}`);
  return data;
}
async function attempt(fn) {try{return await fn();}catch(e){notice(e.message,true);}}
function page(id) {
  currentPage=id;
  document.querySelectorAll('.page').forEach(el=>el.hidden=el.id!==id);
  document.querySelectorAll('nav button').forEach(el=>el.classList.toggle('active',el.dataset.page===id));
  $('pageTitle').textContent=({overview:'Overview',library:'Recordings',editor:'Editor',queue:'Activity',settings:'Settings',diagnostics:'Diagnostics'})[id];
  if(id==='editor') renderSelection();
}
document.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>page(b.dataset.page));
document.querySelectorAll('[data-go]').forEach(b=>b.onclick=()=>page(b.dataset.go));
function cameraStatus(c) {const o=c.observation;return !c.configured?'Not configured':!o.observed_at?'Not checked':o.stale?'Observation expired':o.online?'Reachable':'Unavailable';}
async function refresh(full=false) {
  state=await api('status');
  $('connectionStatus').textContent='Service connected · logging: '+state.options.log_level;
  $('clipCount').textContent=state.library.count;
  $('storageSummary').textContent=bytes(state.library.bytes)+' of '+state.options.max_storage_gb+' GB quota';
  $('cameraCards').innerHTML=state.cameras.map(c=>`<article class="camera-card"><div class="row"><span class="model">${esc(c.model)}</span><span class="badge ${c.observation.online&&!c.observation.stale?'green':''}">${esc(cameraStatus(c))}</span></div><div class="camera-icon">◉ ━ ◉</div><h3>${esc(c.name)}</h3><p>${c.configured?esc(c.address):'Add the station-mode IP address to connect.'}</p><div class="muted">${c.observation.firmware?'Firmware: '+esc(c.observation.firmware):'Firmware not yet read'}<br>${c.observation.observed_at?'Observed '+esc(new Date(c.observation.observed_at*1000).toLocaleString()):'No device observations'}</div><div class="actions"><button data-cam="${c.id}" data-action="inspect" ${!c.configured?'disabled':''}>Inspect</button><button data-cam="${c.id}" data-action="files" ${!c.configured?'disabled':''}>Browse files</button><button data-cam="${c.id}" data-action="live" ${!c.configured?'disabled':''}>Live view</button><button data-cam="${c.id}" data-action="sync" ${!c.configured?'disabled':''}>Sync</button><button data-config="1">Configure</button></div></article>`).join('');
  $('cameraCards').querySelectorAll('[data-action]').forEach(b=>b.onclick=()=>attempt(()=>deviceAction(b.dataset.cam,b.dataset.action)));
  $('cameraCards').querySelectorAll('[data-config]').forEach(b=>b.onclick=()=>page('settings'));
  renderJobs();
  $('runtime').textContent=JSON.stringify({version:state.version,media_tools:state.media_tools,library:state.library,uptime_seconds:Math.round(state.uptime),hardware_validation:'pending'},null,2);
  if(full) {
    renderForms();
    Object.entries(state.options).forEach(([k,v])=>{let el=$('preferences').elements[k];if(el){if(el.type==='checkbox')el.checked=v;else el.value=v;}});
    clips=await api('library'); renderLibrary();
  }
}
function renderForms() {
  $('cameraForms').innerHTML=state.cameras.map(c=>`<form class="camera-form" data-id="${c.id}"><h3>${esc(c.model)}</h3><div class="form-grid"><label>Name<input name="name" value="${esc(c.name)}" maxlength="80"></label><label>Camera IP / HTTP address<input name="address" value="${esc(c.address)}" placeholder="192.168.1.100"></label><label>Attached views<select name="channels">${['F','FR','FI','FRI'].map(v=>`<option ${v===c.channels?'selected':''}>${v}</option>`).join('')}</select></label><div><label><input name="auto_sync" type="checkbox" ${c.auto_sync?'checked':''}> Automatically sync when reachable</label><br><label><input name="writes" type="checkbox" ${c.writes?'checked':''}> Enable model-specific camera controls</label></div><button class="primary">Save camera</button></div><hr></form>`).join('');
  $('cameraForms').querySelectorAll('form').forEach(f=>f.onsubmit=e=>{e.preventDefault();attempt(async()=>{await api('cameras/'+f.dataset.id,'PUT',{name:f.elements.name.value,address:f.elements.address.value,channels:f.elements.channels.value,auto_sync:f.elements.auto_sync.checked,writes:f.elements.writes.checked});notice('Camera profile saved');await refresh();});});
}
async function deviceAction(cid,action) {
  const c=state.cameras.find(c=>c.id===cid);
  if(action==='sync'){const data=await api(`cameras/${cid}/sync`,'POST',{});notice(`${data.queued.length} downloads queued; newest segments deferred`);await refresh();return;}
  $('dialogTitle').textContent=c.name;
  $('dialogBody').innerHTML='<p>Contacting camera…</p>'; $('deviceDialog').showModal();
  if(action==='live'){$('dialogBody').innerHTML=`<p>Root RTSP preview · 5 fps · no audio. Per-lens endpoints await validation.</p><img alt="Live camera preview" src="api/live/${cid}">`;return;}
  if(action==='files') {
    const list=await api(`cameras/${cid}/files`,'POST',{});
    $('dialogBody').innerHTML=`<p>${list.length} recordings on the camera</p><button id="downloadRemote">Download selected</button><div>${list.map((f,i)=>`<div class="segment"><label><input type="checkbox" data-remote="${i}"> ${esc(f.name)} · ${esc(f.category)} · ${(f.size/1024**2).toFixed(1)} MB</label></div>`).join('')}</div>`;
    $('downloadRemote').onclick=()=>attempt(async()=>{const paths=[...document.querySelectorAll('[data-remote]:checked')].map(el=>list[Number(el.dataset.remote)].path);await api(`cameras/${cid}/download`,'POST',{paths});notice('Downloads queued');$('deviceDialog').close();await refresh();});return;
  }
  const data=await api(`cameras/${cid}/inspect`,'POST',{});
  $('dialogBody').innerHTML=`<p>Firmware: ${esc(data.firmware)}</p><p>Recording: ${data.recording===1?'On':data.recording===0?'Off':'Unknown'}</p><div class="toolbar"><button id="startRecording" ${!c.writes?'disabled':''}>Start recording</button><button id="stopRecording" ${!c.writes?'disabled':''}>Stop recording</button></div><p class="muted">Settings below come from the model command database. Writes require successful read-back; camera firmware may reject changes while recording.</p><div>${data.settings.map(s=>`<div class="setting-row"><label>${esc(s.label)}<small class="muted"> (${s.command})</small></label><select id="setting${s.command}" ${!s.writable?'disabled':''}><option value="">${s.current===null?'Not reported':'Current: '+esc(s.current)}</option>${Object.entries(s.options).map(([v,t])=>`<option value="${esc(v)}" ${String(s.current)===v?'selected':''}>${esc(t)}</option>`).join('')}</select><button data-setting="${s.command}" ${!s.writable||!c.writes?'disabled':''}>Apply</button></div>`).join('')}</div>`;
  async function write(command,value){await api(`cameras/${cid}/settings`,'POST',{command,value});notice('Camera confirmed setting by read-back');}
  $('startRecording').onclick=()=>attempt(()=>write(2001,1));
  $('stopRecording').onclick=()=>{if(confirm('Stop this camera’s recording?'))attempt(()=>write(2001,0));};
  $('dialogBody').querySelectorAll('[data-setting]').forEach(b=>b.onclick=()=>attempt(()=>write(Number(b.dataset.setting),Number($('setting'+b.dataset.setting).value))));
  await refresh();
}
$('closeDialog').onclick=()=>{$('dialogBody').innerHTML='';$('deviceDialog').close();};
$('deviceDialog').addEventListener('close',()=>$('dialogBody').innerHTML='');
function renderLibrary() {
  let list=clips.filter(c=>(!$('filterCamera').value||c.camera===$('filterCamera').value)&&(!$('filterCategory').value||c.category===$('filterCategory').value)&&c.name.toLowerCase().includes($('search').value.toLowerCase()));
  if($('filterDate').value){const d=$('filterDate').value.replaceAll('-','');list=list.filter(c=>c.name.replaceAll('_','').startsWith(d));}
  if($('sort').value==='asc')list=[...list].reverse();
  $('recordings').innerHTML=list.length?`<table><thead><tr><th>Select</th><th>Recording</th><th>View</th><th>Category</th><th>Size</th><th>Actions</th></tr></thead><tbody>${list.map(c=>`<tr><td><input type="checkbox" aria-label="Select ${esc(c.name)}" data-select="${c.id}" ${selected.has(c.id)?'checked':''}></td><td class="name">${esc(c.name)}<div class="muted">${esc(c.camera)} · ${c.metadata.duration?c.metadata.duration.toFixed(1)+' sec':esc(c.metadata.status||'Pending analysis')}</div></td><td>${esc(c.channel)}</td><td>${esc(c.category)}</td><td>${(c.size/1024**2).toFixed(1)} MB</td><td><button data-play="${c.id}">Review</button> <button data-protect="${c.id}">${c.protected?'Unprotect':'Protect'}</button> <a href="api/clips/${c.id}/download">Original</a> <button data-delete="${c.id}">Delete local</button></td></tr>`).join('')}</tbody></table>`:'<div class="empty"><h3>No recordings yet</h3><p>Import original footage or download from a connected camera.<br>No demonstration footage is mixed into your library.</p></div>';
  $('recordings').querySelectorAll('[data-select]').forEach(el=>el.onchange=()=>{el.checked?selected.add(el.dataset.select):selected.delete(el.dataset.select);$('selectedCount').textContent=selected.size+' selected';});
  $('recordings').querySelectorAll('[data-play]').forEach(el=>el.onclick=()=>attempt(()=>play(el.dataset.play)));
  $('recordings').querySelectorAll('[data-protect]').forEach(el=>el.onclick=()=>attempt(async()=>{let c=clips.find(c=>c.id===el.dataset.protect);await api(`clips/${c.id}/protect`,'POST',{protected:!c.protected});await refresh(true);}));
  $('recordings').querySelectorAll('[data-delete]').forEach(el=>el.onclick=()=>{if(confirm('Delete this local recording? The camera copy is not changed.'))attempt(async()=>{await api(`clips/${el.dataset.delete}/delete`,'POST',{confirm:el.dataset.delete});selected.delete(el.dataset.delete);await refresh(true);});});
}
['search','filterCamera','filterCategory','filterDate','sort'].forEach(id=>$(id).oninput=renderLibrary);
$('importFiles').onchange=()=>attempt(async()=>{const data=new FormData();for(const f of $('importFiles').files)data.append('files',f);notice('Importing recordings…');const result=await api('import?camera='+$('importCamera').value,'POST',data);notice(`${result.imported.length} files imported; analysis queued`);$('importFiles').value='';await refresh(true);});
async function play(id, autoplay=false) {
  playing=clips.find(c=>c.id===id); const views=clips.filter(c=>c.camera===playing.camera&&c.group_key===playing.group_key).slice(0,3);
  $('playerPanel').hidden=false;$('playingTitle').textContent=playing.name;
  if(playing.metadata.image){$('videos').innerHTML=`<img src="api/clips/${id}/media" alt="Dashcam photograph" style="max-width:100%">`;return;}
  $('videos').innerHTML=views.map(c=>`<div class="video-frame"><video controls playsinline preload="metadata" data-id="${c.id}" src="api/clips/${c.id}/media" ${c.id!==id?'muted':''}></video><span class="badge">${esc(c.channel)}</span></div>`).join('');
  const videos=[...$('videos').querySelectorAll('video')];const lead=videos.find(v=>v.dataset.id===id)||videos[0];
  lead.ontimeupdate=()=>{for(const v of videos)if(v!==lead&&Math.abs(v.currentTime-lead.currentTime)>.3)v.currentTime=lead.currentTime;updateGPS(lead.currentTime);};
  lead.onplay=()=>videos.filter(v=>v!==lead).forEach(v=>v.play().catch(()=>{}));lead.onpause=()=>videos.forEach(v=>{if(v!==lead)v.pause();});
  lead.onended=()=>{const next=clips.filter(c=>c.camera===playing.camera&&c.channel===playing.channel&&c.name>playing.name).sort((a,b)=>a.name.localeCompare(b.name))[0];if(next)attempt(()=>play(next.id,true));};
  videos.forEach(v=>{let drag;v.onpointerdown=e=>{if(Number($('zoom').value)>1){drag={x:e.clientX,y:e.clientY};v.setPointerCapture(e.pointerId);}};v.onpointermove=e=>{if(drag)v.style.transform=`translate(${e.clientX-drag.x}px,${e.clientY-drag.y}px) scale(${$('zoom').value})`;};v.onpointerup=()=>drag=null;v.onerror=()=>notice('Browser cannot decode this recording. Use “Create browser-compatible copy”.',true);});
  const track=await api(`clips/${id}/gps`);gps=track.points;
  $('gpsStatus').textContent=gps.length?`${gps.length} GPS points · route plot without external map tiles · ${track.timing}`:'No supported embedded GPS data found. This does not prove the camera recorded none.';
  $('gpxLink').href=`api/clips/${id}/gpx`;drawRoute();
  drawTelemetry(await api(`clips/${id}/telemetry`));
  $('playerPanel').scrollIntoView({behavior:'smooth',block:'start'});
  if(autoplay)await lead.play().catch(e=>notice(e.message,true));
}
function leadVideo(){return [...$('videos').querySelectorAll('video')].find(v=>v.dataset.id===playing?.id)||$('videos').querySelector('video');}
function drawRoute(){
  if(!routeMap){routeMap=L.map('route',{attributionControl:true}).setView([0,0],2);routeMap.attributionControl.setPrefix('');}
  if(routeLine)routeMap.removeLayer(routeLine);if(routeMarker)routeMap.removeLayer(routeMarker);
  routeMap.invalidateSize();
  if(!gps.length)return;
  routeLine=L.polyline(gps.map(p=>[p.lat,p.lon]),{color:'#53d9b1',weight:4}).addTo(routeMap);
  routeMarker=L.circleMarker([gps[0].lat,gps[0].lon],{radius:7,color:'#e9bd70',fillOpacity:1}).addTo(routeMap);
  routeMap.fitBounds(routeLine.getBounds(),{padding:[20,20],maxZoom:16});
}
$('mapTiles').onchange=()=>{
  if(!routeMap)drawRoute();
  if($('mapTiles').checked){routeTiles=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a>'}).addTo(routeMap);}
  else if(routeTiles){routeMap.removeLayer(routeTiles);routeTiles=null;}
};
function updateGPS(seconds){if(!gps.length)return;const p=gps.reduce((a,b)=>Math.abs(b.seconds-seconds)<Math.abs(a.seconds-seconds)?b:a);if(routeMarker)routeMarker.setLatLng([p.lat,p.lon]);const mph=$('speedMph').checked;$('speed').textContent=(p.speed_kmh*(mph?.621371:1)).toFixed(1)+(mph?' mph':' km/h');}
function drawTelemetry(data){$('telemetryStatus').textContent=data.points.length?`Imported telemetry · ${data.units}`:'Embedded G-sensor decoding awaits calibration; optional CSV import is available.';if(!data.points.length){$('telemetry').innerHTML='';return;}const end=Math.max(...data.points.map(p=>p.seconds),1),max=Math.max(...data.points.flatMap(p=>[Math.abs(p.x),Math.abs(p.y),Math.abs(p.z)]),1);$('telemetry').innerHTML=['x','y','z'].map((axis,i)=>`<polyline fill="none" stroke="${['#53d9b1','#e9bd70','#8aacf3'][i]}" stroke-width="2" points="${data.points.map(p=>(20+p.seconds/end*560)+','+(130-p[axis]/max*110)).join(' ')}"/>`).join('');}
$('telemetryFile').onchange=()=>attempt(async()=>{if(!playing)throw Error('Select a recording');const file=$('telemetryFile').files[0];drawTelemetry(await api(`clips/${playing.id}/telemetry`,'POST',{csv:await file.text(),units:'g'}));});
$('playAll').onclick=()=>{const lead=leadVideo();if(lead)lead.paused?lead.play().catch(e=>notice(e.message,true)):lead.pause();};
$('closePlayer').onclick=()=>{$('videos').innerHTML='';$('playerPanel').hidden=true;playing=null;};
$('backFrame').onclick=()=>{const v=leadVideo();if(v){v.pause();v.currentTime=Math.max(0,v.currentTime-1/30);}};
$('nextFrame').onclick=()=>{const v=leadVideo();if(v){v.pause();v.currentTime+=1/30;}};
$('rate').onchange=()=>$('videos').querySelectorAll('video').forEach(v=>v.playbackRate=Number($('rate').value));
$('zoom').oninput=()=>$('videos').querySelectorAll('video').forEach(v=>v.style.transform=`scale(${$('zoom').value})`);
$('fullscreen').onclick=()=>attempt(()=>$('videos').requestFullscreen());
$('screenshot').onclick=()=>attempt(async()=>{if(!playing)throw Error('Select a recording');await api(`clips/${playing.id}/snapshot`,'POST',{seconds:leadVideo()?.currentTime||0});notice('Screenshot queued; download it from Activity');});
$('compatibility').onclick=()=>attempt(async()=>{await api(`clips/${playing.id}/proxy`,'POST',{});notice('Compatible copy queued in Activity');});
function renderSelection(){$('editSelection').textContent=[...selected].map(id=>clips.find(c=>c.id===id)?.name).join(' + ')||'No recordings selected';}
$('selectedEditor').onclick=()=>{if(selected.size<1||selected.size>3){notice('Select one to three recordings',true);return;}page('editor');};
function drawSegments(){$('segments').innerHTML=segments.map((s,i)=>`<div class="segment row"><span>Segment ${i+1} · ${s.start}–${s.end} sec · ${s.clips.length} view(s)</span><button data-remove="${i}">Remove</button></div>`).join('');$('segments').querySelectorAll('[data-remove]').forEach(b=>b.onclick=()=>{segments.splice(Number(b.dataset.remove),1);drawSegments();});}
$('addSegment').onclick=()=>{const start=Number($('trimStart').value),end=Number($('trimEnd').value);if(!selected.size||selected.size>3||end<=start||start<0){notice('Choose 1–3 views and a valid time range',true);return;}segments.push({clips:[...selected],start,end});drawSegments();};
$('render').onclick=()=>attempt(async()=>{if(!segments.length)throw Error('Add a segment first');await api('exports','POST',{segments,height:Number($('resolution').value),layout:$('layout').value,title:$('titleText').value});notice('Export queued');page('queue');await refresh();});
function renderJobs(){$('jobs').innerHTML=state.jobs.length?state.jobs.map(j=>`<div class="job"><div class="row"><strong>${esc(j.kind)} <span class="badge">${esc(j.state)}</span></strong><span class="muted">${new Date(j.created*1000).toLocaleString()}</span></div><progress value="${j.progress}" max="1"></progress><div class="error">${esc(j.error)}</div><div class="actions">${['queued','running','paused'].includes(j.state)?`<button data-job="${j.id}" data-action="cancel">Cancel</button>`:''}${['queued','running'].includes(j.state)?`<button data-job="${j.id}" data-action="pause">Pause</button><button data-job="${j.id}" data-action="prioritize">Prioritize</button>`:''}${['paused','failed','cancelled'].includes(j.state)?`<button data-job="${j.id}" data-action="retry">${j.state==='paused'?'Resume':'Retry'}</button>`:''}${j.state==='done'&&j.result?`<a class="button" href="api/exports/${j.id}">Download result</a>`:''}</div></div>`).join(''):'<div class="empty">No tasks yet. Imports, downloads and exports appear here.</div>';$('jobs').querySelectorAll('[data-job]').forEach(b=>b.onclick=()=>attempt(async()=>{await api('jobs/'+b.dataset.job,'POST',{action:b.dataset.action});await refresh();}));}
$('preferences').onsubmit=e=>{e.preventDefault();const form=$('preferences');attempt(async()=>{await api('preferences','PUT',{max_storage_gb:Number(form.elements.max_storage_gb.value),retention_days:Number(form.elements.retention_days.value),sync_interval_seconds:Number(form.elements.sync_interval_seconds.value),log_level:form.elements.log_level.value,retention_enabled:form.elements.retention_enabled.checked});notice('Preferences saved');await refresh();});};
$('refresh').onclick=()=>attempt(()=>refresh(true));
attempt(()=>refresh(true));
setInterval(()=>attempt(async()=>{await refresh();if(currentPage==='library'&&!document.hidden){clips=await api('library');renderLibrary();}}),7000);
