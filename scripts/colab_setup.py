"""Install an isolated, supported inference environment in a Colab runtime."""
from pathlib import Path
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ENV = Path('/content/stem-score-env')
PYTHON = ENV/'bin/python'
LOG = Path('/content/stem-score-setup.log')

def step(label, command):
    print(label, flush=True)
    with LOG.open('a') as log:
        result = subprocess.run([str(x) for x in command], stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        print(LOG.read_text()[-7000:])
        raise RuntimeError(label+' failed. See /content/stem-score-setup.log.')

if not shutil.which('nvidia-smi'):
    raise RuntimeError('Select Runtime → Change runtime type → T4 GPU, then reconnect and rerun this cell.')
if shutil.disk_usage('/content').free < 12*1024**3:
    raise RuntimeError('Setup needs at least 12 GB of free runtime disk for packages, model weights and results.')
step('Checking the GPU…', ['nvidia-smi','--query-gpu=name,memory.total','--format=csv'])
if not shutil.which('ffmpeg'):
    step('Installing FFmpeg…',['apt-get','-qq','update'])
    step('Installing audio packages…',['apt-get','-qq','install','-y','ffmpeg','libsndfile1'])
step('Installing uv…',[sys.executable,'-m','pip','install','-q','uv==0.8.22'])
if not PYTHON.exists():
    step('Creating Python 3.11 environment…',['uv','venv','--python','3.11',ENV])
step('Installing CUDA PyTorch (first run is a large download)…',[
    'uv','pip','install','--python',PYTHON,'torch==2.8.0','torchaudio==2.8.0',
    '--index-url','https://download.pytorch.org/whl/cu126'])
step('Installing player and model dependencies…',[
    'uv','pip','install','--python',PYTHON,'-r',ROOT/'requirements.txt','-r',ROOT/'requirements-model.txt',
    'torch==2.8.0','torchaudio==2.8.0'])
# Demucs declares an older torchaudio range. Its tensor-based separation API works
# with 2.8; install without dependency resolution to preserve the model's torch pin.
step('Installing Demucs…',['uv','pip','install','--python',PYTHON,'--no-deps','demucs==4.0.1'])
step('Checking installed runtime…',[PYTHON,'-c',
    "import torch, torchaudio, transformers, fastapi, soundfile; from demucs.pretrained import get_model; assert torch.cuda.is_available(), 'No CUDA GPU'; print(torch.cuda.get_device_name(0))"])
print('Ready. Run the next cell to open Stem Score Lab. Model weights download on the first transcription.',flush=True)
