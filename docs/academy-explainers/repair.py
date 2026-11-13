"""At most two targeted repair passes; original sentence versions never change."""
import argparse
import difflib
import json
from pathlib import Path
from contract import require_course, REF_TEXT, SETTINGS, sha, digest, assert_running
from validation import atomic_json
from transcribe import normalize


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    parser.add_argument('--attempt', type=int, choices=[1, 2], required=True)
    args = parser.parse_args()
    directory = args.directory
    provenance, _ = require_course(directory)
    root = Path(provenance['evidence_root'])
    attempt_file = directory / f'repair-{args.attempt}.json'
    prior = json.loads(attempt_file.read_text()) if attempt_file.exists() else None
    assert not prior or prior.get('status') != 'complete', 'Repair attempt already completed; inspect its receipt'
    records = json.loads((directory / 'timing.json').read_text())
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
    assert 0 < len(affected) <= 12, 'Refusing broad patch generation; inspect narration'
    # Consumed before generation: interrupted attempts are visible and never silently replayed.
    if prior:
        assert prior['affected'] == sorted(affected), 'Changed repair target; preserve attempt and review'
    else:
        atomic_json(attempt_file, dict(status='started', affected=sorted(affected)))
    import soundfile as sf
    import numpy as np
    from f5_tts_mlx.cfm import F5TTS
    from f5_tts_mlx.generate import generate
    model = F5TTS.from_pretrained(SETTINGS['model'])
    F5TTS.from_pretrained = classmethod(lambda cls, *a, **kw: model)
    ref = root / 'ref.wav'
    completed = list(prior.get('completed', [])) if prior else []
    for index in sorted(affected):
        assert_running(root)
        row = records[index]
        base_binding = dict(text=row['text'], settings=SETTINGS, reference_sha256=sha(ref), reference_text=REF_TEXT)
        generation = dict(SETTINGS, method='rk4', seed=7 if args.attempt == 1 else 11,
                          extra_allowance=1.3 if len(row['text'].split()) <= 10 else .6)
        key = f'{row["chapter"]:02d}-{row["part"]:02d}'
        target = directory / (key + '-repair-' + digest(generation)[:12] + '.wav')
        if target.name in completed:
            assert target.exists() and json.loads(target.with_suffix('.json').read_text())['sha256'] == sha(target), 'Changed completed repair'
            continue
        if target.exists() and target.with_suffix('.json').exists():
            receipt = json.loads(target.with_suffix('.json').read_text())
            assert receipt['sha256'] == sha(target) and receipt['binding'] == base_binding, 'Changed immutable repair'
            atomic_json(directory / (key + '.selected.json'), dict(binding=base_binding, wav=target.name))
            completed.append(target.name)
            continue
        assert not target.exists(), 'Unreceipted repair preserved for inspection'
        partial = directory / (target.stem + '.pending.wav')
        generate(row['text'], duration=sf.info(ref).duration + len(row['text'].split()) / 2.5 + .3 + generation['extra_allowance'],
                 ref_audio_path=str(ref), ref_audio_text=REF_TEXT, steps=32,
                 method=generation['method'], seed=generation['seed'], output_path=str(partial))
        samples, rate = sf.read(partial)
        assert rate == 24000 and len(samples) > 24000 and np.isfinite(samples).all()
        partial.replace(target)
        atomic_json(target.with_suffix('.json'), dict(binding=base_binding, generation=generation, sha256=sha(target)))
        atomic_json(directory / (key + '.selected.json'), dict(binding=base_binding, wav=target.name))
        completed.append(target.name)
        atomic_json(attempt_file, dict(status='running', affected=sorted(affected), completed=completed))
    atomic_json(attempt_file, dict(status='complete', affected=sorted(affected), completed=completed,
                                 audio_review='Sampler changed; parent must listen for voice and seam quality.'))


if __name__ == '__main__':
    main()
