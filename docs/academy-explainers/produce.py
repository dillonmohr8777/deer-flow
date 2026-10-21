"""Finite accepted work-course queue; one sequential offline voice/ASR producer."""
import argparse
import json
import os
import time
from pathlib import Path
import subprocess
import zipfile
from build import build
from contract import accepted_sources, voice_directory, assert_running, sha
from validation import atomic_json

HERE = Path(__file__).parent
EXPORT_FILES = {'index.html', 'hyperframes.json', 'lesson.json', 'generation.json', 'captions.vtt', 'transcript.txt'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('evidence', type=Path)
    parser.add_argument('--python', type=Path, required=True, help='Existing offline F5/Whisper environment')
    parser.add_argument('--only', help='Exact accepted stem; default accepted list, tour first')
    parser.add_argument('--host', default='winpc')
    parser.add_argument('--remote-root', default='C:/MacTransfer/academy-work-20261021')
    args = parser.parse_args()
    root = args.evidence.resolve()
    sources, _ = accepted_sources(root)
    if args.only:
        sources = [source for source in sources if source.stem == args.only]
        assert len(sources) == 1, 'Unknown or ambiguous exact accepted stem'
    sources.sort(key=lambda source: source.stem)
    environment = dict(os.environ, HF_HUB_OFFLINE='1')
    (root / 'logs').mkdir(exist_ok=True)
    lock = root / 'PRODUCER.lock'
    with lock.open('x') as stream:
        stream.write(str(os.getpid()))
    # A stale lock is intentionally retained after a crash. Reconcile its PID before reuse.
    results = []

    def run(command, label):
        assert_running(root)
        log = root / 'logs' / (label + '-' + str(time.time_ns()) + '.log')
        with log.open('x') as stream:
            result = subprocess.run([str(args.python), '-u', str(HERE / command[0]), *map(str, command[1:])],
                                    env=environment, stdout=stream, stderr=subprocess.STDOUT)
        return result.returncode

    for source in sources:
        assert_running(root)
        directory, _ = voice_directory(root, source, root / 'ref.wav')
        progress = root / 'queue' / (source.stem + '.json')
        prior = json.loads(progress.read_text()) if progress.exists() else {'attempt': 0}
        if prior.get('status') == 'staged':
            assert (directory / 'voice-check.json').exists(), 'Staged receipt missing'
            continue
        report = None
        for attempt in range(prior['attempt'], 3):
            label = source.stem + f'-attempt{attempt}'
            atomic_json(progress, dict(status='running', attempt=attempt, source_sha256=sha(source)))
            if attempt:
                code = run(['repair.py', directory, '--attempt', attempt], label + '-repair')
                if code:
                    atomic_json(progress, dict(status='review-required', attempt=attempt, reason='repair failed or consumed'))
                    break
            code = run(['synthesize.py', root, '--only', source.stem], label + '-synth')
            if code:
                atomic_json(progress, dict(status='stopped', attempt=attempt, reason='synthesis failed; inspect checkpoint'))
                break
            code = run(['transcribe.py', directory], label + '-asr')
            path = directory / 'voice-check.json'
            assert path.exists() and not (directory / 'ASR-RUNNING.json').exists(), 'ASR incomplete; inspect log, no promotion'
            report = json.loads(path.read_text())
            if code == 0 and report.get('pass') is True:
                break
            if report.get('needs_audio_judgment'):
                atomic_json(progress, dict(status='audio-judgment', attempt=attempt, differences=report['differences']))
                break
            atomic_json(progress, dict(status='review-required', attempt=attempt + 1, differences=report.get('differences'),
                                       reason='narration or duration check failed'))
        if not report or report.get('pass') is not True:
            results.append(dict(stem=source.stem, status='review-required'))
            atomic_json(root / 'production-results.json', results)
            continue
        assert_running(root)
        build(directory / 'lesson.json', root / 'projects', root / 'assets')
        project = root / 'projects' / source.stem
        archive = root / (source.stem + '-project.zip')
        with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED, compresslevel=1) as compressed:
            for file in project.rglob('*'):
                if file.is_file() and (file.name in EXPORT_FILES or file.parent.name in ('assets', 'compositions')):
                    compressed.write(file, file.relative_to(root / 'projects'))
        assert_running(root)
        subprocess.run(['scp', str(archive), args.host + ':' + args.remote_root + '/' + archive.name], check=True)
        # Keep PowerShell variables in a file; no nested command expansion.
        stage = root / 'stage.ps1'
        stage.write_text("param($Root,$Name)\n$ErrorActionPreference='Stop'\nif(Test-Path (Join-Path $Root 'HOLD.json')){throw 'Held'}\nExpand-Archive -LiteralPath (Join-Path $Root ($Name+'-project.zip')) -DestinationPath (Join-Path $Root 'projects') -Force\nif(!(Test-Path (Join-Path $Root ('projects\\'+$Name+'\\index.html')))){throw 'Missing extracted project'}\nNew-Item -ItemType File -Path (Join-Path $Root ($Name+'.ready')) -Force | Out-Null\n")
        subprocess.run(['scp', str(stage), args.host + ':' + args.remote_root + '/stage.ps1'], check=True)
        assert_running(root)
        subprocess.run(['ssh', args.host, 'powershell', '-NoProfile', '-File', args.remote_root + '/stage.ps1',
                        '-Root', args.remote_root, '-Name', source.stem], check=True)
        atomic_json(progress, dict(status='staged', attempt=attempt, duration=report['duration'], generation=directory.name))
        results.append(dict(stem=source.stem, status='staged', duration=report['duration']))
        atomic_json(root / 'production-results.json', results)
        print('STAGED FOR PC', source.stem, report['duration'], flush=True)
    lock.replace(root / f'PRODUCER-complete-{os.getpid()}.lock')
    assert all(row['status'] == 'staged' for row in results), 'Some accepted lessons require review'


if __name__ == '__main__':
    main()
