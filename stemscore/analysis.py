"""Adapt model exports to the UI, preserving raw files and raw timing."""
from collections import Counter
from copy import deepcopy
import math
from pathlib import Path
import re
import numpy as np
import soundfile as sf
from .core import read_json, write_json, command


def lab(path, converters):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        if line.strip():
            fields = line.split('\t')
            rows.append([f(x) for f, x in zip(converters, fields)])
    return rows


def display_midi(midi, grid):
    """Omit only notes that collapse to zero grid duration, on a display copy."""
    copy = deepcopy(midi)
    boundaries = (np.asarray(grid[:-1]) + np.asarray(grid[1:])) / 2
    omitted = []
    for instrument in copy.instruments:
        kept = []
        for note in instrument.notes:
            start, end = np.searchsorted(boundaries, [note.start, note.end])
            if end <= start:
                omitted.append(dict(voice=instrument.name, pitch=note.pitch, start=note.start, end=note.end))
            else:
                kept.append(note)
        instrument.notes = kept
    return copy, omitted


def align_score(notation, folder, duration, warnings=None):
    """Serialize each canonical voice and map each ABC token through its beat grid.

    No assumption about key, pitch, meter, silent voices, tempo or pickup length.
    Canonical padding maps to zero elapsed time, never to invented audio.
    """
    n, p = notation, Path(folder) / 'notation'
    try:
        score = n.build_rebuilt_abc_score(p/'song_melody.mid', p/'song_beats.txt', p/'song_chords.txt', p/'song_keys.txt', p/'song_structures.txt')
    except ValueError as exc:
        if not any(reason in str(exc) for reason in ('cannot be represented on the decoded subbeat grid', 'is shorter than the ABC subbeat grid')):
            raise
        import pretty_midi
        beats = n.read_beats(p/'song_beats.txt')
        measures, _ = n.infer_measures(beats, meter_conflict='infer')
        grid, _, _ = n._build_grid(beats, measures)
        midi, omitted = display_midi(pretty_midi.PrettyMIDI(str(p/'song_melody.mid')), grid)
        omitted_intervals = []
        def representable(rows, kind):
            kept = []
            for start, end, label in rows:
                if n._quantize_time(end, grid) <= n._quantize_time(start, grid):
                    omitted_intervals.append(dict(kind=kind, start=start, end=end, label=label))
                else:
                    kept.append((start, end, label))
            return kept
        keys = representable(n.read_keys(p/'song_keys.txt'), 'key')
        chords = representable(n.read_chords(p/'song_chords.txt'), 'chord')
        if not keys:
            raise ValueError('No decoded key interval fits the score grid')
        score = n._assemble_abc_score(midi, beats, keys,
            n.read_structures(p/'song_structures.txt'), chords,
            meter_conflict='infer', melody_only=False)
        for kind, items in [('notes', omitted), ('intervals', omitted_intervals)]:
            if items:
                write_json(Path(folder)/f'display-omitted-{kind}.json', items)
                if warnings is not None:
                    label = kind[:-1] if len(items)==1 else kind
                    warnings.append(f'Display score omits {len(items)} {label} shorter than the predicted grid can represent. Raw predictions and playback retain them. See display-omitted-{kind}.json.')
    unit = n.abc_unit_denominator(score)
    first = score.measures[0]
    parts = []
    for voice in ('Vocal', 'Ins'):
        values = score.voice_arrs[voice]
        if not np.any(values > 0):
            continue
        pitches = values[values > 0] // 2 - 1
        clef = 'bass' if np.median(pitches) < 55 else 'treble'
        abc = f'X:1\nT:{voice} melody\nM:{first.abc_numerator}/{first.abc_denominator}\nL:1/{unit}\nQ:1/4={round(n.estimate_tempo(score))}\nK:{score.key_arr[first.start_t]} clef={clef}\n'
        events, meter, key = [], (first.abc_numerator, first.abc_denominator), str(score.key_arr[first.start_t])
        for m in score.measures:
            next_meter = (m.abc_numerator, m.abc_denominator)
            if next_meter != meter:
                abc += f'[M:{next_meter[0]}/{next_meter[1]}]'
                meter = next_meter
            next_key = str(score.key_arr[m.start_t])
            if next_key != key:
                abc += f'[K:{next_key}]'
                key = next_key
            body = n._render_voice_measure(score, voice, m, unit)
            leading = n._measure_padding_units(m, unit) if m.pad_before else 0
            grid_units = [leading]
            for denominator in score.subbeat_denominators[m.start_t:m.end_t]:
                grid_units.append(grid_units[-1] + unit // (int(denominator) * score.subbeat_div))
            grid_times = np.clip(score.subbeat_times[m.start_t:m.end_t+1], 0, duration)
            used, offset = 0, len(abc)
            for match in n._MUSIC_ELEMENT_RE.finditer(body):
                if match.group('note') is None:
                    continue
                length = int(match.group('duration') or 1)
                start = float(np.interp(used, grid_units, grid_times))
                end = float(np.interp(used+length, grid_units, grid_times))
                rest = match.group('note') == 'z'
                sub = max(0, min(len(grid_units)-2, int(np.searchsorted(grid_units, used, side='right')-1)))
                pitch = None if rest else int(values[m.start_t+sub])//2-1
                events.append(dict(char=offset+match.start(), endChar=offset+match.end(), start=start, end=end, rest=rest, pitch=pitch, measure=m.index+1))
                used += length
            if used != n._measure_abc_units(m, unit):
                raise ValueError(f'ABC timing mismatch in measure {m.index+1}')
            abc += body + '|' + ('\n' if m.index % 4 == 3 else ' ')
            # Inline key changes update the next measure's starting key.
            key = str(score.key_arr[m.end_t-1])
        parts.append({'voice': voice, 'abc': abc+'\n', 'timeline': events})
        (Path(folder)/f'display-{voice}.abc').write_text(abc+'\n')
    return parts


def summarize(folder, audio_path, duration, notation=None):
    p = Path(folder)
    result = read_json(p/'result.json', {})
    events = read_json(p/'events.json', {}).get('events', [])
    notes = lab(p/'melody_full.lab', [float,float,int,int])
    notes = sorted([n for n in notes if len(n)==4 and 0 <= n[2] <=127 and 0<=n[0]<n[1]<=duration+.1])
    beats = lab(p/'beat.lab', [float,int,int,int])
    data = dict(result=result, events=events, notes=notes, beats=beats,
        chords=lab(p/'chord.lab',[float,float,str]), keys=lab(p/'key.lab',[float,float,str]),
        sections=lab(p/'structure.lab',[float,float,str]),
        playback=read_json(p/'playback.json', {'tracks': [], 'measures': []}),
        tokens=[], parts=[], warnings=list(result.get('warnings', []))+list(result.get('diagnostics', [])))
    data['rhythm'] = []
    rhythm_path = p/'rhythm_events.lab'
    if rhythm_path.exists():
        for line in rhythm_path.read_text().splitlines():
            if line.strip():
                stamp, value = line.split('\t', 1)
                import json
                data['rhythm'].append([float(stamp), json.loads(value)])
    data['tempo'] = [[a[0], 60/(b[0]-a[0])] for a,b in zip(beats,beats[1:]) if b[0]>a[0]]
    # Read decoded tokens with window offsets; position is local to each window.
    window, stamp, start = 0, None, 0
    token_path = p/'tokens.txt'
    if token_path.exists():
        windows = result.get('windows', [])
        for line in token_path.read_text().splitlines():
            if line.startswith('#'):
                m = re.search(r'window(?:_index)?[\s_=:-]*(\d+)', line, re.I)
                if m:
                    window = int(m.group(1)); start = windows[window].get('start',0) if window < len(windows) else 0; stamp=None
                continue
            cols = line.split('\t', 2)
            if len(cols) != 3 or not cols[0].isdigit(): continue
            match = re.fullmatch(r'<time_([\d.]+)s>',cols[2])
            if match: stamp = start+float(match.group(1))
            data['tokens'].append([window,int(cols[0]),int(cols[1]),cols[2],stamp])
    audio = np.frombuffer(command(['ffmpeg','-v','error','-i',audio_path,'-ac','1','-ar','8000','-f','f32le','-']),dtype='<f4')
    bins = np.array_split(audio, min(1500,max(1,len(audio))))
    data['waveform'] = [round(float(np.max(np.abs(x))),5) for x in bins]
    data['rms'] = [round(float(np.sqrt(np.mean(x*x))),6) for x in bins]
    counts = Counter(n[2] for n in notes)
    data['pitchCounts'] = sorted(counts.items())
    if not notes: data['warnings'].insert(0,'No melody notes were emitted. This does not establish that this audio has no melody.')
    elif len(notes)>=8 and max(counts.values())/len(notes)>.9:
        data['warnings'].insert(0,'More than 90% of predicted notes have one pitch. Listen against the input before trusting this transcription.')
    if result.get('abc_error'): data['warnings'].append('Model score export: '+str(result['abc_error']))
    if notation is not None and (p/'notation/song_melody.mid').exists():
        try: data['parts'] = align_score(notation,p,duration,data['warnings'])
        except Exception as e: data['warnings'].append('Synchronized score unavailable: '+str(e)+'. Raw ABC/MIDI remain downloadable.')
    write_json(p/'analysis.json', data)
    return data


def synthesize(notes, dest, duration):
    """Fixed-velocity sine tones of RAW melody timing, not recovered performance."""
    sr = 22050
    out = np.zeros(math.ceil(duration*sr), dtype=np.float32)
    for a,b,pitch,*_ in notes:
        a,b = max(0,round(a*sr)),min(len(out),round(b*sr))
        if b<=a: continue
        t=np.arange(b-a,dtype=np.float32)/sr
        env=np.minimum(t/.008,1)*np.minimum(((b-a)/sr-t)/.035,1)
        out[a:b] += .18*np.sin(2*np.pi*(440*2**((pitch-69)/12))*t)*env
    peak = np.max(np.abs(out),initial=0)
    if peak>.95: out*=.95/peak
    sf.write(dest,out,sr,subtype='PCM_16')
