export const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const formatTime = (seconds, precise=false) => {
  const ms = Math.max(0, Math.round((Number(seconds)||0)*1000));
  return Math.floor(ms/60000)+':'+String(Math.floor(ms/1000)%60).padStart(2,'0')+(precise?'.'+String(ms%1000).padStart(3,'0'):'');
};
export const pitchName = pitch => ['C','C♯','D','E♭','E','F','F♯','G','A♭','A','B♭','B'][pitch%12]+(Math.floor(pitch/12)-1);
export function bisect(rows, time, key=row=>row[0]) {
  let low=0,high=rows.length;
  while(low<high){const mid=(low+high)>>1;if(key(rows[mid])<=time)low=mid+1;else high=mid;}
  return low-1;
}
export function spanAt(rows,time){const row=rows[bisect(rows,time)];return row&&time<row[1]?row:null;}
export function overlappingSources(targets) {
  const seen=new Set();
  for(const target of targets){for(const source of target.sources.includes('original')?['vocals','drums','bass','other']:target.sources){if(seen.has(source))return true;seen.add(source);}}
  return false;
}
export function activeNotes(notes,time){return notes.filter(n=>n[0]<=time&&time<n[1]);}
export function pitchBounds(notes){const pitches=notes.map(n=>n[2]).filter(Number.isFinite);return pitches.length?[Math.max(0,Math.min(...pitches)-3),Math.min(127,Math.max(...pitches)+3)]:[48,72];}
export function safeAsset(path){return typeof path==='string'&&!path.includes('..')&&!path.includes('\\')&&!/^[/]|^[a-z]+:/i.test(path);}
