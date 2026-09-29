"""One cancellable subprocess owns GPU memory; each input can fail independently."""
from __future__ import annotations
import gc
import importlib
import json
import os
from pathlib import Path
import sys
import time
import traceback
import numpy as np
import soundfile as sf
from .core import MODEL_ID, MODEL_REVISION, SOURCES, RUNS, read_json, write_json, media_wav, mp3
from .analysis import summarize, synthesize


def run(job_id):
    folder = RUNS / job_id
    manifest = read_json(folder/'manifest.json')
    config = manifest['config']
    duration = config['end']-config['start']
    def update(stage, **fields):
        manifest.update(stage=stage, updated=time.time(), **fields)
        write_json(folder/'manifest.json',manifest)
    update('Preparing audio',status='running')
    import torch
    torch.set_num_threads(min(4,torch.get_num_threads()))
    if not torch.cuda.is_available():
        raise RuntimeError('A CUDA GPU is required. In Colab choose Runtime → Change runtime type → T4 GPU, then run setup again.')
    public = folder/'result'
    (public/'audio').mkdir(parents=True,exist_ok=True)
    raw = folder/'prepared'; raw.mkdir(exist_ok=True)
    original = raw/'original.wav'
    if not original.exists():
        media_wav(folder/'upload',original,config['start'],duration)
    recording,sr = sf.read(original,dtype='float32',always_2d=True)
    if not len(recording) or not np.isfinite(recording).all(): raise ValueError('Decoded audio is empty or non-finite.')
    duration=len(recording)/sr
    manifest['duration']=duration
    # All stem listening files share the same gain, retaining relative levels.
    manifest.setdefault('audio',{})
    def add_audio(name,path):
        dest=public/'audio'/f'{name}.mp3'
        if not dest.exists(): mp3(path,dest)
        manifest['audio'][name]=f'audio/{name}.mp3'
    add_audio('original',original)
    required = any(t['sources'] != ['original'] for t in config['targets'])
    if required:
        if not all((raw/f'{s}.wav').exists() for s in SOURCES):
            update('Separating vocals, drums, bass and other instruments')
            from demucs.pretrained import get_model
            from demucs.apply import apply_model
            separator=get_model('htdemucs').eval().to('cuda')
            audio=torch.from_numpy(recording.T.copy())
            ref=audio.mean(0); mean=ref.mean(); std=ref.std()
            if float(std)<1e-7:
                separated=np.zeros((4,len(recording),2),dtype=np.float32)
            else:
                with torch.inference_mode():
                    output=apply_model(separator,((audio-mean)/std)[None],device='cuda',shifts=1,split=True,segment=7,overlap=.25,progress=True)[0].cpu()
                    output=output*std+mean
                separated=output.numpy().transpose(0,2,1)
            # Preserve exact length and common timing; float WAV avoids per-stem clipping/normalization.
            for i,name in enumerate(separator.sources):
                sf.write(raw/f'{name}.wav',separated[i],sr,subtype='FLOAT')
            del separator, separated
            if 'output' in locals(): del output
            gc.collect(); torch.cuda.empty_cache()
        peak=1.0
        for name in SOURCES:
            signal,_=sf.read(raw/f'{name}.wav',dtype='float32',always_2d=True)
            peak=max(peak,float(np.max(np.abs(signal),initial=0)))
        stem_gain=.98/peak
        manifest['stemPlaybackGain']=stem_gain
        for name in SOURCES:
            tmp=raw/f'{name}-listen.wav'
            if not tmp.exists():
                signal,_=sf.read(raw/f'{name}.wav',dtype='float32',always_2d=True)
                sf.write(tmp,signal*stem_gain,sr,subtype='PCM_16')
            add_audio(name,tmp)
    update('Preparing transcription inputs')
    targets=manifest['targets']
    pending=[]
    for target in targets:
        if target.get('status') in ('ready','empty'): continue
        target.update(status='queued',error=None)
        p=public/target['id']; p.mkdir(exist_ok=True)
        if target['sources']==['original']:
            mixed=recording.copy()
        else:
            mixed=np.zeros_like(recording)
            for name in target['sources']:
                signal,_=sf.read(raw/f'{name}.wav',dtype='float32',always_2d=True)
                if signal.shape != mixed.shape: raise ValueError('Separated source length mismatch.')
                mixed+=signal
        peak=float(np.max(np.abs(mixed),initial=0)); gain=min(1,.98/max(peak,1e-9))
        target['mixGain']=gain
        source=raw/f"input-{target['id']}.wav"
        sf.write(source,mixed*gain,sr,subtype='FLOAT')
        mp3(source,p/'input.mp3')
        target['audio']=target['id']+'/input.mp3'
        if float(np.sqrt(np.mean(mixed.astype(np.float64)**2)))<1e-5:
            target.update(status='empty',error='This input is effectively silent. Transcription skipped; audio remains available.')
        else: pending.append((target,source,p))
    update('Loading SheetSage2 and its MERT backbone')
    if pending:
        from transformers import AutoModel
        model=AutoModel.from_pretrained(MODEL_ID,revision=MODEL_REVISION,code_revision=MODEL_REVISION,trust_remote_code=True).eval().to('cuda')
        notation=importlib.import_module(type(model).__module__.rsplit('.',1)[0]+'.notation_sheetsage2')
        # Recent torch can report emulated bf16 on a T4; use native support only.
        dtype='bf16' if torch.cuda.get_device_capability()[0]>=8 else 'fp32'
        manifest['model']={'id':MODEL_ID,'revision':MODEL_REVISION,'device':torch.cuda.get_device_name(),'precision':dtype,'demucs':'htdemucs / 4.0.1'}
        for i,(target,source,p) in enumerate(pending):
            target['status']='running'
            update(f"Transcribing {target['label']} ({i+1}/{len(pending)})",activeTarget=target['id'])
            last=[0.]
            def progress(event):
                now=time.monotonic()
                if event.get('stage')!='decoding' or now-last[0]>2:
                    update(manifest['stage'],progress=event);last[0]=now
            try:
                # Full prompt set captures both vocal and instrumental predictions on every input.
                model.transcribe(str(source),output_dir=str(p),dtype=dtype,progress=progress)
                data=summarize(p,source,duration,notation)
                synthesize(data['notes'],p/'melody.wav',duration)
                mp3(p/'melody.wav',p/'melody.mp3');(p/'melody.wav').unlink()
                target.update(status='ready' if data['notes'] else 'empty',analysis=target['id']+'/analysis.json',
                    synth=target['id']+'/melody.mp3',noteCount=len(data['notes']),warnings=data['warnings'])
            except Exception as exc:
                traceback.print_exc()
                target.update(status='failed',error=explain(exc))
                if (p/'result.json').exists():
                    try:
                        data=summarize(p,source,duration,notation)
                        target['analysis']=target['id']+'/analysis.json'
                    except Exception: pass
                gc.collect();torch.cuda.empty_cache()
            target['files']=[str(f.relative_to(public)) for f in sorted(p.rglob('*')) if f.is_file()]
            update(manifest['stage'])
        del model;gc.collect();torch.cuda.empty_cache()
    good=sum(t['status'] in ('ready','empty') for t in targets)
    status='complete' if good==len(targets) else 'partial' if good else 'failed'
    update('Complete' if status=='complete' else 'Some inputs could not be transcribed',status=status,activeTarget=None,progress=None)
    write_json(public/'session.json',public_session(manifest))


def public_session(manifest):
    return {k:manifest[k] for k in ('title','duration','config','targets','audio','model','stemPlaybackGain') if k in manifest}


def explain(exc):
    message=str(exc)
    if 'out of memory' in message.lower():
        return 'GPU memory ran out. Try a shorter excerpt or a larger Colab GPU. Completed inputs are kept. '+message[:300]
    if any(s in message.lower() for s in ('gated','401','403','unauthorized')):
        return 'Model access was denied. Accept the model access conditions on Hugging Face, set HF_TOKEN in Colab Secrets, and rerun setup. '+message[:300]
    return type(exc).__name__+': '+message[:700]

if __name__=='__main__':
    job=sys.argv[1]
    try: run(job)
    except Exception as e:
        traceback.print_exc()
        p=RUNS/job/'manifest.json';m=read_json(p,{})
        m.update(status='failed',stage='Processing stopped',error=explain(e),updated=time.time())
        write_json(p,m)
        sys.exit(1)
