# Stem Score Lab

**Separate a recording. Transcribe its parts. Follow the scores together.**

[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/tusharmagar/stem-score-lab/blob/main/notebooks/Stem_Score_Lab.ipynb)

A bring-your-own-audio experiment using **Demucs + SheetSage2**, with a dense, synchronized music analysis player. Everyone uses their own Google Colab GPU session. No local GPU, public tunnel, paid inference endpoint, or shared backend is required.

## Try it

1. Open the notebook above and choose **Runtime → Change runtime type → T4 GPU** (or a larger GPU).
2. Run **setup**, then **launch**. The interface appears inside the notebook.
3. Upload audio and choose an excerpt. **Start with 30 seconds.**
4. Select transcription inputs, then **Separate & transcribe**.
5. Explore **Stacked scores** or **Deep inspection**, and download your session before Colab disconnects.

Setup and model weights are large downloads. Transcription speed depends on GPU, duration and the number of inputs. Colab GPU availability and runtime limits depend on your account. Each input is processed serially; separation happens once per experiment.

## Inputs and listening

Choose the full mix, vocals, bass, other instruments, instrumental (drums + bass + other), or custom combinations of the four stems. Up to eight unique inputs can be selected. Duplicate combinations are merged. Drums can be auditioned or added to a mix; drums alone are not presented as a pitched melody transcription.

Two different experiments are supported:

- **Transcribe a mix:** sum its source audio, then ask SheetSage2 to transcribe that recording.
- **Compare independent scores:** transcribe several inputs separately and display their scores on a common audio clock.

The player provides:

- Per-input stacked staves, preserving both model-predicted vocal and instrumental voices when present; bass clef for low-register voices.
- Shared seeking and note highlighting, input visibility, mute/solo, and audition buttons for all separated sources.
- Original audio, selected inputs, synthesized predicted melodies, or an overlay. Synthesized melodies use fixed-velocity tones, not recovered instruments.
- Waveform, structure/key/chord/beat lanes, derived BPM and RMS, dynamic-range piano roll, searchable/paginated raw events and token tables, diagnostics, and model export downloads.
- Original ABC/MIDI/LAB/JSON exports and a replayable session ZIP, with no model inference needed to reopen it.

Scores have independently predicted beat grids. **Their bar lines can disagree even though the cursors share audio seconds.** Staff timing can differ from raw event timing because of quantization and notation repairs. Empty voices are not replaced with invented notes.

If a tiny boundary note or annotation cannot fit on the predicted notation grid, the display can omit it with an explicit diagnostic, rather than losing the whole staff. Raw predictions, MIDI, piano roll and synthesized playback retain it. `display-*.abc` exports match the displayed staves; `display-omitted-*.json` records any omissions.

Playback of several overlapping mixes can double sources. The UI warns about this and reduces multi-input gain. Solo inputs for direct comparisons. MP3s are listening previews; the model consumes prepared float WAV audio. Mix gains and model revision/precision are recorded in session metadata.

## What this experiment can establish

Source separation may reveal a line that is masked in the full mix. It does **not** establish that a separated transcription is more accurate. “Other” is a broad residual stem that can contain multiple instruments; artifacts and incorrect model voice labels are possible. SheetSage2 produces lead-sheet-style predictions, not exhaustive multi-instrument notation.

The interface flags empty melodies and cases where more than 90% of notes repeat one pitch. These are descriptive checks, not calibrated confidence. Listen against the source. Short excerpts can also weaken structure/key estimates.

Embeddings, hidden states, raw logits and decoder score tensors are not captured in this version. Raw textual decoder tokens and musical annotations are retained.

## Colab, privacy and recovery

The web server binds only to loopback and is displayed through Colab's authenticated iframe proxy. There is **no public share URL for a running session**. Share the notebook or this repository so others can run their own copies.

Audio is uploaded to and processed on the user's Google Colab runtime. Model weights download from Hugging Face / Meta; this project does not upload audio to GitHub or an inference API. Runtime storage is temporary. Session ZIPs include the excerpt and its derived audio, so treat a downloaded ZIP as containing your recording.

- Upload limit: **200 MB**, **1 second to 12 minutes**. Trim longer recordings before upload.
- Cancel stops the worker and releases its GPU memory. Already completed inputs remain accessible.
- Retry resumes unfinished inputs with the same configuration, reusing saved separated audio on the same runtime.
- A fresh configuration starts a new experiment; upload again. Completed runs appear under **Previous sessions**.
- Download the ZIP **before** resetting/disconnecting. If the runtime is deleted, only your downloaded files survive.
- If a model is gated, accept its access conditions on Hugging Face and add `HF_TOKEN` as a Colab Secret. Never paste tokens into notebook cells. Restart the server/runtime after changing secrets.
- If a browser blocks iframe downloads, use the notebook's optional download cell.

## Reopen a downloaded session

Unzip the session, run:

```bash
python3 serve.py
```

Open `http://localhost:8000`. Python's standard library is sufficient. The bundled server supports audio byte-range requests for seeking. Opening `index.html` directly as a `file://` URL is not supported.

## Local development

For the web service and tests (Python 3.11 + FFmpeg):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m stemscore.server
# http://127.0.0.1:8766
```

Actual inference requires a CUDA GPU, the model dependencies in `requirements-model.txt`, PyTorch/torchaudio 2.8.0, and Demucs 4.0.1. See `scripts/colab_setup.py` for the supported isolated install. Demucs is installed without dependency resolution to avoid its older torchaudio constraint replacing the model's pinned torch stack. This application uses its tensor separation API.

```bash
pip install pytest==8.3.5 httpx==0.28.1
python -m pytest
node --test tests/*.test.js
```

The notebook installs the current repository checkout in a fresh runtime; an existing checkout is preserved on rerun. To pick up code updates, use a fresh runtime or deliberately update the checkout after downloading results. The model and custom model code are pinned to revision `cafc0df1021e14f49e928c4b345f5959d414ef64`.

## Validation

Verified on a Colab Tesla T4 with an isolated Python 3.11 install: generated 12-second audio → four Demucs stems → five independent SheetSage2 inputs, including a custom bass + other mix → synchronized scores and exports. To repeat this execution check after launch, run `/content/stem-score-env/bin/python scripts/smoke_gpu.py` from the repository. It is not a transcription accuracy benchmark.

The local suite includes 21 Python and 6 JavaScript checks for input validation, cancellation, partial-result preservation, safe exports, audio seeking, empty predictions, grid-boundary notes, source overlap and raw stream lookup. Browser checks cover multi-score playback, note highlighting, seeking, soloing and a downloaded session reopened without the inference server.

## Credits and licenses

Independent community experiment; not an official YuE2 / M·A·P product.

- [SheetSage2 / M·A·P](https://huggingface.co/m-a-p/SheetSage2): lead-sheet transcription and timed annotations. Model weights are **CC BY-NC 4.0**; review the upstream terms for your use. The upstream Python code is downloaded, not vendored here.
- [Demucs / Meta](https://github.com/facebookresearch/demucs): four-source separation, `htdemucs` / Demucs 4.0.1. MIT.
- [abcjs](https://paulrosen.github.io/abcjs/): notation rendering, version 6.7.1. Bundled with its MIT license in `web/vendor/LICENSE.md`.

Original application code is MIT licensed. That license does not change model licenses or rights in audio that users upload. This repository contains no bundled commercial songs, model weights, user results, or credentials.
