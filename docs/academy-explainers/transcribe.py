"""Independent offline narration check and word timing; preserve raw ASR."""
import argparse
import difflib
import json
import re
from pathlib import Path

import mlx_whisper
from validation import atomic_json, fingerprints, timing_errors

NUMBERS = dict(zip(
    'zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split(),
    map(str, range(20))))
TENS = dict(zip('twenty thirty forty fifty sixty seventy eighty ninety'.split(), range(20, 100, 10)))


def normalize(text):
    text = text.lower().replace('momo bot', 'momobot')
    for letters, command in [('p w d', 'pwd'), ('l s', 'ls'), ('c d', 'cd'), ('m k d i r', 'mkdir')]:
        text = re.sub(r'\b' + letters.replace(' ', r'\s*') + r'\b', command, text)
    text = text.replace("let's", 'let us').replace("don't", 'do not').replace("can't", 'cannot')
    for name, value in TENS.items():
        for unit, number in list(NUMBERS.items())[1:10]:
            text = re.sub(rf'\b{name}[ -]{unit}\b', str(value + int(number)), text)
        text = re.sub(rf'\b{name}\b', str(value), text)
    for name, value in NUMBERS.items():
        text = re.sub(rf'\b{name}\b', value, text)
    return [word for word in re.findall(r'[a-z0-9]+', text) if word not in ('dollar', 'dollars')]


def check(directory):
    atomic_json(directory / 'voice-check.json', {'pass': False, 'status': 'checking'})
    lesson = json.loads((directory / 'lesson.json').read_text())
    result = mlx_whisper.transcribe(str(directory / 'narration.wav'),
        path_or_hf_repo='mlx-community/whisper-large-v3-turbo', language='en',
        word_timestamps=True, temperature=0, condition_on_previous_text=False,
        hallucination_silence_threshold=.5)
    (directory / 'asr-raw.json').write_text(json.dumps(result, indent=2))
    # Whisper can hallucinate hundreds of words in a trailing fraction of a second.
    # Preserve that raw output; impossible-rate segments cannot be spoken captions.
    removed, segments = [], []
    for segment in result['segments']:
        rate = len(segment['text'].split()) / max(.01, segment['end'] - segment['start'])
        (removed if rate > 8 else segments).append(segment)
    result['segments'] = segments
    result['text'] = ' '.join(segment['text'] for segment in segments)
    (directory / 'asr.json').write_text(json.dumps(result, indent=2))
    expected = normalize(' '.join(c['narration'] for c in lesson['chapters']))
    actual = normalize(result['text'])
    matcher = difflib.SequenceMatcher(None, expected, actual, autojunk=False)
    differences = [dict(kind=op, expected=' '.join(expected[i:j]), heard=' '.join(actual[k:l]))
                   for op, i, j, k, l in matcher.get_opcodes() if op != 'equal']
    matched = sum(block.size for block in matcher.get_matching_blocks())
    report = dict(duration=lesson['duration'], expected_tokens=len(expected),
                  heard_tokens=len(actual), matched_tokens=matched,
                  coverage=matched / len(expected), alignment=matcher.ratio(),
                  impossible_rate_asr_segments=len(removed), differences=differences)
    report['timing_errors'] = timing_errors(result, lesson['duration'])
    report['sha256'] = fingerprints(directory)
    report['pass'] = report['coverage'] >= .995 and report['alignment'] >= .99 and 300 <= lesson['duration'] <= 360 and not report['timing_errors']
    atomic_json(directory / 'voice-check.json', report)
    print(directory.name, json.dumps(report), flush=True)
    return report['pass']


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('voice', type=Path)
    parser.add_argument('--only')
    args = parser.parse_args()
    verdicts = [check(source.parent) for source in sorted(args.voice.glob('*/lesson.json'))
                if not args.only or source.parent.name.startswith(args.only)]
    assert verdicts and all(verdicts), 'Narration review required; see voice-check.json'
