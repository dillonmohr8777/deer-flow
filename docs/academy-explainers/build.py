"""Build self-contained HyperFrames teaching projects from completed narration."""
import argparse
import difflib
import html
import json
import shutil
import os
import re
import time
from pathlib import Path
from validation import require_approved
from contract import COURSE_MAX, duration_ok, require_course, sha
from master import master

HERE = Path(__file__).parent
STYLE = """
@font-face{font-family:Nunito;src:url('assets/nunito-sans.ttf')}
@font-face{font-family:Nunito;font-weight:700 900;src:url('assets/nunito-sans-bold.ttf')}
@font-face{font-family:Archivo;src:url('assets/archivo-black.ttf')}
@font-face{font-family:Fraunces;font-weight:700;src:url('assets/fraunces-bold.woff2')}
*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;overflow:hidden}
body{background:#F2EDE3;color:#101E3F;font-family:Nunito,sans-serif}
#root{position:relative;width:100%;height:100%;overflow:hidden}
.scene{position:absolute;inset:0;padding:180px 100px 160px}
.header{position:absolute;left:90px;right:90px;top:45px;height:80px;display:flex;align-items:center;gap:26px;border-bottom:3px solid #D8C3A0;padding-bottom:20px}
.logo{width:72px;height:72px}.brand{font-family:Fraunces,serif;font-weight:700;font-size:34px;color:#1B4B9E;letter-spacing:-.015em}.lesson-no{margin-left:auto;color:#3A4A6B;font-size:26px;font-weight:700}
.chapter-no{color:#1B4B9E;font-family:Archivo,sans-serif;font-size:26px;letter-spacing:3px;margin:0 0 25px}
.title{font-family:Fraunces,serif;font-weight:700;font-size:76px;line-height:1.08;max-width:700px;margin:0;color:#101E3F;letter-spacing:-.015em}
.layout{display:grid;grid-template-columns:720px 1fr;gap:70px;height:650px;align-items:center}
.principle{font-size:36px;line-height:1.3;max-width:670px;margin-top:42px;color:#101E3F;font-weight:700;border-left:8px solid #1B4B9E;padding-left:26px}
.board{border:2px solid #D8C3A0;border-radius:20px;background:#FBF8F1;padding:46px;min-height:490px;display:flex;flex-direction:column;justify-content:center;position:relative;box-shadow:0 1px 2px rgb(16 30 63/.16),0 24px 44px -18px rgb(16 30 63/.5),14px 16px 0 rgb(27 75 158/.18)}
.board-label{font-family:Archivo,sans-serif;font-size:26px;color:#1B4B9E;letter-spacing:2px;margin-bottom:25px}
.row{font-size:37px;line-height:1.3;margin:10px 0;padding:9px 14px;white-space:pre-wrap;border-radius:8px;position:relative;color:#101E3F;border-left:6px solid rgba(27,75,158,0)}
.row.command{font-family:monospace;font-size:32px}
.bar{position:absolute;height:8px;background:#1B4B9E;bottom:0;left:0;width:100%;transform-origin:left;border-radius:0 0 18px 18px}
.footer{position:absolute;left:100px;right:100px;bottom:30px;font-size:23px;color:#3A4A6B;font-weight:700;display:flex;justify-content:space-between}
.caption{position:absolute;left:125px;right:125px;bottom:85px;text-align:center}
.caption span{display:inline-block;max-width:100%;font-size:38px;line-height:1.25;font-weight:800;padding:12px 32px;background:#101E3F;color:#FBF8F1;border-radius:14px;box-shadow:0 12px 26px -14px rgb(16 30 63/.6)}
.clip{position:absolute}.shot{max-height:640px;max-width:100%;object-fit:contain;border-radius:18px;border:2px solid #D8C3A0}
.mode-example{display:flex;align-items:center;gap:20px}.mode-example .shot{width:255px;height:590px}.mode-example .row{font-size:30px}
"""


def escape(value):
    return html.escape(str(value), quote=True)


def timestamp(value, separator='.'):
    ms = int(round(value * 1000))
    hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000)
    seconds, ms = divmod(ms, 1000)
    return f'{hours:02}:{minutes:02}:{seconds:02}{separator}{ms:03}'


def script_timing(expected, heard):
    """Caption text is the reviewed script; each word takes the time of the ASR word aligned to it."""
    from transcribe import normalize
    key = lambda text: ''.join(normalize(text))
    timed = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, [key(t) for t in expected], [key(w['word']) for w in heard], autojunk=False).get_opcodes():
        if tag == 'insert':
            continue
        if i2 - i1 == j2 - j1:
            timed += [dict(start=heard[j]['start'], end=heard[j]['end'], word=expected[i]) for i, j in zip(range(i1, i2), range(j1, j2))]
            continue
        # Uneven replace spreads over the heard span; a missed word sits in the gap between its neighbours.
        start = heard[j1]['start'] if j2 > j1 else (heard[j1 - 1]['end'] if j1 else 0.0)
        end = heard[j2 - 1]['end'] if j2 > j1 else (heard[j1]['start'] if j1 < len(heard) else start)
        step = (end - start) / (i2 - i1)
        timed += [dict(start=start + k * step, end=start + (k + 1) * step, word=expected[i1 + k]) for k in range(i2 - i1)]
    return timed


def captions(asr, lesson=None):
    words = [w for segment in asr['segments'] for w in segment.get('words', [])]
    assert words, 'Word timestamps are required; do not invent caption timing.'
    if lesson is not None:
        words = script_timing(re.findall(r'\S+', ' '.join(c['narration'] for c in lesson['chapters'])), words)
    cues, batch = [], []
    for word in words:
        batch.append(word)
        # Cues end with the sentence or at a comma once long enough, so a cue never starts the next sentence.
        text = word['word']
        if len(batch) == 8 or (len(batch) >= 3 and text.endswith(('.', '?', '!'))) or (len(batch) >= 5 and text.endswith((',', ';', ':'))) or word is words[-1]:
            cues.append(dict(start=batch[0]['start'], end=batch[-1]['end'], text=' '.join(w['word'].strip() for w in batch)))
            batch = []
    return cues


def build(source, output, assets, burn_captions=False):
    lesson = json.loads(source.read_text())
    assert duration_ok(lesson), lesson['duration']
    require_approved(source.parent)
    _, packet = require_course(source.parent)
    stem = lesson['course_stem']
    project = output / stem
    project.mkdir(parents=True, exist_ok=True)
    (project / 'compositions').mkdir(exist_ok=True)
    (project / 'assets').mkdir(exist_ok=True)
    for name in ['momo-mark.svg', 'archivo-black.ttf', 'nunito-sans.ttf', 'nunito-sans-bold.ttf', 'fraunces-bold.woff2', 'gsap.min.js']:
        shutil.copy2(assets / name, project / 'assets' / name)
    if (assets / 'experience.png').exists():
        shutil.copy2(assets / 'experience.png', project / 'assets/experience.png')
    # The video carries a delivery master (edge fades, -16 LUFS, true-peak ceiling); the accepted narration stays as is.
    pending = project / 'assets' / ('narration-' + str(time.time_ns()) + '.wav')
    mastering = master(source.parent / 'narration.wav', source.parent / 'timing.json', pending)
    pending.replace(project / 'assets/narration.wav')
    mastering.update(source_sha256=sha(source.parent / 'narration.wav'), output_sha256=sha(project / 'assets/narration.wav'))
    (project / 'mastering.json').write_text(json.dumps(mastering, indent=2))
    key = stem[:2]
    visuals = json.loads((HERE / 'work-visuals.json').read_text())[stem]
    assert len(visuals) == len(lesson['chapters']), 'Chapter/visual mismatch'
    chapter_total = len(lesson['chapters'])
    course_total = packet.get('course_total')
    assert isinstance(course_total, int) and max(int(row['stem'][:2])+1 for row in packet['lessons']) <= course_total <= COURSE_MAX, 'Explicit complete-course total required'
    word_caps = captions(json.loads((source.parent / 'asr.json').read_text()), lesson)
    vtt = ['WEBVTT', '']
    hosts, boards = [], []
    for index, (chapter, board) in enumerate(zip(lesson['chapters'], visuals)):
        cid = f'chapter-{index}'
        title, label, content, principle = board
        rows = content.splitlines()
        row_html = ''.join(f'<div class="row {"command" if key == "03" else ""}" id="{cid}-row-{j}">{escape(line)}</div>' for j, line in enumerate(rows))
        if board[1] == 'EXPERIENCE MODES':
            assert (assets / 'experience.png').is_file(), 'Inspected Experience screenshot required'
            row_html = f'<div class="mode-example"><img class="shot" src="assets/experience.png" alt="Actual Easy, Medium and Hard experience settings"><div>{row_html}</div></div>'
        duration = chapter['duration']
        # Enter: label, title, principle and board settle in; rows follow the board. Leave: a short lift and fade.
        animation = [f'const tl=gsap.timeline({{paused:true}});',
                     f'tl.fromTo("#{cid} .chapter-no",{{opacity:0,x:-28}},{{opacity:1,x:0,duration:.5,ease:"power3.out"}},.05);',
                     f'tl.fromTo("#{cid} .title",{{opacity:0,y:40}},{{opacity:1,y:0,duration:.7,ease:"power3.out"}},.12);',
                     f'tl.fromTo("#{cid} .principle",{{opacity:0,x:-22}},{{opacity:1,x:0,duration:.6,ease:"power3.out"}},.4);',
                     f'tl.fromTo("#{cid} .board",{{opacity:0,y:46,scale:.97}},{{opacity:1,y:0,scale:1,duration:.7,ease:"power3.out"}},.18);',
                     f'tl.to("#{cid} .scene",{{opacity:0,y:-14,duration:.35,ease:"power2.in"}},{max(1.5, duration - .4):.3f});']
        animation += [f'tl.fromTo("#{cid}-row-{j}",{{opacity:0,y:26}},{{opacity:1,y:0,duration:.45,ease:"power3.out"}},{j*.1+.5:.2f});' for j in range(len(rows))]
        # One active row at a time (royal edge, warm fill); rows already covered keep a light fill.
        for j in range(len(rows)):
            start = max(.9, j * duration / len(rows))
            animation.append(f'tl.to("#{cid}-row-{j}",{{backgroundColor:"#E6D7BE",borderLeftColor:"rgba(27,75,158,1)",duration:.3,ease:"power1.out"}},{start:.3f});')
            if j:
                animation.append(f'tl.to("#{cid}-row-{j-1}",{{backgroundColor:"#EFE7DA",borderLeftColor:"rgba(27,75,158,0)",duration:.3,ease:"power1.out"}},{start:.3f});')
        animation.append(f'tl.fromTo("#{cid}-bar",{{scaleX:0}},{{scaleX:1,duration:{duration},ease:"none"}},0);')
        animation.append(f'window.__timelines["{cid}"]=tl;')
        frame = f'''<!doctype html><html><body><template>
<style>#{cid}{{position:absolute;inset:0;width:100%;height:100%}}</style>
<div id="{cid}" data-composition-id="{cid}" data-width="1920" data-height="1080" data-duration="{duration}">
<section class="scene"><div class="layout"><div><p class="chapter-no">CHAPTER {index+1:02} / {chapter_total}</p><h1 class="title">{escape(title)}</h1><p class="principle">{escape(principle)}</p></div>
<div class="board"><div class="board-label">{escape(label)}</div>{row_html}<div id="{cid}-bar" class="bar"></div></div></div></section></div>
<script>{''.join(animation)}</script></template></body></html>'''
        (project / f'compositions/{cid}.html').write_text(frame)
        hosts.append(f'<div id="slot-{cid}" class="clip" data-composition-id="{cid}" data-composition-src="compositions/{cid}.html" data-start="{chapter["start"]}" data-duration="{duration}" data-track-index="0" data-width="1920" data-height="1080"></div>')
        boards.append(f'## Frame {index+1}\nstatus: animated\nsrc: compositions/{cid}.html\nmotion: waterfall-entry + css-marker-patterns\nbeat: {chapter["title"]}\n')
    cap_html = []
    for index, cap in enumerate(word_caps):
        duration = max(.01, cap['end'] - cap['start'])
        cap_html.append(f'<div id="caption-{index}" class="clip caption" data-start="{cap["start"]}" data-duration="{duration}" data-track-index="2"><span>{escape(cap["text"])}</span></div>')
        vtt += [f'{timestamp(cap["start"])} --> {timestamp(cap["end"])}', cap['text'], '']
    duration = lesson['duration']
    title = lesson['title'].split(':')[0]
    document = f'''<!doctype html><html lang="en"><head><meta charset="UTF-8"><title>{escape(lesson["title"])}</title>
<script src="assets/gsap.min.js"></script><style>{STYLE}</style></head><body>
<div id="root" data-composition-id="main" data-width="1920" data-height="1080" data-duration="{duration}">
<header class="header"><img class="logo" src="assets/momo-mark.svg" alt="MomoBot"><span class="brand">Momentum Academy</span><span class="lesson-no">LESSON {int(key)+1} / {course_total}</span></header>
{''.join(hosts)}{''.join(cap_html) if burn_captions else ''}
<audio id="narration" class="clip" src="assets/narration.wav" data-start="0" data-duration="{duration}" data-track-index="1"></audio>
<footer class="footer"><span>{escape(title)}</span><span>Dillon Mohr</span></footer></div>
<script>const tl=gsap.timeline({{paused:true}});tl.to(".logo",{{y:-12,rotation:-4,duration:1.3,ease:"sine.inOut",yoyo:true,repeat:{max(1, int(duration / 1.3) - 1)}}},0);window.__timelines["main"]=tl;</script></body></html>'''
    (project / 'index.html').write_text(document)
    (project / 'hyperframes.json').write_text(json.dumps({'authoringSkill': 'general-video', 'media': {'autoProxy': False}}, indent=2))
    (project / 'STORYBOARD.md').write_text('\n'.join(boards))
    (project / 'captions.vtt').write_text('\n'.join(vtt))
    (project / 'transcript.txt').write_text('\n\n'.join(c['title'] + '\n' + c['narration'] for c in lesson['chapters']))
    (project / 'lesson.json').write_text(json.dumps(lesson, indent=2))
    shutil.copy2(source.parent / 'generation.json', project / 'generation.json')
    (project / 'BRIEF.md').write_text('---\nworkflow: general-video\nflow: automation\nstoryboard: no\n---\nFive to six minutes of useful instruction in Dillon\'s own voice; no music bed so the lesson stays easy to hear. Existing Momo brand assets, work examples, variable practical chapters, sidecar word-timed captions default off. Parent owns final integration.\n')
    (project / 'design.md').write_text('MomoBot Paper tokens: cream #F2EDE3, cream-hi #FBF8F1, kraft #D8C3A0, ink #101E3F, ink-muted #3A4A6B, royal #1B4B9E for state and objects. Fraunces 700 headings, Archivo Black labels, Nunito Sans text. Exact transparent Momo mark bouncing in the header. Focal element: concrete teaching example; left edge: chapter/title; bottom: word-timed captions. Stepped highlight follows teaching beats. No decorative movement competing with commands.\n')
    print(project, round(duration, 3), 'seconds', len(word_caps), 'captions')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('voice', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('assets', type=Path)
    parser.add_argument('--burn-captions', action='store_true')
    args = parser.parse_args()
    for source in sorted(args.voice.glob('*/*/lesson.json')):
        if (source.parent / 'asr.json').exists():
            build(source, args.output, args.assets, args.burn_captions)
