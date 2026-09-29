import {esc,formatTime,pitchName,bisect,spanAt,overlappingSources,activeNotes,pitchBounds,safeAsset} from './logic.js';
const $=id=>document.getElementById(id);
const COLORS=['#577f68','#b78a49','#6483ab','#a37183','#5d9a96','#9a875d','#7b77a2','#ae704d'];
const presetInputs=[
 {id:'original',label:'Full mix',sources:['original'],description:'The original recording'},
 {id:'vocals',label:'Vocals',sources:['vocals'],description:'Separated vocal source'},
 {id:'bass',label:'Bass',sources:['bass'],description:'Separated bass source'},
 {id:'other',label:'Other instruments',sources:['other'],description:'May contain several instruments'},
 {id:'instrumental',label:'Instrumental',sources:['drums','bass','other'],description:'Everything except vocals'}
];
const state={live:Boolean(window.LAB_KEY),job:null,session:null,base:'',selected:new Set(),muted:new Set(),solo:null,audition:null,
 analyses:new Map(),knownInputs:new Set(),media:new Map(),scores:[],master:null,playing:false,playGeneration:0,loadingGeneration:0,
 inspect:null,view:'scores',time:0,custom:[],page:{ledger:0,token:0},ledgerRows:[],tokenRows:[],lastPaint:0,lastSync:0,rollStart:-1,
 poll:null,renderSignature:'',loadedSignature:'',uploading:false};
function notice(message){$('notice').textContent=message;$('notice').hidden=!message;}
async function api(path,options={}){
 const response=await fetch(path,{...options,headers:{'X-Lab-Key':window.LAB_KEY||'',...options.headers},cache:'no-store'});
 if(!response.ok){let msg;try{const j=await response.json();msg=typeof j.detail==='string'?j.detail:JSON.stringify(j.detail);}catch{msg=await response.text();}throw Error(msg||`Request failed (${response.status})`);}
 return response.json();
}
const asset=path=>{if(!safeAsset(path))throw Error('Invalid artifact path');return state.base+path.split('/').map(encodeURIComponent).join('/');};
const target=id=>state.session?.targets.find(t=>t.id===id);
function targetsForListening(){return (state.session?.targets||[]).filter(t=>t.audio&&state.selected.has(t.id)&&!state.muted.has(t.id)&&(!state.solo||state.solo===t.id));}
function renderPresets(){
 $('presets').innerHTML=presetInputs.map(p=>`<label class="input-option"><input type="checkbox" data-preset="${p.id}" ${['original','vocals','bass','other'].includes(p.id)?'checked':''}><span><strong>${esc(p.label)}</strong><small>${esc(p.description)}</small></span></label>`).join('');
 $('mix-sources').innerHTML=['vocals','drums','bass','other'].map(s=>`<label><input type="checkbox" value="${s}"> ${s}</label>`).join('');
 updatePassCount();
}
function chosenTargets(){return [...presetInputs.filter(p=>$(`presets`).querySelector(`[data-preset="${p.id}"]`).checked),...state.custom].map(({label,sources})=>({label,sources}));}
function updatePassCount(){const n=new Set(chosenTargets().map(t=>[...t.sources].sort().join('-'))).size;$('pass-count').textContent=n+' transcription pass'+(n===1?'':'es');$('run').disabled=!state.job||state.job.status!=='uploaded'||state.uploading||!n||n>8;}
function renderCustom(){
 $('custom-targets').innerHTML=state.custom.map((t,i)=>`<div class="custom-row"><span>${esc(t.label)} <small>(${esc(t.sources.join(' + '))})</small></span><button data-remove="${i}" aria-label="Remove ${esc(t.label)}">×</button></div>`).join('');updatePassCount();
}
function newSession(){
 pause();clearTimeout(state.poll);state.loadingGeneration++;state.job=null;state.session=null;state.analyses.clear();state.knownInputs.clear();disposeAudio();state.scores=[];state.renderSignature='';state.loadedSignature='';state.inspect=null;state.selected.clear();state.muted.clear();state.solo=null;state.audition=null;
 $('workspace').hidden=true;$('job-panel').hidden=true;$('setup').hidden=false;document.querySelector('.intro').hidden=false;$('file').value='';$('upload-title').textContent='Drop a song or choose a file';$('upload-sub').textContent='MP3, WAV, FLAC, M4A and more · up to 200 MB / 12 min';$('clip-start').value=0;$('clip-end').value='';notice('');history.replaceState(null,'',location.pathname);updatePassCount();refreshHistory();
}
async function upload(file){
 if(!file||state.uploading)return;
 if(file.size>200*1024**2){notice('Upload limit is 200 MB. Compress or trim the recording.');return;}
 newSession();state.uploading=true;$('upload-progress').hidden=false;$('upload-progress').value=0;$('upload-title').textContent='Uploading '+file.name;$('file').disabled=true;notice('');
 try{
  const result=await new Promise((resolve,reject)=>{const xhr=new XMLHttpRequest();xhr.open('POST','api/upload');xhr.setRequestHeader('X-Lab-Key',window.LAB_KEY);xhr.setRequestHeader('X-Filename',encodeURIComponent(file.name));xhr.setRequestHeader('Content-Type','application/octet-stream');xhr.upload.onprogress=e=>{if(e.lengthComputable)$('upload-progress').value=e.loaded/e.total*100;};xhr.onerror=()=>reject(Error('Upload connection lost. Reconnect the runtime and try again.'));xhr.onload=()=>{let data;try{data=JSON.parse(xhr.responseText);}catch{return reject(Error('Server returned an invalid response. Reconnect and retry.'));}xhr.status>=200&&xhr.status<300?resolve(data):reject(Error(data.detail||'Upload failed'));};xhr.send(file);});
  state.job=result;showUpload(result);history.replaceState(null,'','#'+result.id);refreshHistory();
 }catch(e){notice(e.message);$('upload-title').textContent='Upload failed — choose a file to retry';}
 finally{state.uploading=false;$('file').disabled=false;$('upload-progress').hidden=true;updatePassCount();}
}
function showUpload(job){$('upload-title').textContent=job.title;$('upload-sub').textContent=`${formatTime(job.source.duration,true)} · ${job.source.channels} channels · ${job.source.sampleRate} Hz`;$('clip-end').value=job.source.duration.toFixed(3);$('clip-end').max=job.source.duration;$('clip-start').max=job.source.duration-1;}
async function startJob(retry=false){
 if(!state.job)return;
 const config=retry?state.job.config:{start:Number($('clip-start').value),end:Number($('clip-end').value),targets:chosenTargets()};
 if(!Number.isFinite(config.start)||!Number.isFinite(config.end)||config.start<0||config.end-config.start<1||config.end>state.job.source.duration+.01){notice('Choose a valid excerpt of at least 1 second.');return;}
 $('run').disabled=true;notice('');
 try{const job=await api(`api/jobs/${state.job.id}/run`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(config)});state.job=job;$('setup').hidden=true;document.querySelector('.intro').hidden=true;await pollJob();}
 catch(e){notice(e.message);updatePassCount();}
}
async function refreshHistory(){if(!state.live)return;try{const data=await api('api/status');$('history').innerHTML='<option value="">Choose…</option>'+data.sessions.map(s=>`<option value="${esc(s.id)}">${esc(s.title)} · ${esc(s.status)}</option>`).join('');}catch{/* A reconnect message is shown by the job poll. */}}
async function loadJob(id){
 newSession();try{const job=await api(`api/jobs/${id}`);state.job=job;showUpload(job);history.replaceState(null,'','#'+id);if(job.status==='uploaded'){updatePassCount();return;}$('setup').hidden=true;document.querySelector('.intro').hidden=true;await pollJob();}catch(e){notice(e.message);}
}
async function pollJob(){
 clearTimeout(state.poll);if(!state.job)return;const id=state.job.id;
 try{
  const job=await api(`api/jobs/${id}`);if(state.job?.id!==id)return;state.job=job;
  $('job-panel').hidden=false;$('job-stage').textContent=job.stage;$('job-detail').textContent=job.progress?`${job.progress.stage}${job.progress.window?' · window '+job.progress.window+'/'+job.progress.windows:''}${job.progress.tokens?' · '+job.progress.tokens+' tokens':''}`:'Completed inputs remain available if another input fails. Processing runs one input at a time.';
  $('job-targets').innerHTML=(job.targets||[]).map(t=>`<span class="job-chip" data-status="${esc(t.status)}">${esc(t.label)} · ${esc(t.status)}</span>`).join('');
  $('job-error').textContent=job.error||(job.targets||[]).filter(t=>t.error).map(t=>t.label+': '+t.error).join('\n');
  const running=['queued','running','cancelling'].includes(job.status);$('cancel').hidden=!running;$('cancel').disabled=job.status==='cancelling';$('retry').hidden=running||!['partial','failed','cancelled','interrupted'].includes(job.status);
  if(job.audio?.original){state.base=`results/${id}/`;await hydrate(job);}
  if(state.job?.id!==id)return;
  if(!running){$('bundle').hidden=!job.audio?.original;$('bundle').href=`api/jobs/${id}/bundle`;$('bundle').download='Stem-Score-Lab.zip';refreshHistory();}
  else state.poll=setTimeout(pollJob,1800);
  $('connection').textContent='Colab / local session';
 }catch(e){if(state.job?.id!==id)return;$('connection').textContent='Disconnected';notice('Connection interrupted. Keep the Colab runtime connected. Retrying automatically. '+e.message);state.poll=setTimeout(pollJob,6000);}
}
async function hydrate(session){
 const generation=state.loadingGeneration;
 const first=!state.session;state.session=session;
 for(const t of session.targets||[]){
  if(t.audio&&!state.knownInputs.has(t.id)){state.knownInputs.add(t.id);state.selected.add(t.id);}
  if(t.analysis&&!state.analyses.has(t.id)){
   try{const d=await api(asset(t.analysis));if(generation!==state.loadingGeneration)return;state.analyses.set(t.id,d);}catch(e){notice('An input finished, but its analysis could not be loaded: '+e.message);}
  }
 }
 if(generation!==state.loadingGeneration)return;
 $('workspace').hidden=false;$('new-session').hidden=!state.live;$('song-title').textContent=session.title;
 $('duration').textContent=formatTime(session.duration);$('seek').max=session.duration;
 $('session-caption').textContent=`${formatTime(session.duration,true)} excerpt · source ${formatTime(session.config?.start||0)}–${formatTime(session.config?.end||session.duration)} · ${(session.targets||[]).length} inputs · ${session.model?.precision||'processing'} · SheetSage2`;
 if(!state.master&&session.audio?.original){state.master=getMedia('master',session.audio.original);state.master.addEventListener('ended',()=>{pause();seek(session.duration);});state.master.addEventListener('loadedmetadata',()=>{$('play').disabled=false;});$('play').disabled=state.master.readyState<1;}
 const signature=JSON.stringify(session.targets.map(t=>[t.id,t.status,t.analysis,t.noteCount]));
 if(signature!==state.renderSignature){
  state.renderSignature=signature;
  if(!state.inspect||!state.analyses.has(state.inspect))state.inspect=[...state.analyses.keys()][0]||null;
  renderTracks();renderScores();renderInspection();
 }
 if(first)paint(0,true);
}
function getMedia(key,path){
 if(!state.media.has(key)){
  const audio=new Audio(asset(path));audio.preload='metadata';audio.preservesPitch=true;audio.playbackRate=Number($('speed').value);audio.volume=0;
  audio.addEventListener('error',()=>{if(state.playing)notice('An audio file could not be read. Pause and retry, or download the session.');});state.media.set(key,audio);
 }
 return state.media.get(key);
}
function disposeAudio(){for(const a of state.media.values()){a.pause();a.removeAttribute('src');a.load();}state.media.clear();state.master=null;state.time=0;}
function audioPlan(){
 const plan=new Map();if(!state.master)return plan;
 plan.set(state.master,0);const mode=$('hear').value;const volume=Number($('volume').value);
 if(state.audition){const path=state.session.audio?.[state.audition];if(path)plan.set(getMedia('audition:'+state.audition,path),volume);return plan;}
 if(mode==='original'){plan.set(state.master,volume);return plan;}
 const tracks=targetsForListening();const level=volume/Math.max(1,tracks.length)/(mode==='overlay'?2:1);
 for(const t of tracks){if(['stems','overlay'].includes(mode)&&t.audio)plan.set(getMedia('input:'+t.id,t.audio),level);if(['melody','overlay'].includes(mode)&&t.synth)plan.set(getMedia('synth:'+t.id,t.synth),level);}
 return plan;
}
function updateListeningCaption(){
 const tracks=targetsForListening();$('mix-warning').hidden=!overlappingSources(tracks)||$('hear').value==='original'||Boolean(state.audition);
 $('listen-caption').textContent=state.audition?`Solo audio: ${state.audition} · same excerpt clock`:$('hear').value==='original'?'Original excerpt · score selections do not change this audio':$('hear').value==='melody'?`${tracks.filter(t=>t.synth).length} predicted melodies · simple tone synthesis · fixed velocity`:$('hear').value==='overlay'?'Selected recordings + predicted melody tones · summed at reduced gain':`${tracks.length} selected inputs · solo an input for direct comparison`;
}
async function changeListening(){
 updateListeningCaption();const wasPlaying=state.playing;const time=state.master?.currentTime||state.time;pause();seek(time);if(wasPlaying)await play();
}
async function readyAudio(audio){if(audio.readyState>=2)return;await new Promise((resolve,reject)=>{const done=()=>{cleanup();resolve();};const fail=()=>{cleanup();reject(Error('Audio could not load. Check that the runtime is still connected.'));};const timer=setTimeout(fail,45000);const cleanup=()=>{clearTimeout(timer);audio.removeEventListener('loadeddata',done);audio.removeEventListener('error',fail);};audio.addEventListener('loadeddata',done,{once:true});audio.addEventListener('error',fail,{once:true});audio.load();});}
async function play(){
 if(!state.master)return;
 const gen=++state.playGeneration;const start=state.time>=state.session.duration-.03?0:state.time;$('play').disabled=true;$('play').textContent='…';notice('');
 try{
  const plan=audioPlan();await Promise.all([...plan.keys()].map(readyAudio));if(gen!==state.playGeneration)return;
  for(const [a,gain] of plan){a.volume=gain;a.currentTime=Math.min(start,Math.max(0,a.duration-.001));a.playbackRate=Number($('speed').value);}
  // Issue every play call in one task. The silent master is the recording clock.
  await Promise.all([...plan.keys()].map(a=>a.play()));
  if(gen!==state.playGeneration){if(!state.playing)for(const a of plan.keys())a.pause();return;}
  state.playing=true;$('play').textContent='Ⅱ';$('play').setAttribute('aria-label','Pause');$('play').disabled=false;updateListeningCaption();
 }catch(e){if(gen===state.playGeneration){pause();notice(e.message+' Press Play to try again.');}}
}
function pause(){state.playGeneration++;state.media.forEach(a=>a.pause());state.playing=false;$('play').textContent='▶';$('play').setAttribute('aria-label','Play');$('play').disabled=!state.master;}
function seek(time){if(!state.session)return;const t=Math.max(0,Math.min(state.session.duration,Number(time)||0));state.media.forEach(a=>{if(a.readyState>=1)a.currentTime=Math.min(t,Math.max(0,a.duration-.001));});paint(t,true);}
function renderTracks(){
 $('track-list').innerHTML=state.session.targets.map((t,i)=>`<div class="track-control" style="--track:${COLORS[i%COLORS.length]}"><label><input type="checkbox" data-show="${esc(t.id)}" ${state.selected.has(t.id)?'checked':''} ${!t.audio?'disabled':''}> ${esc(t.label)}</label><button data-mute="${esc(t.id)}" class="${state.muted.has(t.id)?'on':''}" aria-pressed="${state.muted.has(t.id)}">Mute</button><button data-solo="${esc(t.id)}" class="${state.solo===t.id?'on':''}" aria-pressed="${state.solo===t.id}">Solo</button><button data-inspect="${esc(t.id)}" ${!state.analyses.has(t.id)?'disabled':''}>Inspect ↗</button><div class="track-meta">${esc(t.sources.join(' + '))} · ${t.noteCount??'—'} notes · ${esc(t.status)}</div></div>`).join('');
 $('inspect-select').innerHTML=state.session.targets.filter(t=>state.analyses.has(t.id)).map(t=>`<option value="${esc(t.id)}">${esc(t.label)}</option>`).join('');if(state.inspect)$('inspect-select').value=state.inspect;
 $('stem-buttons').innerHTML=Object.keys(state.session.audio||{}).filter(x=>x!=='original').map(s=>`<button class="small-button" data-audition="${esc(s)}">${esc(s)}</button>`).join('')+'<button class="small-button" data-audition="">Return to selected inputs</button>';
 $('stem-audition').hidden=Object.keys(state.session.audio||{}).length<=1;updateListeningCaption();
}
function renderScores(){
 state.scores=[];const tracks=state.session.targets.filter(t=>state.selected.has(t.id));$('selection-count').textContent=tracks.length+' inputs visible';
 $('score-stack').innerHTML=tracks.length?tracks.map(t=>{
  const d=state.analyses.get(t.id),color=COLORS[state.session.targets.indexOf(t)%COLORS.length];
  return `<section class="panel score-card" data-track="${esc(t.id)}" style="--track:${color}"><div class="panel-head"><h2>${esc(t.label)}</h2><div><button class="small-button" data-svg="${esc(t.id)}">SVG ↓</button> <span class="badge" data-now="${esc(t.id)}">—</span> <button class="small-button" data-inspect="${esc(t.id)}" ${!d?'disabled':''}>Inspect ↗</button></div></div>${d?.warnings?.length?`<div class="score-warning">${esc(d.warnings[0])}</div>`:''}<div class="score-body">${d?.parts?.length?d.parts.map((part,i)=>`<div class="score-part"><div class="voice-label">${part.voice==='Vocal'?'Predicted vocal voice':'Predicted instrumental voice'}</div><div class="score-scroll"><div class="score" id="score-${esc(t.id)}-${i}"></div></div></div>`).join(''):`<div class="score-empty">${esc(t.error||(d?.notes?.length?'No synchronized staff could be built. Raw notes and exports are available under Inspect.':t.status==='queued'||t.status==='running'?'Waiting for this transcription…':'No melody score was emitted for this input.'))}</div>`}</div>${d?.warnings?.length>1?`<details><summary>${d.warnings.length-1} more diagnostics</summary><div>${d.warnings.slice(1).map(esc).join('<br>')}</div></details>`:''}</section>`;
 }).join(''):'<div class="score-empty">Select an input above to show its score.</div>';
 for(const t of tracks){const d=state.analyses.get(t.id);(d?.parts||[]).forEach((part,i)=>{
  const element=$(`score-${t.id}-${i}`);
  try{
   const visual=ABCJS.renderAbc(element,part.abc,{responsive:'resize',staffwidth:1050,add_classes:true,paddingtop:3,paddingbottom:10,paddingleft:12,paddingright:12,format:{titlefont:'Georgia 0',staffsep:30,measurenb:4},clickListener:note=>{const e=part.timeline.find(e=>e.char>=note.startChar&&e.char<note.endChar);if(e)seek(e.start);}})[0];
   const events=part.timeline.map(e=>({...e,elements:(visual.getElementFromChar(e.char)?.abselem?.elemset||[]).filter(Boolean)}));
   element.dataset.events=events.length;element.dataset.mapped=events.filter(e=>e.elements.length).length;
   state.scores.push({id:t.id,element,events,active:-2,scroller:element.closest('.score-scroll')});
  }catch(e){element.textContent='Score rendering failed. Raw ABC remains available in Exports. '+e.message;}
 });}
 paint(state.time,true);
}
function showView(view){state.view=view;document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.view===view)));$('scores-view').hidden=view!=='scores';$('analysis-view').hidden=view!=='analysis';if(view==='analysis')renderInspection();else renderScores();}
function inspect(id){if(!state.analyses.has(id))return;state.inspect=id;state.page={ledger:0,token:0};$('inspect-select').value=id;showView('analysis');}
function renderInspection(){
 const d=state.analyses.get(state.inspect);if(!d){$('metrics').innerHTML='<p class="hint">Analysis appears as inputs finish.</p>';return;}
 $('metrics').innerHTML=[['note','NOTE'],['chord','CHORD'],['key','KEY'],['section','SECTION'],['meter','METER'],['bpm','BPM*'],['bar','BAR / BEAT'],['rms','RMS dBFS*']].map(([id,label])=>`<div class="metric"><span>${label}</span><b id="metric-${id}">—</b></div>`).join('');
 $('diagnostics').innerHTML=`<p><b>${d.notes.length} notes · ${d.pitchCounts.length} distinct pitches</b><br>${d.notes.filter(n=>n[3]===0).length} vocal / ${d.notes.filter(n=>n[3]===1).length} instrumental labels</p>`+d.warnings.map(w=>`<p>${esc(w)}</p>`).join('');
 const r=d.result;$('run-info').textContent=JSON.stringify({model:state.session.model,precision:r.dtype,inferenceSeconds:r.elapsed_seconds,peakGpuMiB:r.peak_gpu_mib,windows:r.windows?.length,prompts:r.prompts,preset:r.preset,pitchCounts:d.pitchCounts.map(([p,n])=>[pitchName(p),n])},null,2);
 const t=target(state.inspect);$('downloads').innerHTML=(t.files||[]).filter(safeAsset).map(path=>`<a download href="${esc(asset(path))}">${esc(path.slice(t.id.length+1))} ↓</a>`).join('');
 state.rollStart=-1;renderOverview();renderLedger();renderTokens();paint(state.time,true);
}
const svgText=(x,y,text,extra='')=>`<text x="${x}" y="${y}" ${extra}>${esc(text)}</text>`;
function renderOverview(){
 const d=state.analyses.get(state.inspect);if(!d||state.view!=='analysis')return;
 const W=Math.max(400,$('overview').clientWidth-20),H=204,L=87,R=12,w=W-L-R,dur=state.session.duration,x=t=>L+t/dur*w;
 let s=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Waveform, sections, key, chord, beats and derived tempo">`;
 const step=dur>180?30:dur>60?10:5;for(let t=0;t<=dur;t+=step){s+=`<path d="M${x(t)} 17V197" stroke="#e1e7da"/>`+svgText(x(t),12,formatTime(t),'text-anchor="middle"');}
 [[43,'WAVEFORM'],[77,'STRUCTURE'],[99,'KEY'],[121,'CHORD'],[146,'BEATS'],[183,'TEMPO*']].forEach(([y,l])=>s+=svgText(2,y,l));
 const peak=Math.max(...d.waveform,.001);s+=`<path d="${d.waveform.map((v,i)=>`M${(L+i/Math.max(1,d.waveform.length-1)*w).toFixed(2)} ${(42-v/peak*18).toFixed(2)}v${(v/peak*36).toFixed(2)}`).join(' ')}" stroke="#86a18b"/>`;
 for(const [rows,y,color] of [[d.sections,64,'#dce6d1'],[d.keys,86,'#e9e0c9'],[d.chords,108,'#eed6bb']]){let last=-100;for(const [a,b,label] of rows){s+=`<rect x="${x(a)}" y="${y}" width="${Math.max(.5,x(b)-x(a))}" height="18" fill="${color}" stroke="#fff"><title>${esc(label)} · ${a.toFixed(3)}–${b.toFixed(3)} s</title></rect>`;if(x(a)>last+70&&x(b)-x(a)>24){s+=svgText(x(a)+3,y+12,label);last=x(a);}}}
 for(const b of d.beats)s+=`<path d="M${x(b[0])} 132v${b[1]===1?16:8}" stroke="${b[1]===1?'#8c6940':'#c0aa8e'}"/>`;
 if(d.tempo.length){const vals=d.tempo.map(x=>x[1]),lo=Math.min(...vals),hi=Math.max(...vals);s+=`<path d="${d.tempo.map(([t,v],i)=>(i?'L':'M')+x(t)+','+(194-(v-lo)/(hi-lo||1)*31)).join(' ')}" fill="none" stroke="#7091b0"/>`+svgText(W-4,165,lo.toFixed(1)+'–'+hi.toFixed(1)+' BPM','text-anchor="end"');}else s+=svgText(L,183,'No beat intervals available');
 s+=`<path id="overview-cursor" class="cursor" d="M${L} 18V200"/></svg>`;$('overview').innerHTML=s;
 $('overview').onclick=e=>{const rect=$('overview').querySelector('svg').getBoundingClientRect();seek(((e.clientX-rect.left)/rect.width*W-L)/w*dur);};state.overviewWidth=w;
}
function renderRoll(time,force){
 const d=state.analyses.get(state.inspect);if(!d||state.view!=='analysis')return;
 const size=Math.min(Number($('roll-window').value),state.session.duration),start=Math.min(Math.floor(time/(size*.75))*size*.75,Math.max(0,state.session.duration-size));if(!force&&state.rollStart===start)return;state.rollStart=start;
 const W=Math.max(400,$('roll').clientWidth-20),H=204,L=45,w=W-L-10,[low,high]=pitchBounds(d.notes),row=169/(high-low+1),x=t=>L+(t-start)/size*w,y=p=>24+(high-p)*row;
 state.rollWidth=w;state.rollSize=size;
 let s=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Raw melody notes, orange vocal and green instrumental"><defs><clipPath id="roll-clip"><rect x="${L}" y="22" width="${w}" height="174"/></clipPath></defs>`;
 for(let p=low;p<=high;p++){s+=`<rect x="${L}" y="${y(p)}" width="${w}" height="${row}" fill="${[1,3,6,8,10].includes(p%12)?'#edf0e6':'#fbfcf6'}"/>`;if(p%12===0||p===low||p===high)s+=svgText(1,y(p)+Math.min(row,10),pitchName(p));}
 const step=size>60?20:size>16?5:2;for(let t=Math.ceil(start/step)*step;t<=start+size;t+=step)s+=svgText(x(t),13,formatTime(t),'text-anchor="middle"');
 s+='<g clip-path="url(#roll-clip)">';for(const b of d.beats.filter(b=>b[0]>=start&&b[0]<=start+size))s+=`<path d="M${x(b[0])} 22V196" stroke="${b[1]===1?'#c4d0be':'#e1e7db'}"/>`;
 for(const n of d.notes.filter(n=>n[1]>start&&n[0]<start+size)){s+=`<rect data-time="${n[0]}" data-end="${n[1]}" x="${x(n[0])}" y="${y(n[2])+.3}" width="${Math.max(.7,(n[1]-n[0])/size*w)}" height="${Math.max(1,row-.8)}" rx="1" fill="${n[3]===0?'#b97836':'#668777'}"><title>${pitchName(n[2])} · ${n[0].toFixed(3)}–${n[1].toFixed(3)} s · ${n[3]===0?'vocal':'instrumental'} label</title></rect>`;}
 s+=`</g><path id="roll-cursor" class="cursor" d="M${L} 20V198"/></svg>`;$('roll').innerHTML=s;
 $('roll').onclick=e=>{const n=e.target.closest('[data-time]');if(n){seek(Number(n.dataset.time));return;}const r=$('roll').querySelector('svg').getBoundingClientRect();seek(start+((e.clientX-r.left)/r.width*W-L)/w*size);};
}
function renderLedger(){
 const d=state.analyses.get(state.inspect);if(!d)return;const type=$('ledger-type').value;let head,rows;
 if(type==='notes'){head=['Start','End','Pitch','Voice'];rows=d.notes.map(n=>({time:n[0],cells:[n[0].toFixed(3),n[1].toFixed(3),pitchName(n[2])+' / '+n[2],n[3]===0?'Vocal':'Instrumental']}));}
 else if(type==='events'){head=['Time','Subbeat','Emitted values'];rows=d.events.map(e=>({time:e.time,cells:[e.time.toFixed(3),e.global_subbeat,JSON.stringify(e.values)]}));}
 else if(type==='beats'){head=['Time','Beat','Meter'];rows=d.beats.map(b=>({time:b[0],cells:[b[0].toFixed(3),b[1],b[2]+'/'+b[3]]}));}
 else if(type==='rhythm'){head=['Time','Rhythm'];rows=(d.rhythm||[]).map(r=>({time:r[0],cells:[r[0].toFixed(3),JSON.stringify(r[1])]}));}
 else if(type==='measures'){head=['Bar','Start','End','Notated quarters'];rows=(d.playback?.measures||[]).map(m=>({time:m.start,cells:[m.index+1,m.start.toFixed(3),m.end.toFixed(3),((m.score_end-m.score_start)*4).toFixed(2)]}));}
 else{head=['Start','End','Label'];rows=d[type].map(r=>({time:r[0],cells:[r[0].toFixed(3),r[1].toFixed(3),r[2]]}));}
 const q=$('ledger-search').value.toLowerCase();rows=rows.filter(r=>r.cells.join(' ').toLowerCase().includes(q));state.ledgerRows=rows;
 state.page.ledger=Math.max(0,Math.min(state.page.ledger,Math.ceil(rows.length/200)-1));const start=state.page.ledger*200;
 $('ledger-head').innerHTML='<tr>'+head.map(x=>'<th>'+esc(x)+'</th>').join('')+'</tr>';
 $('ledger-body').innerHTML=rows.slice(start,start+200).map(r=>`<tr data-time="${r.time}">${r.cells.map(c=>'<td>'+esc(c)+'</td>').join('')}</tr>`).join('');
 $('ledger-count').textContent=rows.length?`${start+1}–${Math.min(start+200,rows.length)} / ${rows.length} rows`:'No matching rows';$('ledger-prev').disabled=!start;$('ledger-next').disabled=start+200>=rows.length;
}
function renderTokens(){
 const d=state.analyses.get(state.inspect);if(!d)return;const q=$('token-search').value.toLowerCase();const rows=d.tokens.filter(r=>r.join(' ').toLowerCase().includes(q));state.tokenRows=rows;
 state.page.token=Math.max(0,Math.min(state.page.token,Math.ceil(rows.length/200)-1));const start=state.page.token*200;
 $('token-body').innerHTML=rows.slice(start,start+200).map(r=>`<tr ${r[4]!==null?`data-time="${r[4]}"`:''}>${[r[0],r[1],r[2],r[3],r[4]===null?'—':r[4].toFixed(3)].map(c=>'<td>'+esc(c)+'</td>').join('')}</tr>`).join('');
 $('token-count').textContent=rows.length?`${start+1}–${Math.min(start+200,rows.length)} / ${rows.length} tokens`:'No matching tokens';$('token-prev').disabled=!start;$('token-next').disabled=start+200>=rows.length;
}
function paint(time,force=false){
 if(!state.session)return;state.time=time;$('elapsed').textContent=formatTime(time,true);$('seek').value=time;$('seek').setAttribute('aria-valuetext',formatTime(time,true));
 for(const score of state.scores){let i=bisect(score.events,time,e=>e.start);if(i>=0&&time>=score.events[i].end)i=-1;
  if(i!==score.active||force){score.element.querySelectorAll('.active-note').forEach(e=>e.classList.remove('active-note'));const e=score.events[i];if(e&&!e.rest)e.elements.forEach(el=>el.classList.add('active-note'));score.active=i;score.element.dataset.currentEvent=i;
   if(e?.elements.length&&$('follow').checked&&state.view==='scores'){const box=e.elements[0].getBoundingClientRect(),outer=score.scroller.getBoundingClientRect();if(box.top<outer.top+14||box.bottom>outer.bottom-20)score.scroller.scrollTop+=box.top-outer.top-35;}
  }
 }
 document.querySelectorAll('[data-now]').forEach(el=>{const d=state.analyses.get(el.dataset.now);const notes=d?activeNotes(d.notes,time):[];el.textContent=notes.length?[...new Set(notes.map(n=>pitchName(n[2])))].join(' + '):'Rest';});
 if(state.view!=='analysis')return;const d=state.analyses.get(state.inspect);if(!d)return;
 const notes=activeNotes(d.notes,time),b=d.beats[bisect(d.beats,time)],tempo=d.tempo[bisect(d.tempo,time)],bar=bisect(d.playback?.measures||[],time,m=>m.start);const rms=d.rms[Math.min(d.rms.length-1,Math.floor(time/state.session.duration*d.rms.length))];
 const values={note:notes.length?[...new Set(notes.map(n=>pitchName(n[2])))].join(' + '):'Rest',chord:spanAt(d.chords,time)?.[2]||'—',key:spanAt(d.keys,time)?.[2]||'—',section:spanAt(d.sections,time)?.[2]||'—',meter:b?b[2]+'/'+b[3]:'—',bpm:tempo?tempo[1].toFixed(1):'—',bar:bar>=0?(bar+1)+' / '+(b?.[1]||'—'):'—',rms:rms>0?(20*Math.log10(rms)).toFixed(1):'−∞'};
 for(const [k,v] of Object.entries(values)){const el=$('metric-'+k);if(el)el.textContent=v;}
 const ei=bisect(d.events,time,e=>e.time);if(force||ei!==state.lastEvent){$('event-json').textContent=ei>=0?JSON.stringify(d.events[ei],null,2):'No event emitted yet.';$('event-index').textContent=ei>=0?'#'+ei:'';state.lastEvent=ei;}
 const cursor=$('overview-cursor');if(cursor)cursor.setAttribute('transform',`translate(${time/state.session.duration*state.overviewWidth} 0)`);
 renderRoll(time,force);const roll=$('roll-cursor');if(roll)roll.setAttribute('transform',`translate(${(time-state.rollStart)/state.rollSize*state.rollWidth} 0)`);
 $('roll').querySelectorAll('[data-time]').forEach(n=>{n.setAttribute('stroke',time>=Number(n.dataset.time)&&time<Number(n.dataset.end)?'#293e30':'none');});
}
function tick(now){
 if(state.playing&&state.master){const t=Math.min(state.session.duration,state.master.currentTime);
  if(now-state.lastSync>700){for(const [a,gain] of audioPlan()){a.volume=gain;if(a!==state.master&&!a.paused&&Math.abs(a.currentTime-t)>.065)a.currentTime=Math.min(t,a.duration-.001);}state.lastSync=now;}
  if(now-state.lastPaint>65){paint(t);state.lastPaint=now;}
 }requestAnimationFrame(tick);
}
function downloadSvg(id){const card=document.querySelector(`[data-track="${CSS.escape(id)}"]`);const svgs=[...card.querySelectorAll('svg')];if(!svgs.length)return;svgs.forEach((svg,i)=>{const clone=svg.cloneNode(true);clone.querySelectorAll('.active-note').forEach(n=>n.classList.remove('active-note'));clone.setAttribute('xmlns','http://www.w3.org/2000/svg');const url=URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(clone)],{type:'image/svg+xml'}));const a=document.createElement('a');a.href=url;a.download=id+'-score-'+(i+1)+'.svg';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});}
async function init(){
 renderPresets();$('presets').onchange=updatePassCount;$('file').onchange=e=>upload(e.target.files[0]);
 for(const event of ['dragenter','dragover'])$('drop-zone').addEventListener(event,e=>{e.preventDefault();$('drop-zone').classList.add('drag');});
 $('drop-zone').ondragleave=()=>$('drop-zone').classList.remove('drag');$('drop-zone').ondrop=e=>{e.preventDefault();$('drop-zone').classList.remove('drag');upload(e.dataTransfer.files[0]);};
 $('preview-clip').onclick=()=>{if(!state.job)return;$('clip-start').value=0;$('clip-end').value=Math.min(30,state.job.source.duration);};
 $('add-mix').onclick=()=>{const sources=[...$('mix-sources').querySelectorAll('input:checked')].map(x=>x.value);if(!sources.length||sources.length===1&&sources[0]==='drums'){notice('Choose at least one pitched source. Drums can be added as context.');return;}const key=[...sources].sort().join('-');if(chosenTargets().some(t=>[...t.sources].sort().join('-')===key)){notice('That combination is already selected.');return;}if(chosenTargets().length>=8){notice('Choose at most eight inputs per experiment.');return;}state.custom.push({label:$('mix-name').value.trim()||sources.join(' + '),sources});$('mix-name').value='';notice('');renderCustom();};
 $('custom-targets').onclick=e=>{const b=e.target.closest('[data-remove]');if(b){state.custom.splice(Number(b.dataset.remove),1);renderCustom();}};
 $('run').onclick=()=>startJob();$('retry').onclick=()=>startJob(true);$('cancel').onclick=async()=>{try{await api(`api/jobs/${state.job.id}/cancel`,{method:'POST'});pollJob();}catch(e){notice(e.message);}};
 $('new-session').onclick=newSession;$('history').onchange=e=>{if(e.target.value)loadJob(e.target.value);};
 $('jump-go').onclick=()=>seek(Number($('jump').value));$('jump').onkeydown=e=>{if(e.key==='Enter')seek(Number(e.target.value));};
 $('play').onclick=()=>state.playing?pause():play();$('seek').oninput=e=>seek(e.target.value);$('volume').oninput=()=>{for(const [a,gain] of audioPlan())a.volume=gain;};$('speed').onchange=()=>state.media.forEach(a=>a.playbackRate=Number($('speed').value));$('hear').onchange=()=>{state.audition=null;changeListening();};
 document.addEventListener('click',e=>{
  const svg=e.target.closest('[data-svg]');if(svg)downloadSvg(svg.dataset.svg);
  const tab=e.target.closest('[data-view]');if(tab)showView(tab.dataset.view);
  const inspectButton=e.target.closest('[data-inspect]');if(inspectButton)inspect(inspectButton.dataset.inspect);
  const mute=e.target.closest('[data-mute]');if(mute){const id=mute.dataset.mute;state.muted.has(id)?state.muted.delete(id):state.muted.add(id);state.audition=null;renderTracks();changeListening();}
  const solo=e.target.closest('[data-solo]');if(solo){const id=solo.dataset.solo;state.solo=state.solo===id?null:id;state.selected.add(id);state.muted.delete(id);state.audition=null;if($('hear').value==='original')$('hear').value='stems';renderTracks();renderScores();changeListening();}
  const audition=e.target.closest('[data-audition]');if(audition){state.audition=audition.dataset.audition||null;changeListening();}
  const row=e.target.closest('tr[data-time]');if(row)seek(Number(row.dataset.time));
 });
 $('track-list').onchange=e=>{const id=e.target.dataset.show;if(!id)return;e.target.checked?state.selected.add(id):state.selected.delete(id);if(state.solo===id&&!e.target.checked)state.solo=null;state.audition=null;renderScores();changeListening();};
 $('print-scores').onclick=()=>{showView('scores');window.print();};
 $('inspect-select').onchange=e=>{state.inspect=e.target.value;state.page={ledger:0,token:0};renderInspection();};$('roll-window').onchange=()=>paint(state.time,true);
 $('ledger-type').onchange=$('ledger-search').oninput=()=>{state.page.ledger=0;renderLedger();};$('token-search').oninput=()=>{state.page.token=0;renderTokens();};
 for(const [name,fn] of [['ledger',renderLedger],['token',renderTokens]]){$(name+'-prev').onclick=()=>{state.page[name]--;fn();};$(name+'-next').onclick=()=>{state.page[name]++;fn();};}
 window.addEventListener('keydown',e=>{if(['INPUT','SELECT','TEXTAREA','BUTTON'].includes(e.target.tagName)||e.target.isContentEditable)return;if(e.code==='Space'&&state.master){e.preventDefault();state.playing?pause():play();}if(e.key==='ArrowLeft')seek(state.time-5);if(e.key==='ArrowRight')seek(state.time+5);});
 let resizeTimer;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(state.view==='analysis'){renderOverview();paint(state.time,true);}},150);});
 requestAnimationFrame(tick);
 if(state.live){$('connection').textContent='Colab / local session';await refreshHistory();if(/^[a-f0-9]{32}$/.test(location.hash.slice(1)))await loadJob(location.hash.slice(1));}
 else{
  $('setup').hidden=true;document.querySelector('.intro').hidden=true;$('connection').textContent='Saved session';state.base='data/';
  if(location.protocol==='file:'){notice('Open this folder with a local web server: python3 serve.py, then visit http://localhost:8000.');return;}
  try{const session=await api('data/session.json');await hydrate(session);}catch(e){notice('No saved session found. Launch the Colab notebook to process a recording. '+e.message);}
 }
}
init().catch(e=>notice(e.message));
