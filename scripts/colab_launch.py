"""Called in the notebook kernel; the server runs in the isolated environment."""
from pathlib import Path
import json
import os
import subprocess
import time
import urllib.request
from google.colab import output

ROOT=Path('/content/stem-score-lab')
PYTHON=Path('/content/stem-score-env/bin/python')
PORT=8766
if not PYTHON.exists():
    raise RuntimeError('Run the setup cell first.')
# Optional secret, never printed or put in notebook source/output.
try:
    from google.colab import userdata
    token=userdata.get('HF_TOKEN')
except Exception:
    token=None
server_env=os.environ.copy()
if token:server_env['HF_TOKEN']=token
server_env['STEMSCORE_RUNS']='/content/stem-score-runs'
try:
    with urllib.request.urlopen(f'http://127.0.0.1:{PORT}/api/status',timeout=2) as response:
        json.load(response)
    print('Reusing your running Stem Score Lab session.')
except OSError:
    with Path('/content/stem-score-server.log').open('ab') as log:
        subprocess.Popen([str(PYTHON),'-m','stemscore.server','--port',str(PORT)],cwd=ROOT,
            env=server_env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    for _ in range(40):
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{PORT}/api/status',timeout=2) as response:
                json.load(response)
            break
        except OSError:time.sleep(.5)
    else:raise RuntimeError('Server did not start. Inspect /content/stem-score-server.log.')
print('Upload your audio below. Keep this runtime connected and download the session ZIP before leaving.')
output.serve_kernel_port_as_iframe(PORT,height=1000,cache_in_notebook=False)
