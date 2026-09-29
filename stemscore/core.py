"""Pure validation, media preparation and artifact helpers (no model imports)."""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import uuid

MODEL_ID = 'm-a-p/SheetSage2'
MODEL_REVISION = 'cafc0df1021e14f49e928c4b345f5959d414ef64'
SOURCES = ('vocals', 'drums', 'bass', 'other')
MAX_BYTES = 200 * 1024 * 1024
MAX_DURATION = 720
MAX_TARGETS = 8
ROOT = Path(__file__).resolve().parents[1]
RUNS = Path(os.environ.get('STEMSCORE_RUNS', ROOT / 'runs')).resolve()


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')))
    temp.replace(path)


def command(args):
    result = subprocess.run([str(x) for x in args], capture_output=True, timeout=600)
    if result.returncode:
        raise ValueError(result.stderr.decode(errors='replace')[-2000:])
    return result.stdout


def probe(path):
    data = json.loads(command(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe',
        '-select_streams', 'a:0', '-show_entries', 'format=duration:stream=duration,channels,sample_rate',
        '-of', 'json', path]))
    streams = data.get('streams', [])
    if not streams:
        raise ValueError('This file has no readable audio stream.')
    duration = float(data.get('format', {}).get('duration', streams[0].get('duration', 0)))
    if not math.isfinite(duration) or not 1 <= duration <= MAX_DURATION:
        raise ValueError(f'Choose audio between 1 second and {MAX_DURATION // 60} minutes. Trim longer recordings first.')
    return {'duration': duration, 'sampleRate': int(streams[0]['sample_rate']), 'channels': streams[0]['channels']}


def validate_config(config, duration):
    if not isinstance(config, dict):
        raise ValueError('Experiment configuration must be an object.')
    start = float(config.get('start', 0))
    end = float(config.get('end') or duration)
    if not all(math.isfinite(x) for x in (start, end)) or not 0 <= start < end <= duration + .01 or end-start < 1:
        raise ValueError('Choose a valid excerpt of at least 1 second inside the recording.')
    targets = config.get('targets', [])
    if not isinstance(targets, list) or not 1 <= len(targets) <= MAX_TARGETS:
        raise ValueError(f'Choose between 1 and {MAX_TARGETS} transcription inputs.')
    cleaned, seen = [], set()
    for target in targets:
        if not isinstance(target, dict):
            raise ValueError('Each transcription input must be an object.')
        components = target.get('sources', [])
        if not isinstance(components, list) or not components or any(not isinstance(c, str) for c in components) or len(components) != len(set(components)):
            raise ValueError('Every input needs distinct source names.')
        if any(c not in (*SOURCES, 'original') for c in components):
            raise ValueError('Unknown source in mix.')
        if 'original' in components and len(components) > 1:
            raise ValueError('The original already contains every source; choose stems to create a mix.')
        if components == ['drums']:
            raise ValueError('Drums are available for listening; pitched melody transcription is not supported for drums alone.')
        key = '-'.join(sorted(components))
        if key in seen:
            continue
        seen.add(key)
        label = str(target.get('label') or ' + '.join(components)).strip()[:70] or key
        cleaned.append({'id': key, 'label': label, 'sources': components})
    return {'start': start, 'end': min(end, duration), 'targets': cleaned}


def media_wav(source, dest, start=0, duration=None):
    args = ['ffmpeg', '-y', '-v', 'error', '-protocol_whitelist', 'file,pipe', '-i', source, '-ss', str(start)]
    if duration is not None:
        args += ['-t', str(duration)]
    command(args + ['-map', '0:a:0', '-vn', '-ac', '2', '-ar', '44100', '-c:a', 'pcm_f32le', dest])


def mp3(source, dest):
    command(['ffmpeg', '-y', '-v', 'error', '-i', source, '-map', '0:a:0', '-codec:a', 'libmp3lame', '-q:a', '3', dest])


def fingerprint(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()
