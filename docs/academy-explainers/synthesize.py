"""One offline model, immutable sentence versions, atomic complete audio receipts."""
import argparse
import json
import re
import time
from pathlib import Path
from contract import REF_TEXT, SETTINGS, assert_running, ensure_generation, digest, sha
from validation import atomic_json


def chunks(text, maximum=30):
    result = []
    for sentence in re.split(r'(?<=[.!?])\s+', text.strip()):
        words = sentence.split()
        result.extend(' '.join(words[start:start + maximum]) for start in range(0, len(words), maximum))
    assert result and all(len(item.split()) <= maximum for item in result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--only', required=True, help='Exact accepted source stem')
    parser.add_argument('--backend', choices=['mlx', 'cpu'], default='mlx')
    args = parser.parse_args()
    root = args.root.resolve()
    source, ref = root / 'scripts' / (args.only + '.json'), root / 'ref.wav'
    settings = dict(SETTINGS)
    if args.backend == 'cpu':
        settings.update(engine='pytorch-cpu', model='F5TTS_v1_Base', threads=2, f5_tts_version='1.1.22',
            cfg_strength=2, sway_sampling_coef=-1, target_rms=.1, cross_fade_duration=.15, use_ema=True,
            vocoder_sha256='97ec976ad1fd67a33ab2682d29c0ac7df85234fae875aefcc5fb215681a91b2a',
            checkpoint_sha256='670900fd14e6c458b95da6e9ed317cdb20dbaf7a1c02ac06a05475a9d32b6a38')
    directory = ensure_generation(root, source, ref, settings)
    # Imports follow acceptance/HOLD validation, so rejected jobs never load weights.
    import numpy as np
    import soundfile as sf
    if args.backend == 'mlx':
        import mlx.core as mx
        from f5_tts_mlx.cfm import F5TTS
        from f5_tts_mlx.generate import generate
        model = F5TTS.from_pretrained(settings['model'])
        F5TTS.from_pretrained = classmethod(lambda cls, *a, **kw: model)
    else:
        import os, shutil
        os.environ.update(OMP_NUM_THREADS='2', MKL_NUM_THREADS='2', HF_HUB_OFFLINE='1', WANDB_MODE='disabled', HF_HUB_DISABLE_TELEMETRY='1')
        assert shutil.disk_usage('/mnt/c').free >= 10*1024**3, 'Host disk floor'
        import torch
        torch.set_num_threads(2)
        torch.set_num_interop_threads(2)
        from f5_tts.api import F5TTS
        checkpoint = root / 'models/F5-TTS/F5TTS_v1_Base/model_1250000.safetensors'
        assert sha(checkpoint) == settings['checkpoint_sha256'], 'Wrong official checkpoint'
        assert sha(root / 'models/vocos-mel-24khz/pytorch_model.bin') == settings['vocoder_sha256'], 'Wrong vocoder'
        model = F5TTS(model=settings['model'], ckpt_file=str(checkpoint), device='cpu', ode_method='euler',
                      vocoder_local_path=str(root / 'models/vocos-mel-24khz'))
        def generate(text, duration, ref_audio_path, ref_audio_text, steps, method, seed, output_path):
            assert method == 'euler', 'CPU sampler must remain bound to its receipt'
            model.infer(ref_file=ref_audio_path, ref_text=ref_audio_text, gen_text=text, nfe_step=steps,
                        seed=seed, fix_duration=duration, file_wave=output_path, remove_silence=False,
                        cfg_strength=settings['cfg_strength'], sway_sampling_coef=settings['sway_sampling_coef'],
                        target_rms=settings['target_rms'], cross_fade_duration=settings['cross_fade_duration'])
    reference_seconds = sf.info(ref).duration
    lesson = json.loads(source.read_text())
    records, waveforms, cursor = [], [], 0.0
    for chapter_index, chapter in enumerate(lesson['chapters']):
        chapter_start = cursor
        for part_index, text in enumerate(chunks(chapter['narration'])):
            assert_running(root)  # Safe sentence boundary; prior files remain complete.
            key = f'{chapter_index:02d}-{part_index:02d}'
            binding = dict(text=text, settings=settings, reference_sha256=sha(ref), reference_text=REF_TEXT)
            # Completed repairs are immutable versions selected by a hash-bound pointer.
            pointer = directory / (key + '.selected.json')
            selected = json.loads(pointer.read_text()) if pointer.exists() else None
            if selected:
                assert selected['binding'] == binding, 'Stale selected chunk'
                target = directory / selected['wav']
            else:
                target = directory / (key + '-' + digest(binding)[:12] + '.wav')
            receipt = target.with_suffix('.json')
            started = time.monotonic()
            valid = target.exists() and receipt.exists()
            if valid:
                metadata = json.loads(receipt.read_text())
                assert metadata['binding'] == binding and metadata['sha256'] == sha(target), 'Changed or incomplete chunk'
            else:
                assert not target.exists(), 'Unreceipted original preserved; choose a new version before retry'
                partial = directory / (target.stem + '.pending.wav')
                generate(text, duration=reference_seconds + len(text.split()) / settings['words_per_second'] + settings['duration_allowance'],
                         ref_audio_path=str(ref), ref_audio_text=REF_TEXT, steps=settings['steps'],
                         method=settings['method'], seed=settings['seed'], output_path=str(partial))
                samples, rate = sf.read(partial)
                assert rate == 24000 and len(samples) > 24000 and np.isfinite(samples).all(), 'Invalid generated audio'
                partial.replace(target)
                atomic_json(receipt, dict(binding=binding, sha256=sha(target), generation=settings))
            samples, rate = sf.read(target)
            assert rate == 24000 and len(samples) > 24000 and np.isfinite(samples).all()
            duration = len(samples) / rate
            records.append(dict(chapter=chapter_index, part=part_index, title=chapter['title'], text=text,
                                start=cursor, duration=duration, wav=target.name, sha256=sha(target)))
            waveforms.extend([samples, np.zeros(round(24000 * settings['pause']))])
            cursor += duration + settings['pause']
            # Only this script's exact prefix is checkpointed, never a merge with stale rows.
            atomic_json(directory / 'timing.json', records)
            print(json.dumps(dict(lesson=source.stem, chapter=chapter_index, chunk=part_index,
                                  seconds=round(duration, 3), wall=round(time.monotonic()-started, 2))), flush=True)
            if args.backend == 'mlx':
                mx.clear_cache()
            else:
                assert shutil.disk_usage('/mnt/c').free >= 10*1024**3, 'Host disk floor'
        chapter['start'], chapter['duration'] = chapter_start, cursor - chapter_start
    assert_running(root)
    temporary = directory / 'narration.pending.wav'
    sf.write(temporary, np.concatenate(waveforms), 24000)
    temporary.replace(directory / 'narration.wav')
    lesson.update(duration=cursor, course_stem=source.stem, course='momentum-work')
    atomic_json(directory / 'lesson.json', lesson)
    print(f'COMPLETE {source.stem} {cursor:.3f}s', flush=True)


if __name__ == '__main__':
    main()
