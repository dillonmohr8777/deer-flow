"""Repair only independently identified sentence mismatches, preserving originals."""
import argparse
import difflib
import json
import shutil
from pathlib import Path
import soundfile as sf
from synthesize import F5TTS, generate, REF_TEXT
from transcribe import normalize


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    parser.add_argument('--ref', type=Path, required=True)
    parser.add_argument('--attempt', type=int, choices=[1, 2], required=True)
    args = parser.parse_args()
    directory = args.directory
    records = json.loads((directory / 'timing.json').read_text())
    records.sort(key=lambda item: item['start'])
    expected, owners = [], []
    for index, record in enumerate(records):
        tokens = normalize(record['text'])
        expected.extend(tokens)
        owners.extend([index] * len(tokens))
    actual = normalize(json.loads((directory / 'asr.json').read_text())['text'])
    affected = set()
    for operation, i, j, k, l in difflib.SequenceMatcher(None, expected, actual, autojunk=False).get_opcodes():
        if operation != 'equal':
            affected.update(owners[i:j] or owners[max(0, i-1):i+1])
    assert len(affected) <= 12, 'Whole narration needs review; refusing broad patch generation'
    print(json.dumps([records[index] for index in sorted(affected)], indent=2), flush=True)
    if not affected:
        return
    model = F5TTS.from_pretrained('lucasnewman/f5-tts-mlx')
    F5TTS.from_pretrained = classmethod(lambda cls, *a, **kw: model)
    reference_seconds = sf.info(args.ref).duration
    for index in sorted(affected):
        row = records[index]
        target = directory / row['wav']
        backup = directory / (target.stem + f'-rejected-repair{args.attempt}.wav')
        assert not backup.exists(), f'Attempt already used: {backup}'
        shutil.copy2(target, backup)
        allowance = 1.3 if len(row['text'].split()) <= 10 else .6
        generate(row['text'], duration=reference_seconds + len(row['text'].split()) / 2.5 + .3 + allowance,
                 ref_audio_path=str(args.ref), ref_audio_text=REF_TEXT, steps=32,
                 method='rk4', seed=7 if args.attempt == 1 else 11, output_path=str(target))


if __name__ == '__main__':
    main()
