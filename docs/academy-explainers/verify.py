"""Probe finished exports and inspect every chapter center without re-rendering."""
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
from validation import require_approved
from contract import duration_ok, voice_directory, accepted_sources, sha


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('video', type=Path)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    root, video = args.evidence, args.video
    name = video.stem
    project = root / 'projects' / name
    accepted_sources(root)
    voice, _ = voice_directory(root, root / 'scripts' / (name + '.json'), root / 'ref.wav')
    require_approved(voice)
    lesson = json.loads((project / 'lesson.json').read_text())
    qa = root / 'qa' / (name + '-' + time.strftime('%H%M%S'))
    qa.mkdir(parents=True)
    probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(video)]))
    (qa / 'probe.json').write_text(json.dumps(probe, indent=2))
    duration = float(probe['format']['duration'])
    visual = next(s for s in probe['streams'] if s['codec_type'] == 'video')
    audio = next(s for s in probe['streams'] if s['codec_type'] == 'audio')
    assert duration_ok(dict(lesson, duration=duration)) and abs(duration - lesson['duration']) < .2
    assert visual['width'] >= 1280 and visual['height'] >= 720 and audio['codec_name'] == 'aac'
    assert abs(float(audio['duration']) - lesson['duration']) < .2
    vtt = (project / 'captions.vtt').read_text()
    cues = re.findall(r'(\d\d):(\d\d):(\d\d)\.(\d\d\d) --> (\d\d):(\d\d):(\d\d)\.(\d\d\d)', vtt)
    assert len(cues) >= 80
    previous = 0
    for cue in cues:
        h, m, s, ms, eh, em, es, ems = map(int, cue)
        start, end = h*3600+m*60+s+ms/1000, eh*3600+em*60+es+ems/1000
        assert previous <= start <= end <= duration + .1
        previous = start
    decode = subprocess.run(['ffmpeg', '-hide_banner', '-i', str(video), '-vn', '-af', 'volumedetect,silencedetect=noise=-45dB:d=3', '-f', 'null', '-'], capture_output=True, text=True)
    (qa / 'audio-decode.log').write_text(decode.stderr)
    assert decode.returncode == 0 and 'silence_start' not in decode.stderr
    peak = float(re.search(r'max_volume: ([\d.-]+) dB', decode.stderr)[1])
    mean = float(re.search(r'mean_volume: ([\d.-]+) dB', decode.stderr)[1])
    assert -35 < mean < -5 and peak < 0, (mean, peak)
    # Oct 22: delivered loudness and a constant frame cadence (no dropped or doubled frames).
    from master import loudness
    level = loudness(video)
    assert -17 <= level['integrated_lufs'] <= -15 and level['true_peak_dbtp'] <= -1.5, level
    fps = float(Fraction(visual['r_frame_rate']))
    times = sorted(float(t) for t in subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'packet=pts_time', '-of', 'csv=p=0', str(video)], text=True).split())
    uneven = sum(abs(b - a - 1 / fps) > .002 for a, b in zip(times, times[1:]))
    assert fps >= 30 and not uneven and abs(len(times) - duration * fps) <= 2, (fps, uneven, len(times))
    frames = []
    for index, chapter in enumerate(lesson['chapters']):
        at = chapter['start'] + chapter['duration']/2
        frame = qa / f'chapter-{index:02d}.jpg'
        subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(at), '-i', str(video), '-frames:v', '1', '-vf', 'scale=480:270', str(frame)], check=True)
        assert frame.stat().st_size > 5000
        frames.append(dict(chapter=index+1, title=chapter['title'], at=at, frame=frame.name))
    subprocess.run(['ffmpeg', '-v', 'error', '-framerate', '1', '-i', str(qa / 'chapter-%02d.jpg'), '-vf', f'tile=2x{(len(frames)+1)//2}', '-frames:v', '1', str(qa / 'contact-sheet.jpg')], check=True)
    for source, suffix in [('captions.vtt', '.vtt'), ('transcript.txt', '.txt'), ('lesson.json', '.json')]:
        shutil.copy2(project / source, video.with_suffix(suffix))
    shutil.copy2(qa / frames[0]['frame'], video.with_suffix('.jpg'))
    exported = [video, video.with_suffix('.jpg'), video.with_suffix('.vtt'), video.with_suffix('.txt')]
    manifest = dict(stem=name, duration=duration, files=[dict(name=item.name, bytes=item.stat().st_size, sha256=sha(item)) for item in exported])
    (video.parent / (name + '-manifest.json')).write_text(json.dumps(manifest, indent=2))
    report = dict(video=str(video), duration=duration, width=visual['width'], height=visual['height'], fps=visual['r_frame_rate'], audio_codec=audio['codec_name'], mean_dbfs=mean, peak_dbfs=peak, **level, frames=len(times), captions=len(cues), chapters=frames, sha256=hashlib.sha256(video.read_bytes()).hexdigest(), voice_check=json.loads((voice/'voice-check.json').read_text()), passed=True)
    (qa / 'verification.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k not in ('chapters', 'voice_check')}), flush=True)


if __name__ == '__main__':
    main()
