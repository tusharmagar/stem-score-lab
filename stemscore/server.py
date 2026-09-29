"""Session-scoped HTTP service. CPU web process supervises one GPU worker."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from .core import ROOT, RUNS, MAX_BYTES, read_json, write_json, probe, validate_config

app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
KEY=secrets.token_urlsafe(32)
LOCK=threading.RLock()
WORKER=None
ACTIVE=None
RUNS.mkdir(parents=True,exist_ok=True)
for path in RUNS.glob('*/manifest.json'):
    m=read_json(path,{})
    if m.get('status') in ('running','queued','cancelling'):
        m.update(status='interrupted',stage='Previous runtime stopped. Retry to keep completed inputs.')
        write_json(path,m)


def directory(job):
    if len(job)!=32 or any(c not in '0123456789abcdef' for c in job):raise HTTPException(404,'Unknown session')
    p=RUNS/job
    if not p.is_dir():raise HTTPException(404,'Unknown session')
    return p


def authorize(request):
    if not secrets.compare_digest(request.headers.get('X-Lab-Key',''),KEY):raise HTTPException(403,'Reload this page before changing the session.')


@app.get('/',response_class=HTMLResponse)
def index():
    return (ROOT/'web/index.html').read_text().replace('<!--CONFIG-->', '<script>window.LAB_KEY='+json.dumps(KEY)+'</script>')


@app.get('/api/status')
def status():
    sessions=[]
    for path in RUNS.glob('*/manifest.json'):
        m=read_json(path,{})
        sessions.append({k:m.get(k) for k in ('id','title','status','stage','updated')})
    return {'active':ACTIVE,'sessions':sorted(sessions,key=lambda x:x['updated'] or 0,reverse=True),'maxUploadMB':MAX_BYTES//1024**2}


@app.post('/api/upload')
async def upload(request:Request):
    authorize(request)
    p=RUNS/uuid.uuid4().hex;p.mkdir()
    total=0
    try:
        with (p/'upload').open('wb') as stream:
            async for chunk in request.stream():
                total+=len(chunk)
                if total>MAX_BYTES:raise HTTPException(413,'Upload limit is 200 MB. Compress or trim the recording.')
                stream.write(chunk)
        info=await asyncio.to_thread(probe,p/'upload')
        title=request.headers.get('X-Filename','Your recording')
        from urllib.parse import unquote
        title=Path(unquote(title)).name[:150]
        m=dict(id=p.name,title=title,source=info,status='uploaded',stage='Choose inputs',updated=time.time())
        write_json(p/'manifest.json',m)
        return m
    except HTTPException:
        shutil.rmtree(p);raise
    except Exception as exc:
        shutil.rmtree(p);raise HTTPException(400,str(exc))


def launch(p):
    global WORKER,ACTIVE
    (p/'cancel-requested').unlink(missing_ok=True)
    env=os.environ.copy();env['STEMSCORE_RUNS']=str(RUNS)
    # Official Demucs checkpoints include Python state (PyTorch 2.6+ changed its default).
    env['TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD']='1'
    with (p/'worker.log').open('ab') as log:
        WORKER=subprocess.Popen([sys.executable,'-u','-m','stemscore.worker',p.name],cwd=ROOT,
            env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    ACTIVE=p.name
    def monitor(proc,job):
        global WORKER,ACTIVE
        rc=proc.wait()
        with LOCK:
            m=read_json(p/'manifest.json')
            if m['status'] in ('running','queued','cancelling'):
                m.update(status='cancelled' if (p/'cancel-requested').exists() else 'failed',stage='Cancelled; completed inputs retained' if (p/'cancel-requested').exists() else f'Worker exited ({rc}). Retry or inspect the notebook log.',updated=time.time())
                for t in m.get('targets',[]):
                    if t['status'] in ('queued','running'):t['status']='cancelled'
                write_json(p/'manifest.json',m)
            if ACTIVE==job:WORKER=None;ACTIVE=None
    threading.Thread(target=monitor,args=(WORKER,p.name),daemon=True).start()


@app.post('/api/jobs/{job}/run')
async def start(job:str,request:Request):
    authorize(request);p=directory(job);body=await request.json()
    with LOCK:
        if WORKER is not None:raise HTTPException(409,'Another run is active. Cancel it or wait before starting.')
        m=read_json(p/'manifest.json')
        try:config=validate_config(body,m['source']['duration'])
        except (ValueError,TypeError,KeyError) as e:raise HTTPException(400,str(e))
        if m.get('config') and m['config']!=config:
            raise HTTPException(409,'This session has saved results. Upload the recording again to start a different experiment.')
        m.update(config=config,status='queued',stage='Starting worker',error=None,updated=time.time())
        m.setdefault('targets',[dict(t,status='queued') for t in config['targets']])
        write_json(p/'manifest.json',m);launch(p)
    return m


@app.post('/api/jobs/{job}/cancel')
def cancel(job:str,request:Request):
    authorize(request);p=directory(job)
    with LOCK:
        if ACTIVE!=job or WORKER is None:raise HTTPException(409,'This run is no longer active.')
        m=read_json(p/'manifest.json');m.update(status='cancelling',stage='Stopping worker');write_json(p/'manifest.json',m)
        proc=WORKER
        (p/'cancel-requested').touch()
        os.killpg(proc.pid,signal.SIGTERM)
        def force_stop():
            try:proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                try:os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError:pass
        threading.Thread(target=force_stop,daemon=True).start()
    return {'status':'cancelling'}


@app.get('/api/jobs/{job}')
def get_job(job:str):
    return read_json(directory(job)/'manifest.json')


@app.get('/results/{job}/{filename:path}')
def artifact(job:str,filename:str):
    base=directory(job)/'result';path=(base/filename).resolve()
    if not path.is_relative_to(base.resolve()) or not path.is_file():raise HTTPException(404,'File unavailable')
    return FileResponse(path)


@app.get('/api/jobs/{job}/bundle')
def bundle(job:str):
    p=directory(job);m=read_json(p/'manifest.json')
    if m['status'] in ('queued','running','cancelling','uploaded'):raise HTTPException(409,'Stop the run or wait before downloading.')
    # Snapshot includes finished/partial exports, not original uploads, logs or credentials.
    from .worker import public_session
    result=p/'result';result.mkdir(exist_ok=True)
    write_json(result/'session.json',public_session(m))
    dest=p/'Stem-Score-Lab.zip'
    temp=p/(uuid.uuid4().hex+'.zip')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as archive:
        for f in (ROOT/'web').rglob('*'):
            if f.is_file() and not f.is_symlink():archive.write(f,f.relative_to(ROOT/'web'))
        for f in result.rglob('*'):
            if f.is_file() and not f.is_symlink():archive.write(f,Path('data')/f.relative_to(result))
        archive.writestr('START.txt','Run: python3 serve.py\nThen open http://localhost:8000\nKeep this folder private if its audio is private.\nScores are model predictions; synthesis uses simple tones, not the original performance.\n')
    temp.replace(dest)
    return FileResponse(dest,filename='Stem-Score-Lab.zip',media_type='application/zip')

app.mount('/',StaticFiles(directory=ROOT/'web'),name='assets')


def main():
    import uvicorn
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8766);args=parser.parse_args()
    uvicorn.run(app,host='127.0.0.1',port=args.port,log_level='warning')

if __name__=='__main__':main()
