"""Checkpointed offline Dillon-voice narration from reviewed chapter JSON."""
import argparse
import json
import re
import time
from pathlib import Path

import mlx.core as mx
import numpy as np
import soundfile as sf
from f5_tts_mlx.cfm import F5TTS
from f5_tts_mlx.generate import generate
from validation import atomic_json

REF_TEXT = 'Is this enough for you to be able to use my voice? Nice and deep, slow, relaxed, but knowledgeable.'


def chunks(text, maximum=30):
    result = []
    for sentence in re.split(r'(?<=[.!?])\s+', text.strip()):
        words = sentence.split()
        result.extend(' '.join(words[start:start + maximum])
                      for start in range(0, len(words), maximum))
    assert result and all(len(item.split()) <= maximum for item in result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('scripts', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--ref', type=Path, required=True)
    parser.add_argument('--only')
    parser.add_argument('--limit-chapters', type=int)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    # Keep one model resident; the upstream convenience helper reloads each call.
    model = F5TTS.from_pretrained('lucasnewman/f5-tts-mlx')
    F5TTS.from_pretrained = classmethod(lambda cls, *a, **kw: model)
    reference_seconds = sf.info(args.ref).duration
    for source in sorted(args.scripts.glob('*.json')):
        if args.only and not source.stem.startswith(args.only):
            continue
        lesson = json.loads(source.read_text())
        directory = args.output / source.stem
        directory.mkdir(exist_ok=True)
        known = {item['wav']: item['text'] for item in json.loads(
            (directory / 'timing.json').read_text())} if (directory / 'timing.json').exists() else {}
        checkpoint = {item["wav"]: item for item in json.loads((directory / "timing.json").read_text())} if (directory / "timing.json").exists() else {}
        records, waveforms, cursor = [], [], 0.0
        for chapter_index, chapter in enumerate(lesson['chapters'][:args.limit_chapters]):
            chapter_start = cursor
            for part_index, text in enumerate(chunks(chapter['narration'])):
                target = directory / f'{chapter_index:02d}-{part_index:02d}.wav'
                started = time.monotonic()
                if target.exists():
                    sidecar = target.with_suffix('.json')
                    recorded = known.get(target.name) or (json.loads(sidecar.read_text())['text'] if sidecar.exists() else None)
                    assert recorded == text, f'Changed text: preserve and regenerate {target}'
                if not target.exists():
                    atomic_json(target.with_suffix('.json'), {'text': text})
                    generate(text, duration=reference_seconds + len(text.split()) / 2.5 + .3,
                             ref_audio_path=str(args.ref), ref_audio_text=REF_TEXT,
                             steps=32, method='euler', seed=7, output_path=str(target))
                samples, rate = sf.read(target)
                assert rate == 24000 and len(samples) > 24000 and np.isfinite(samples).all()
                duration = len(samples) / rate
                records.append(dict(chapter=chapter_index, title=chapter['title'], text=text,
                                    start=cursor, duration=duration, wav=target.name))
                waveforms.extend([samples, np.zeros(8400)])
                cursor += duration + .35
                checkpoint[target.name] = records[-1]
                atomic_json(directory / 'timing.json', list(checkpoint.values()))
                print(json.dumps(dict(lesson=source.stem, chapter=chapter_index, chunk=part_index,
                                      seconds=round(duration, 3), wall=round(time.monotonic()-started, 2))), flush=True)
                mx.clear_cache()
            chapter['start'], chapter['duration'] = chapter_start, cursor - chapter_start
        sf.write(directory / 'narration.wav', np.concatenate(waveforms), 24000)
        lesson['duration'] = cursor
        atomic_json(directory / 'lesson.json', lesson)
        print(f'COMPLETE {source.stem} {cursor:.3f}s', flush=True)


if __name__ == '__main__':
    main()
