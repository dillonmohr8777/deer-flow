"""Content-bound receipts and caption timing checks shared by build and ASR."""
import hashlib
import json
import math
import re


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + '.pending')
    temporary.write_text(json.dumps(value, indent=2))
    temporary.replace(path)


def fingerprints(directory):
    return {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
            for name in ('narration.wav', 'lesson.json', 'asr.json')}


def timing_errors(asr, duration):
    words = [word for segment in asr['segments'] for word in segment.get('words', [])]
    errors = []
    previous = 0
    segment_text = re.findall(r"[a-z0-9]+", " ".join(s.get("text", "") for s in asr["segments"]).lower())
    timed_text = re.findall(r"[a-z0-9]+", " ".join(w.get("word", "") for w in words).lower())
    if segment_text != timed_text:
        errors.append("Timed words do not cover accepted segment text")
    if not words:
        return ['No word timestamps']
    for index, word in enumerate(words):
        start, end = word.get('start'), word.get('end')
        if not isinstance(start, (float, int)) or not isinstance(end, (float, int)):
            errors.append(f'word {index}: missing times')
            continue
        if not math.isfinite(start) or not math.isfinite(end) or not 0 <= start <= end <= duration + .05:
            errors.append(f'word {index}: invalid range')
        if start < previous - .05:
            errors.append(f'word {index}: nonmonotonic')
        previous = end
    if sum(word.get('end', 0) > word.get('start', 0) for word in words) / len(words) < .9:
        errors.append('More than ten percent of word times collapsed')
    return errors


def require_approved(directory):
    report = json.loads((directory / 'voice-check.json').read_text())
    assert report['pass'], 'Voice review gate'
    assert report.get('sha256') == fingerprints(directory), 'Voice receipt is stale'
    lesson = json.loads((directory / 'lesson.json').read_text())
    asr = json.loads((directory / 'asr.json').read_text())
    assert not timing_errors(asr, lesson['duration']), 'Caption timing gate'
