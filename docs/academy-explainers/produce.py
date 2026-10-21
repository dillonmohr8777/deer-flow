"""Finite sequential voice/ASR/build/stage job. Final publication stays separate."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile
from build import build

HERE = Path(__file__).parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('evidence', type=Path)
    parser.add_argument('--start', type=int, default=2, choices=range(1, 8))
    parser.add_argument('--host', default='winpc')
    parser.add_argument('--remote-root', default='C:/MacTransfer/academy-explainers-20261021')
    args = parser.parse_args()
    root = args.evidence
    assert not (root / "HOLD.json").exists(), "Production is held; reconcile the newest role-specific Academy scope first"
    python = str(root / 'voice/.venv/bin/python')
    environment = dict(os.environ, HF_HUB_OFFLINE='1')
    results = []

    def run(command, log):
        with (root / 'voice' / log).open('w') as stream:
            return subprocess.run([python, '-u', str(HERE / command[0]), *map(str, command[1:])],
                                  env=environment, stdout=stream, stderr=subprocess.STDOUT).returncode

    for number in range(args.start, 8):
        source = next((root / 'scripts').glob(f'{number:02d}-*.json'))
        directory = root / 'voice-sentences' / source.stem
        synth = ['synthesize.py', root / 'scripts', root / 'voice-sentences', '--ref', root / 'voice/ref.wav', '--only', f'{number:02d}']
        if number == 3:
            synth += ['--pause', '.25']
        print('SYNTH', source.stem, flush=True)
        assert run(synth, f'{number:02d}-production-synth.log') == 0, source.stem
        run(['transcribe.py', root / 'voice-sentences', '--only', f'{number:02d}'], f'{number:02d}-production-asr.log')
        for attempt in [1, 2]:
            report = json.loads((directory / 'voice-check.json').read_text())
            if report['pass']:
                break
            if list(directory.glob(f'*-rejected-repair{attempt}.wav')):
                continue
            print('REPAIR', source.stem, attempt, flush=True)
            assert run(['repair.py', directory, '--ref', root / 'voice/ref.wav', '--attempt', attempt], f'{number:02d}-production-repair{attempt}.log') == 0
            assert run(synth, f'{number:02d}-production-rebuild{attempt}.log') == 0
            run(['transcribe.py', root / 'voice-sentences', '--only', f'{number:02d}'], f'{number:02d}-production-asr{attempt}.log')
        report = json.loads((directory / 'voice-check.json').read_text())
        results.append(dict(lesson=source.stem, duration=report['duration'], passed=report['pass'], differences=report['differences']))
        (root / 'production-results.json').write_text(json.dumps(results, indent=2))
        if not report['pass']:
            print('REVIEW REQUIRED', source.stem, report['differences'], flush=True)
            continue
        build(directory / 'lesson.json', root / 'projects', root / 'assets')
        project = root / 'projects' / source.stem
        archive = root / (source.stem + '-project.zip')
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as compressed:
            for file in project.rglob('*'):
                if file.is_file() and 'snapshots' not in file.parts and file.suffix != '.log':
                    compressed.write(file, file.relative_to(root / 'projects'))
        subprocess.run(['scp', str(archive), args.host + ':' + args.remote_root + '/' + archive.name], check=True)
        windows_root = args.remote_root.replace('/', '\\')
        command = f'Expand-Archive -Force {windows_root}\\{archive.name} {windows_root}\\projects; New-Item -ItemType File -Force {windows_root}\\{source.stem}.ready | Out-Null'
        subprocess.run(['ssh', args.host, 'powershell -NoProfile -Command "' + command + '"'], check=True)
        print('STAGED FOR PC', source.stem, report['duration'], report['coverage'], flush=True)
    assert results and all(row['passed'] for row in results), 'Some lessons require review; see production-results.json'


if __name__ == '__main__':
    main()
