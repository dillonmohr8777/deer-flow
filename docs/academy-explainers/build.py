"""Build self-contained HyperFrames teaching projects from completed narration."""
import argparse
import html
import json
import shutil
from pathlib import Path
from validation import require_approved

HERE = Path(__file__).parent
STYLE = """
@font-face{font-family:Nunito;src:url('assets/nunito-sans.ttf')}
@font-face{font-family:Archivo;src:url('assets/archivo-black.ttf')}
*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;overflow:hidden}
body{background:#0E1417;color:#F4F1EC;font-family:Nunito,sans-serif}
#root{position:relative;width:100%;height:100%;overflow:hidden}
.scene{position:absolute;inset:0;padding:180px 100px 160px}
.header{position:absolute;left:90px;right:90px;top:45px;height:80px;display:flex;align-items:center;gap:26px;border-bottom:2px solid #687175;padding-bottom:20px}
.logo{width:72px;height:72px}.brand{font-weight:800;font-size:30px}.lesson-no{margin-left:auto;color:#F4F1EC;font-size:26px}
.chapter-no{color:#F6A765;font-size:28px;font-weight:800;letter-spacing:3px;margin:0 0 25px}
.title{font-family:Archivo,sans-serif;font-size:72px;line-height:1.13;max-width:700px;margin:0}
.layout{display:grid;grid-template-columns:720px 1fr;gap:70px;height:650px;align-items:center}
.principle{font-size:38px;line-height:1.3;max-width:670px;margin-top:42px;color:#F6A765}
.board{border:2px solid #687175;border-radius:20px;background:#172226;padding:46px;min-height:490px;display:flex;flex-direction:column;justify-content:center;position:relative}
.board-label{font-size:28px;color:#F6A765;font-weight:900;letter-spacing:2px;margin-bottom:25px}
.row{font-size:37px;line-height:1.3;margin:10px 0;padding:9px 14px;white-space:pre-wrap;border-radius:8px;position:relative}
.row.command{font-family:monospace;font-size:32px}.row.current{background:#28373B}
.bar{position:absolute;height:7px;background:#E27113;bottom:0;left:0;width:100%;transform-origin:left}
.footer{position:absolute;left:100px;right:100px;bottom:30px;font-size:23px;color:#B7C0C3;display:flex;justify-content:space-between}
.caption{position:absolute;left:125px;right:125px;bottom:85px;min-height:60px;text-align:center;font-size:36px;line-height:1.25;font-weight:800;padding:10px 24px;background:#0E1417;color:#F4F1EC}
.clip{position:absolute}.shot{max-height:640px;max-width:100%;object-fit:contain;border-radius:18px;border:2px solid #687175}
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


def captions(asr):
    words = [w for segment in asr['segments'] for w in segment.get('words', [])]
    assert words, 'Word timestamps are required; do not invent caption timing.'
    return [dict(start=batch[0]['start'], end=batch[-1]['end'],
                 text=' '.join(w['word'].strip() for w in batch))
            for offset in range(0, len(words), 7) if (batch := words[offset:offset + 7])]


def build(source, output, assets):
    lesson = json.loads(source.read_text())
    assert 300 <= lesson['duration'] <= 360, lesson['duration']
    require_approved(source.parent)
    project = output / source.parent.name
    project.mkdir(parents=True, exist_ok=True)
    (project / 'compositions').mkdir(exist_ok=True)
    (project / 'assets').mkdir(exist_ok=True)
    for name in ['momo-mark.svg', 'archivo-black.ttf', 'nunito-sans.ttf', 'gsap.min.js']:
        shutil.copy2(assets / name, project / 'assets' / name)
    if (assets / 'experience.png').exists():
        shutil.copy2(assets / 'experience.png', project / 'assets/experience.png')
    shutil.copy2(source.parent / 'narration.wav', project / 'assets/narration.wav')
    key = source.parent.name[:2]
    visuals = json.loads((HERE / 'visuals.json').read_text())[key]
    assert len(visuals) == len(lesson['chapters']) == 10
    word_caps = captions(json.loads((source.parent / 'asr.json').read_text()))
    vtt = ['WEBVTT', '']
    hosts, boards = [], []
    for index, (chapter, board) in enumerate(zip(lesson['chapters'], visuals)):
        cid = f'chapter-{index}'
        title, label, content, principle = board
        rows = content.splitlines()
        row_html = ''.join(f'<div class="row {"command" if key == "03" else ""}" id="{cid}-row-{j}">{escape(line)}</div>' for j, line in enumerate(rows))
        if key == '02' and index == 2:
            row_html = f'<div class="mode-example"><img class="shot" src="assets/experience.png" alt="Actual Easy, Medium and Hard experience settings"><div>{row_html}</div></div>'
        duration = chapter['duration']
        animation = [f'const tl=gsap.timeline({{paused:true}});']
        animation += [f'tl.fromTo("#{cid}-row-{j}",{{opacity:0,y:30}},{{opacity:1,y:0,duration:.35,ease:"power4.out"}},{j*.12+.1});' for j in range(len(rows))]
        for j in range(len(rows)):
            start = max(.6, j * duration / len(rows))
            animation.append(f'tl.to("#{cid}-row-{j}",{{backgroundColor:"#35484D",duration:.25,ease:"none"}},{start:.3f});')
        animation.append(f'tl.fromTo("#{cid}-bar",{{scaleX:0}},{{scaleX:1,duration:{duration},ease:"none"}},0);')
        animation.append(f'window.__timelines["{cid}"]=tl;')
        frame = f'''<!doctype html><html><body><template>
<style>#{cid}{{position:absolute;inset:0;width:100%;height:100%}}</style>
<div id="{cid}" data-composition-id="{cid}" data-width="1920" data-height="1080" data-duration="{duration}">
<section class="scene"><div class="layout"><div><p class="chapter-no">CHAPTER {index+1:02} / 10</p><h1 class="title">{escape(title)}</h1><p class="principle">{escape(principle)}</p></div>
<div class="board"><div class="board-label">{escape(label)}</div>{row_html}<div id="{cid}-bar" class="bar"></div></div></div></section></div>
<script>{''.join(animation)}</script></template></body></html>'''
        (project / f'compositions/{cid}.html').write_text(frame)
        hosts.append(f'<div id="slot-{cid}" class="clip" data-composition-id="{cid}" data-composition-src="compositions/{cid}.html" data-start="{chapter["start"]}" data-duration="{duration}" data-track-index="0" data-width="1920" data-height="1080"></div>')
        boards.append(f'## Frame {index+1}\nstatus: animated\nsrc: compositions/{cid}.html\nmotion: waterfall-entry + css-marker-patterns\nbeat: {chapter["title"]}\n')
    cap_html = []
    for index, cap in enumerate(word_caps):
        duration = max(.01, cap['end'] - cap['start'])
        cap_html.append(f'<div id="caption-{index}" class="clip caption" data-start="{cap["start"]}" data-duration="{duration}" data-track-index="2">{escape(cap["text"])}</div>')
        vtt += [f'{timestamp(cap["start"])} --> {timestamp(cap["end"])}', cap['text'], '']
    duration = lesson['duration']
    title = lesson['title'].split(':')[0]
    document = f'''<!doctype html><html lang="en"><head><meta charset="UTF-8"><title>{escape(lesson["title"])}</title>
<script src="assets/gsap.min.js"></script><style>{STYLE}</style></head><body>
<div id="root" data-composition-id="main" data-width="1920" data-height="1080" data-duration="{duration}">
<header class="header"><img class="logo" src="assets/momo-mark.svg" alt="MomoBot"><span class="brand">Momentum AI Academy</span><span class="lesson-no">LESSON {int(key)} / 7</span></header>
{''.join(hosts)}{''.join(cap_html)}
<audio id="narration" class="clip" src="assets/narration.wav" data-start="0" data-duration="{duration}" data-track-index="1"></audio>
<footer class="footer"><span>{escape(title)}</span><span>Dillon Mohr</span></footer></div>
<script>const tl=gsap.timeline({{paused:true}});window.__timelines["main"]=tl;</script></body></html>'''
    (project / 'index.html').write_text(document)
    (project / 'hyperframes.json').write_text(json.dumps({'authoringSkill': 'general-video', 'media': {'autoProxy': False}}, indent=2))
    (project / 'STORYBOARD.md').write_text('\n'.join(boards))
    (project / 'captions.vtt').write_text('\n'.join(vtt))
    (project / 'transcript.txt').write_text('\n\n'.join(c['title'] + '\n' + c['narration'] for c in lesson['chapters']))
    (project / 'lesson.json').write_text(json.dumps(lesson, indent=2))
    (project / 'BRIEF.md').write_text('---\nworkflow: general-video\nflow: automation\nstoryboard: no\n---\nFive to six minutes of useful instruction in Dillon\'s own voice; no music bed so the lesson stays easy to hear. Existing Momo brand assets, ten practical chapters, word-timed captions. Parent owns final integration.\n')
    (project / 'design.md').write_text('Existing Momentum tokens: deep #0E1417, onDeep #F4F1EC, signal #E27113. Lighter #F6A765 for readable accent text. Exact transparent Momo mark, existing Archivo headline and Nunito body files. Focal element: concrete teaching example; left edge: chapter/title; bottom: word-timed captions. Stepped highlight follows teaching beats. No decorative movement competing with commands.\n')
    print(project, round(duration, 3), 'seconds', len(word_caps), 'captions')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('voice', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('assets', type=Path)
    args = parser.parse_args()
    for source in sorted(args.voice.glob('*/lesson.json')):
        if (source.parent / 'asr.json').exists():
            build(source, args.output, args.assets)
