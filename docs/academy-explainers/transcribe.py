"""Independent offline narration check and word timing; preserve raw ASR."""
import argparse
import difflib
import json
import re
from pathlib import Path

from contract import require_course, duration_ok
from validation import atomic_json, fingerprints, timing_errors

NUMBERS = dict(zip(
    'zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split(),
    map(str, range(20))))
TENS = dict(zip('twenty thirty forty fifty sixty seventy eighty ninety'.split(), range(20, 100, 10)))


def normalize(text):
    text = text.lower().replace('momo bot', 'momobot').replace('file name', 'filename')
    text = text.replace('momobot dot needmomentum dot com', 'momobot needmomentum com')
    for letters, command in [('p w d', 'pwd'), ('l s', 'ls'), ('c d', 'cd'), ('m k d i r', 'mkdir')]:
        text = re.sub(r'\b' + letters.replace(' ', r'\s*') + r'\b', command, text)
    text = text.replace('’', "'")
    for contraction, expanded in {"let's": 'let us', "don't": 'do not', "can't": 'cannot', "isn't": 'is not', "doesn't": 'does not', "won't": 'will not', "shouldn't": 'should not', "aren't": 'are not', "wasn't": 'was not', "didn't": 'did not', "couldn't": 'could not', "wouldn't": 'would not', "hasn't": 'has not', "haven't": 'have not'}.items():
        text = text.replace(contraction, expanded)
    for name, value in TENS.items():
        for unit, number in list(NUMBERS.items())[1:10]:
            text = re.sub(rf'\b{name}[ -]{unit}\b', str(value + int(number)), text)
        text = re.sub(rf'\b{name}\b', str(value), text)
    for name, value in NUMBERS.items():
        text = re.sub(rf'\b{name}\b', value, text)
    return [word for word in re.findall(r'[a-z0-9]+', text) if word not in ('dollar', 'dollars')]


def critical_differences(differences):
    protected = {'not', 'no', 'never', 'without', 'cannot', 'only', 'before', 'after'}
    return [row for row in differences if any(token in protected or any(c.isdigit() for c in token)
            for token in normalize(row['expected']) + normalize(row['heard']))]


def check(directory):
    require_course(directory)
    import mlx_whisper
    atomic_json(directory / 'ASR-RUNNING.json', {'status': 'checking'})
    lesson = json.loads((directory / 'lesson.json').read_text())
    result = mlx_whisper.transcribe(str(directory / 'narration.wav'),
        path_or_hf_repo='mlx-community/whisper-large-v3-turbo', language='en',
        word_timestamps=True, temperature=0, condition_on_previous_text=False,
        hallucination_silence_threshold=.5)
    raw = directory / f'asr-raw-{__import__("time").time_ns()}.json'
    atomic_json(raw, result)
    # Whisper can hallucinate hundreds of words in a trailing fraction of a second.
    # Preserve that raw output; impossible-rate segments cannot be spoken captions.
    removed, segments = [], []
    for segment in result['segments']:
        rate = len(segment['text'].split()) / max(.01, segment['end'] - segment['start'])
        (removed if rate > 8 else segments).append(segment)
    result['segments'] = segments
    result['text'] = ' '.join(segment['text'] for segment in segments)
    atomic_json(directory / 'asr.json', result)
    expected = normalize(' '.join(c['narration'] for c in lesson['chapters']))
    actual = normalize(result['text'])
    matcher = difflib.SequenceMatcher(None, expected, actual, autojunk=False)
    differences = [dict(kind=op, expected=' '.join(expected[i:j]), heard=' '.join(actual[k:l]), expected_start=i, expected_end=j)
                   for op, i, j, k, l in matcher.get_opcodes() if op != 'equal']
    matched = sum(block.size for block in matcher.get_matching_blocks())
    report = dict(duration=lesson['duration'], expected_tokens=len(expected),
                  heard_tokens=len(actual), matched_tokens=matched,
                  coverage=matched / len(expected), alignment=matcher.ratio(),
                  impossible_rate_asr_segments=len(removed), differences=differences)
    report['timing_errors'] = timing_errors(result, lesson['duration'])
    report['sha256'] = fingerprints(directory)
    report['critical_differences'] = critical_differences(differences)
    report['raw_asr'] = raw.name
    report['identity_note'] = 'ASR checks spoken content, not speaker identity. Authorized reference provenance and actual audio review are separate.'
    report['structural_pass'] = report['coverage'] >= .995 and report['alignment'] >= .99 and duration_ok(lesson) and not report['timing_errors']
    report['needs_audio_judgment'] = bool(differences) and not report['critical_differences'] and all(row['kind'] == 'replace' and len(row['expected'].split()) == len(row['heard'].split()) == 1 for row in differences)
    report['pass'] = report['structural_pass'] and not differences
    # A reviewed ASR homophone can be accepted without pretending raw ASR was exact.
    judgment = directory / 'audio-judgment.json'
    if judgment.exists():
        value = json.loads(judgment.read_text())
        report['audio_judgment'] = value
        report['pass'] = report['structural_pass'] and value.get('accepted') is True and value.get('sha256') == report['sha256'] and value.get('differences') == differences and bool(value.get('reviewer')) and bool(value.get('note'))
    atomic_json(directory / 'voice-check.json', report)
    (directory / 'ASR-RUNNING.json').replace(directory / 'ASR-LAST-RUN.json')
    print(directory.name, json.dumps(report), flush=True)
    return report['pass']


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    assert check(args.directory), 'Narration review required; see voice-check.json'
