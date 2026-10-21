# MomoBot Academy teaching series

Seven ten-chapter lessons, each with 5–6 minutes of Dillon-authorized own-voice narration, practical visual examples, independent ASR, and WebVTT captions. Keep these lessons separate from the short-film example library.

## Reproduce

Use the existing cached F5-TTS MLX environment on Apple Silicon, offline. The authorized voice reference is a protected local input and is intentionally not in Git. F5 0.2.6 on MLX 0.32.4 needs integer duration tensors in cfm.py: cast per-example dur with int(dur), and mx.full duration with dtype=mx.int32. No model downloads are required when caches exist.

1. Read disk/RAM guard status. Synthesize one process only: `HF_HUB_OFFLINE=1 python synthesize.py scripts OUTPUT --ref AUTHORIZED_REF.wav`.
2. `HF_HUB_OFFLINE=1 python transcribe.py OUTPUT`. Each voice-check binds audio, lesson, and ASR SHA-256. All lessons must be 300–360 seconds, coverage >=99.5%, alignment >=99%, with valid word timing. Review every mismatch; repair real lost words before promotion. Raw ASR and rejected audio remain in evidence.
3. `python build.py OUTPUT PROJECTS ASSETS`. Assets require exact transparent Momo mark, Archivo Black, Nunito Sans, local GSAP, and the current verified Experience screenshot.
4. Run HyperFrames 0.8.61 `check --snapshots` per project; inspect frames and preview before final render. Stream final MP4 on the Windows worker; do not create a full PNG frame set or render on the memory-constrained Mac.
5. Probe all exports, compare actual durations, inspect sampled frames/audio and verify captions in the consuming HTML video player before publication. Parent session owns integration and destination acceptance.

## Checks

`python -m unittest discover -s . -p 'test_*.py'`

`python -m py_compile synthesize.py transcribe.py build.py validation.py`

Production evidence and media: `/Users/dillonmohr/Documents/Codex/2026-10-21/momobot-prod-readiness/academy-explainers/`.

No client material, new model download, paid generation, external messages, or hosting mutation is required by this source package. Narrations are generic personal examples; source scripts do not promise connectors or capabilities that have not been verified.
