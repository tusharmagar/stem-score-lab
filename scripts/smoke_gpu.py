"""Exercise upload → Demucs → SheetSage2 → analysis through the running service.

Uses a generated 12-second two-register tone pattern, not a music quality benchmark.
Run in the isolated inference environment after launching the server.
"""
import io
import json
from pathlib import Path
import re
import sys
import time
import urllib.request
import numpy as np
import soundfile as sf

BASE='http://127.0.0.1:8766'
with urllib.request.urlopen(BASE) as response:
    key=re.search(r'window.LAB_KEY=("[^"]+")',response.read().decode()).group(1)
key=json.loads(key)

def request(path,payload=None,raw=None):
    headers={'X-Lab-Key':key}
    data=None
    if payload is not None:headers['Content-Type']='application/json';data=json.dumps(payload).encode()
    if raw is not None:headers.update({'Content-Type':'audio/wav','X-Filename':'Synthetic%20integration%20test.wav'});data=raw
    with urllib.request.urlopen(urllib.request.Request(BASE+path,data=data,headers=headers),timeout=120) as response:
        return json.load(response)

sr=44100;duration=12;audio=np.zeros((sr*duration,2),np.float32)
for i in range(24):
    start=int(i*.5*sr);length=int(.44*sr);t=np.arange(length)/sr
    env=np.minimum(t/.01,1)*np.minimum((.44-t)/.04,1)
    pitch=[60,64,67,72,69,65,62,67][i%8];hz=440*2**((pitch-69)/12)
    audio[start:start+length,0]+=.16*(np.sin(2*np.pi*hz*t)+.2*np.sin(4*np.pi*hz*t))*env
    bass=[36,36,41,43][i//6];hz=440*2**((bass-69)/12)
    audio[start:start+length,1]+=.13*np.sin(2*np.pi*hz*t)*env
memory=io.BytesIO();sf.write(memory,audio,sr,format='WAV')
job=request('/api/upload',raw=memory.getvalue())
config={'start':0,'end':duration,'targets':[
 {'label':'Full mix','sources':['original']}, {'label':'Vocals','sources':['vocals']},
 {'label':'Bass','sources':['bass']}, {'label':'Other instruments','sources':['other']},
 {'label':'Bass + other','sources':['bass','other']}]}
request('/api/jobs/'+job['id']+'/run',payload=config)
print('JOB',job['id'],flush=True)
last=None;deadline=time.monotonic()+1200
while time.monotonic()<deadline:
    result=request('/api/jobs/'+job['id'])
    stamp=(result['stage'],str(result.get('progress')))
    if stamp!=last:
        print(result['status'],result['stage'],result.get('progress'),flush=True);last=stamp
    if result['status'] not in ('queued','running','cancelling'):break
    time.sleep(4)
else:raise RuntimeError('Integration test exceeded 20 minutes; inspect or cancel the running job.')
print('RESULT',json.dumps({'id':job['id'],'status':result['status'],'error':result.get('error'),'targets':[{k:t.get(k) for k in ['label','status','noteCount','error']} for t in result['targets']]}),flush=True)
if result['status']!='complete':sys.exit(1)
for target in result['targets']:
    if target.get('analysis'):
        data=request('/results/'+job['id']+'/'+target['analysis'])
        assert 'notes' in data and 'parts' in data
        assert all(0<=e['start']<=e['end']<=duration+.001 for part in data['parts'] for e in part['timeline'])
print('GPU PIPELINE CHECK PASSED. This checks execution, not transcription accuracy.',flush=True)
