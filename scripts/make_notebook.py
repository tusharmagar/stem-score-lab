"""Generate a clean public notebook; never serialize local outputs or credentials."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
cells=[]
def add(kind,source):
    cell={'cell_type':kind,'metadata':{},'source':source.strip().splitlines(keepends=True)}
    if kind=='code':cell.update(execution_count=None,outputs=[])
    cells.append(cell)
add('markdown','''# Stem Score Lab
### Hear the parts. See the music.
Separate a recording with **Demucs**, transcribe selected stems or custom mixes with **SheetSage2**, and follow their scores together.

**Start:** Runtime → Change runtime type → **T4 GPU** (or a larger GPU). Run the two cells below in order. No installation is needed on your own computer.

Each person runs their own session and uploads their own audio. The interface stays inside Colab through its authenticated runtime proxy; no public tunnel is created. Uploaded audio is not sent to this project's GitHub repository. Google Colab stores and processes your runtime files; Hugging Face and Meta host model downloads.

Try a **30-second excerpt** first. First setup/model downloads can take several minutes; each selected input is a separate inference pass. Upload limit: 200 MB / 12 minutes. Runtime availability and limits depend on your Colab account.

**Experimental transcription:** separation does not guarantee better accuracy. “Other” can contain several instruments; model voice labels can be wrong. Drums are listenable and can be mixed in, but are not transcribed as pitched melodies. Empty/repetitive predictions are flagged, not hidden.

[Source and guide](https://github.com/tusharmagar/stem-score-lab) · [SheetSage2](https://huggingface.co/m-a-p/SheetSage2) · [Demucs](https://github.com/facebookresearch/demucs)

SheetSage2 weights use CC BY-NC 4.0; review upstream terms for your use. If a model access error occurs, grant access on Hugging Face and add a read token named **HF_TOKEN** in Colab Secrets (key icon). Do not paste tokens into code cells.
''')
add('code','''# 1. Install the isolated Python 3.11 / CUDA environment.
from pathlib import Path
import subprocess, sys
ROOT = Path('/content/stem-score-lab')
if not (ROOT / '.git').exists():
    subprocess.run(['git', 'clone', '--depth', '1',
        'https://github.com/tusharmagar/stem-score-lab.git', str(ROOT)], check=True)
setup = subprocess.Popen([sys.executable, '-u', str(ROOT / 'scripts/colab_setup.py')], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
for line in setup.stdout:
    print(line, end='', flush=True)
if setup.wait():
    raise RuntimeError('Setup failed; see the output above.')
''')
add('code','''# 2. Launch the player directly in this notebook.
# Rerun this cell if the interface needs to be reopened; completed runs are retained
# for as long as this runtime's disk survives.
exec((ROOT / 'scripts/colab_launch.py').read_text())
''')
add('markdown','''## Using the player
1. Upload audio; optionally choose an excerpt.
2. Choose **Full mix**, **Vocals**, **Bass**, **Other instruments**, **Instrumental**, or custom source combinations (up to eight unique inputs).
3. Click **Separate & transcribe**. Completed inputs become available as others process.
4. **Stacked scores** shows independent transcriptions on one audio clock. **Deep inspection** includes notes, chords, key, structure, beats, derived tempo, waveform, events, decoded tokens and exports.
5. **Hear** switches between the original, selected inputs, predicted melody tones, or an overlay. **Solo** isolates an input; the stem audition section includes drums. Scores retain both predicted vocal and instrumental voices when present.
6. **Download session ZIP** saves the player, audio and model outputs. Unzip locally, run `python3 serve.py`, then open the printed localhost URL. No model or GPU is needed to replay a saved session.

Selecting a combined mix transcribes that mix anew. Listening to several independently transcribed melodies is a different experiment. Independently predicted meters and bar positions may disagree even though all cursors follow the same audio time.

**Before disconnecting:** download your results. Runtime files disappear if Colab resets or deletes the machine. Sharing this notebook shares the workflow; it does not share your running session or uploaded song.

### Troubleshooting
- **No GPU / out of memory:** choose a GPU runtime; use fewer inputs or a shorter excerpt. Demucs and SheetSage2 run sequentially to avoid loading both models on GPU together.
- **One input fails:** other inputs continue. Retry unfinished inputs to reuse completed results and separated audio on this runtime.
- **No notes / repeated pitch:** inspect and listen; silence, separation artifacts, complex arrangements and model errors can all affect the output.
- **Disconnected interface:** reconnect Colab and rerun cell 2. If the runtime was reset, rerun setup and upload again.
- **Model access denied:** configure `HF_TOKEN` in Secrets, restart the runtime after downloading completed results, then rerun setup and launch.
- **Browser download fails in the iframe:** use the optional notebook download cell below.
''')
add('code','''# Optional: download the most recent completed/partial/cancelled session through Colab.
import json, urllib.request
from pathlib import Path
from google.colab import files
BASE = 'http://127.0.0.1:8766'
with urllib.request.urlopen(BASE + '/api/status') as response:
    sessions = json.load(response)['sessions']
finished = [s for s in sessions if s['status'] in ('complete', 'partial', 'cancelled', 'failed', 'interrupted')]
if not finished:
    print('No finished sessions yet.')
else:
    destination = Path('/content/Stem-Score-Lab.zip')
    urllib.request.urlretrieve(BASE + '/api/jobs/' + finished[0]['id'] + '/bundle', destination)
    files.download(str(destination))
''')
add('code','''# Optional: inspect recent worker messages for your latest run.
# Review logs before posting them publicly: they can include your filename.
from pathlib import Path
logs = sorted(Path('/content/stem-score-runs').glob('*/worker.log'), key=lambda p: p.stat().st_mtime)
print(logs[-1].read_text()[-7000:] if logs else 'No worker log yet.')
''')
add('markdown','''To apply a newly configured Hugging Face secret, stop the runtime process from the notebook's terminal or restart the runtime, then rerun setup and launch. Download completed work before restarting the runtime.''')
notebook={'nbformat':4,'nbformat_minor':5,'metadata':{'colab':{'name':'Stem_Score_Lab.ipynb'},'accelerator':'GPU','kernelspec':{'name':'python3','display_name':'Python 3'},'language_info':{'name':'python'}},'cells':cells}
for i,c in enumerate(cells):c['id']=f'stem-score-{i}'
(ROOT/'notebooks/Stem_Score_Lab.ipynb').write_text(json.dumps(notebook,indent=2)+'\n')
