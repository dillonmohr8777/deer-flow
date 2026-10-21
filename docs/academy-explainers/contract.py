"""Small, deterministic contract for this Momentum work course."""
import hashlib
import json
from pathlib import Path
from validation import atomic_json

REF_TEXT = 'Is this enough for you to be able to use my voice? Nice and deep, slow, relaxed, but knowledgeable.'
SETTINGS = dict(model='lucasnewman/f5-tts-mlx', steps=32, method='euler', seed=7,
                words_per_second=2.5, duration_allowance=.3, pause=.35, sample_rate=24000)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def assert_running(root):
    root = Path(root)
    assert not (root / 'HOLD.json').exists(), f'Production held: {root / "HOLD.json"}'


def accepted_sources(root):
    """Parent supplies this exact, hash-bound acceptance file after factual review."""
    root = Path(root)
    assert_running(root)
    path = root / 'SCRIPT-ACCEPTED.json'
    assert path.is_file(), f'Awaiting parent script acceptance: {path}'
    packet = json.loads(path.read_text())
    assert packet.get('accepted') is True and packet.get('course') == 'momentum-work', 'Wrong course acceptance'
    rows = packet.get('lessons', [])
    assert 1 <= len(rows) <= 17, 'Acceptance must list exact lessons'
    stems = [row['stem'] for row in rows]
    assert len(stems) == len(set(stems)), 'Duplicate accepted stem'
    output = []
    for row in rows:
        source = root / 'scripts' / (row['stem'] + '.json')
        assert source.is_file() and sha(source) == row['sha256'], f'Unaccepted source: {source}'
        output.append(source)
    return output, packet


def identity(source, ref, settings=None):
    return dict(source_sha256=sha(source), reference_sha256=sha(ref),
                reference_text=REF_TEXT, settings=settings or SETTINGS)


def voice_directory(root, source, ref, settings=None):
    binding = identity(source, ref, settings)
    return Path(root) / 'voice-sentences' / source.stem / digest(binding)[:16], binding


def duration_ok(lesson):
    duration = lesson['duration']
    return 480 <= duration < 600 if lesson.get('course_stem', '').startswith('00-') else 300 <= duration <= 360


def require_course(directory):
    directory = Path(directory)
    provenance = json.loads((directory / 'generation.json').read_text())
    root = Path(provenance['evidence_root'])
    sources, packet = accepted_sources(root)
    source = root / 'scripts' / (provenance['stem'] + '.json')
    assert source in sources and sha(source) == provenance['binding']['source_sha256'], 'Stale narration source'
    assert sha(root / 'ref.wav') == provenance['binding']['reference_sha256'] == packet.get('reference_sha256'), 'Changed or unaccepted voice reference'
    assert digest(provenance['binding'])[:16] == directory.name, 'Wrong generation directory'
    return provenance, packet


def ensure_generation(root, source, ref, settings=None):
    sources, packet = accepted_sources(root)
    assert sha(ref) == packet.get('reference_sha256'), 'Unaccepted voice reference'
    assert source in sources, 'Only accepted exact stems may synthesize'
    directory, binding = voice_directory(root, source, ref, settings)
    directory.mkdir(parents=True, exist_ok=True)
    value = dict(stem=source.stem, evidence_root=str(Path(root).resolve()), binding=binding)
    path = directory / 'generation.json'
    if path.exists():
        assert json.loads(path.read_text()) == value, 'Generation identity collision'
    else:
        atomic_json(path, value)
    return directory
