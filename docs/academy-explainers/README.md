# Momentum Academy work course

The corrected course covers sixteen initial lessons: four foundations, ten work-role families and two growth lessons. A seventeenth client-communication module follows verified working portal UI. The platform tour is480–<600seconds; all other lessons are300–360seconds. These are work lessons with concrete synthetic records and exercises. The original seven generic lessons and their media remain held and preserved as engine evidence, never promoted as this course.

`work-visuals.json` holds173 concrete teaching boards. The parent owns factual script acceptance, Academy UI/progress compatibility, private media hosting and production release. This branch owns only `docs/academy-explainers/`.

## Accepted inputs and production

Use a new evidence root with `scripts/<exact-stem>.json`, protected `ref.wav`, exact brand `assets/`, and parent-written `SCRIPT-ACCEPTED.json`:

```json
{"accepted":true,"course":"momentum-work","course_total":16,"lessons":[{"stem":"04-account-client-success","sha256":"exact-script-file-sha256"}]}
```

Partial acceptance may list fewer than the total course. It authorizes only the exact listed bytes. A missing acceptance file or `HOLD.json` stops generation before any model import. Old generic evidence remains separate.

1. Read disk/RAM guard status and coordinate the existing storage owner. One model process only. The existing cached Apple Silicon environment uses F5-TTS MLX offline. `cpu-setup.ps1` is the separately authorized Windows CPU fallback setup, with a6GiB setup budget and10GiB free-space floor. No CUDA, purchases or concurrent CPU voice/render jobs.
2. `HF_HUB_OFFLINE=1 EXISTING_PYTHON synthesize.py ROOT --only EXACT_STEM` generates immutable sentence versions. Source hash, authorized reference hash/transcript and synthesis settings determine a generation directory. WAV files and complete receipts publish atomically. Changed scripts or settings cannot inherit old chunks. Originals stay intact.
3. `HF_HUB_OFFLINE=1 EXISTING_PYTHON transcribe.py GENERATION_DIRECTORY` preserves raw ASR, rejects incomplete timed-word tracks and reports every word difference. Missing negations, numbers and other protected instruction tokens cannot hide beneath a coverage tolerance. Actual omitted words require repair. Harmless ASR differences require a source-bound `audio-judgment.json` by an outside reviewer who listened; ASR does not prove speaker identity.
4. Initial generation plus at most two targeted repair passes. Repairs write new versions and selection pointers, preserving originals and exact sampler/seed metadata. Interrupted checks retain their last complete receipt and an explicit incomplete marker that blocks promotion.
5. `python build.py ROOT/voice-sentences ROOT/projects ROOT/assets` builds accepted compositions. Captions are sidecar WebVTT by default; `--burn-captions` is explicit. Variable chapter counts and actual accepted course total drive labels. Assets are exact transparent Momo mark, Archivo Black, Nunito Sans, local GSAP and inspected Experience screenshot.
6. The finite `produce.py ROOT --python EXISTING_PYTHON` job stages only accepted exact stems to the sole PC queue. Its PID lock must be reconciled before a crashed run resumes. No new scheduler. Windows `render.ps1` rejects missing or mismatched projects before changing directories, checks HyperFrames, then exports4workers at15fps. The renderer's compressed capture scratch stays on PC; it is not a full PNG sequence or a claimed streaming path.
7. `verify.py VIDEO --evidence ROOT` checks real duration and audio/video streams, decodes audio, checks levels/silence, validates captions, samples every chapter, exports a poster and writes MP4/JPG/VTT/TXT hashes. These checks complement actual voice/content/frame review. Parent independently spot-plays, verifies caption CORS/textTracks and integrates privately.

The complete production command is finite and stops at PC staging; parent release and consumer acceptance remain separate. A staged archive is never described as a finished MP4.

## Focused checks

`python -m unittest discover -s docs/academy-explainers -p 'test_*.py' -v`

`python -m py_compile docs/academy-explainers/*.py`

New evidence: `/Users/dillonmohr/Documents/Codex/2026-10-21/momobot-prod-readiness/academy-work/`.

The authorized reference, narration, client data and model weights never enter Git. No public voice publication, Netlify deployment or external messages are part of this worker's scope.
