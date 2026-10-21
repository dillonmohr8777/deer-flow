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
    args = parser.parse_args()
    root = args.root.resolve()
    source, ref = root / 'scripts' / (args.only + '.json'), root / 'ref.wav'
    directory = ensure_generation(root, source, ref)
    # Imports follow acceptance/HOLD validation, so rejected jobs never load weights.
    import mlx.core as mx
    import numpy as np
    import soundfile as sf
    from f5_tts_mlx.cfm import F5TTS
    from f5_tts_mlx.generate import generate
    model = F5TTS.from_pretrained(SETTINGS['model'])
    F5TTS.from_pretrained = classmethod(lambda cls, *a, **kw: model)
    reference_seconds = sf.info(ref).duration
    lesson = json.loads(source.read_text())
    records, waveforms, cursor = [], [], 0.0
    for chapter_index, chapter in enumerate(lesson['chapters']):
        chapter_start = cursor
        for part_index, text in enumerate(chunks(chapter['narration'])):
            assert_running(root)  # Safe sentence boundary; prior files remain complete.
            key = f'{chapter_index:02d}-{part_index:02d}'
            binding = dict(text=text, settings=SETTINGS, reference_sha256=sha(ref), reference_text=REF_TEXT)
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
                generate(text, duration=reference_seconds + len(text.split()) / SETTINGS['words_per_second'] + SETTINGS['duration_allowance'],
                         ref_audio_path=str(ref), ref_audio_text=REF_TEXT, steps=SETTINGS['steps'],
                         method=SETTINGS['method'], seed=SETTINGS['seed'], output_path=str(partial))
                samples, rate = sf.read(partial)
                assert rate == 24000 and len(samples) > 24000 and np.isfinite(samples).all(), 'Invalid generated audio'
                partial.replace(target)
                atomic_json(receipt, dict(binding=binding, sha256=sha(target), generation=SETTINGS))
            samples, rate = sf.read(target)
            assert rate == 24000 and len(samples) > 24000 and np.isfinite(samples).all()
            duration = len(samples) / rate
            records.append(dict(chapter=chapter_index, part=part_index, title=chapter['title'], text=text,
                                start=cursor, duration=duration, wav=target.name, sha256=sha(target)))
            waveforms.extend([samples, np.zeros(round(24000 * SETTINGS['pause']))])
            cursor += duration + SETTINGS['pause']
            # Only this script's exact prefix is checkpointed, never a merge with stale rows.
            atomic_json(directory / 'timing.json', records)
            print(json.dumps(dict(lesson=source.stem, chapter=chapter_index, chunk=part_index,
                                  seconds=round(duration, 3), wall=round(time.monotonic()-started, 2))), flush=True)
            mx.clear_cache()
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
