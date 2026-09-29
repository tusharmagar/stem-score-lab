import io
import zipfile
from pathlib import Path
import pytest
import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient
from stemscore.core import validate_config, write_json, probe, media_wav
from stemscore.analysis import summarize, synthesize


def config(*sources,start=0,end=10):
    return {'start':start,'end':end,'targets':[{'sources':list(s)} for s in sources]}


def test_inputs_are_canonical_and_deduplicated():
    result=validate_config(config(['other','bass'],['bass','other'],['original']),20)
    assert len(result['targets'])==2
    assert result['targets'][0]['id']=='bass-other'


@pytest.mark.parametrize('bad',[
    config(['drums']),config(['original','bass']),config(['guitar']),config(['bass','bass']),
    config([],),config(['vocals'],start=-1),config(['vocals'],end=21),config(['vocals'],start=9.9),
    config(['vocals'],end=float('nan')),config(['vocals'],start=float('inf')),
    {'targets':[]}, {'targets':[{'sources':['vocals']}]*9}
])
def test_invalid_inputs_rejected(bad):
    with pytest.raises(ValueError):validate_config(bad,20)


def test_mp3_or_stereo_is_not_required(tmp_path):
    source=tmp_path/'mono.wav';sf.write(source,np.sin(np.arange(22050*3)*2*np.pi*220/22050)*.1,22050)
    info=probe(source);assert info['channels']==1 and info['duration']==3
    out=tmp_path/'stereo.wav';media_wav(source,out,.5,1.25)
    data,rate=sf.read(out,always_2d=True);assert rate==44100 and data.shape==(55125,2)


def test_silence_missing_score_and_overlap_tokens(tmp_path):
    source=tmp_path/'silent.wav';sf.write(source,np.zeros(16000),8000)
    write_json(tmp_path/'result.json',{'duration_seconds':2,'windows':[{'start':0},{'start':100}]})
    (tmp_path/'tokens.txt').write_text('# window_index=0 start=0\n0\t1\t<time_1.0s>\n1\t2\tfoo\n# window_index=1 start=100\n0\t1\t<time_1.5s>\n1\t2\tbar\n')
    d=summarize(tmp_path,source,2)
    assert not d['notes'] and not d['parts'] and d['warnings']
    assert d['tokens'][-1][-1]==101.5
    assert not any(d['waveform'])
    synthesize([],tmp_path/'synth.wav',2)
    data,rate=sf.read(tmp_path/'synth.wav');assert len(data)==rate*2 and not data.any()


def test_repetition_alert_and_polyphony_synthesis(tmp_path):
    source=tmp_path/'input.wav';sf.write(source,np.zeros(8000*2),8000)
    (tmp_path/'melody_full.lab').write_text(''.join(f'{i/10}\t{i/10+.1}\t69\t1\n' for i in range(10)))
    d=summarize(tmp_path,source,2);assert '90%' in d['warnings'][0]
    synthesize([[0,1,40,1],[0,1,80,0]],tmp_path/'synth.wav',2)
    data,_=sf.read(tmp_path/'synth.wav');assert np.max(np.abs(data))<=.95


@pytest.fixture
def server(tmp_path,monkeypatch):
    from stemscore import server
    monkeypatch.setattr(server,'RUNS',tmp_path)
    monkeypatch.setattr(server,'WORKER',None)
    monkeypatch.setattr(server,'ACTIVE',None)
    return server,TestClient(server.app)


def upload_wav(server):
    mod,client=server;data=io.BytesIO();sf.write(data,np.zeros(8000*2),8000,format='WAV')
    r=client.post('/api/upload',headers={'X-Lab-Key':mod.KEY,'X-Filename':'test.wav'},content=data.getvalue())
    assert r.status_code==200
    return r.json()['id']


def test_upload_auth_invalid_file_and_size(server,monkeypatch):
    mod,client=server
    assert client.post('/api/upload',content=b'abc').status_code==403
    assert client.post('/api/upload',headers={'X-Lab-Key':mod.KEY},content=b'abc').status_code==400
    assert not list(mod.RUNS.iterdir())
    monkeypatch.setattr(mod,'MAX_BYTES',10)
    assert client.post('/api/upload',headers={'X-Lab-Key':mod.KEY},content=b'x'*11).status_code==413
    assert not list(mod.RUNS.iterdir())


def test_mutual_exclusion_and_immutable_configuration(server,monkeypatch):
    mod,client=server;job=upload_wav(server);headers={'X-Lab-Key':mod.KEY}
    monkeypatch.setattr(mod,'WORKER',object())
    assert client.post(f'/api/jobs/{job}/run',headers=headers,json=config(['bass'])).status_code==409
    monkeypatch.setattr(mod,'WORKER',None);monkeypatch.setattr(mod,'launch',lambda p:None)
    payload=config(['bass'],end=2)
    assert client.post(f'/api/jobs/{job}/run',headers=headers,json=payload).status_code==200
    assert client.post(f'/api/jobs/{job}/run',headers=headers,json=config(['other'],end=2)).status_code==409
    assert client.post(f'/api/jobs/{job}/run',headers=headers,json=payload).status_code==200


def test_range_requests_and_private_files_not_in_download(server):
    mod,client=server;job=upload_wav(server);p=mod.RUNS/job
    result=p/'result';result.mkdir();(result/'clip.mp3').write_bytes(b'0123456789')
    r=client.get(f'/results/{job}/clip.mp3',headers={'Range':'bytes=2-5'})
    assert r.status_code==206 and r.content==b'2345'
    assert client.get(f'/results/{job}/%2E%2E/upload').status_code==404
    (result/'leak').symlink_to(p/'upload')
    assert client.get(f'/results/{job}/leak').status_code==404
    (result/'leak').unlink()
    m=mod.read_json(p/'manifest.json');m.update(status='cancelled',duration=2,targets=[],config={},audio={'original':'clip.mp3'})
    write_json(p/'manifest.json',m);(p/'worker.log').write_text('secret-log')
    r=client.get(f'/api/jobs/{job}/bundle');assert r.status_code==200
    with zipfile.ZipFile(io.BytesIO(r.content)) as archive:
        names=archive.namelist();assert 'data/session.json' in names and 'app.js' in names
        assert 'upload' not in names and not any('.log' in n or '.git/' in n for n in names)
        assert mod.KEY.encode() not in archive.read('index.html')
        assert archive.read('data/clip.mp3')==b'0123456789'
