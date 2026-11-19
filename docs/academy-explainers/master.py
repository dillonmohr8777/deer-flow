"""Delivery master for an accepted narration. The accepted narration.wav is never changed: this writes a
derived 48 kHz file plus a receipt. Each synthesized sentence starts and stops at a hard edge next to
digital silence, which clicks; every sentence gets a short raised-cosine fade first. Then a rumble
high-pass, loudness to -16 LUFS and a 4x oversampled true-peak ceiling with room for the AAC encode.
Measured Oct 22 on lesson 16: no broadband hiss inside sentences (stationary floor below -85 dBFS per bin
above 3 kHz), so no denoiser: it would only add latency and artifacts. Every stage is latency free."""
import json
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

TARGET_LUFS = -16.0
CEILING_DBTP = -2.0  # HyperFrames encodes AAC 192k; codec overshoot must stay under the -1.5 dBTP delivery target
FADE_IN, FADE_OUT = .012, .040  # sentence tails are already below -40 dBFS in their last 40 ms
# Two identical channels: HyperFrames passes a stereo source through at unity, while a mono source goes through
# its own pan filter (measured 2.1 dB down on lesson 16), so loudness is set and measured as delivered.
SHAPE = 'highpass=f=60:poles=2,aresample=48000:filter_size=64:cutoff=0.97,pan=stereo|c0=c0|c1=c0'
LIMIT = 'aresample=192000:filter_size=64,alimiter=limit={limit:.4f}:attack=1:release=60:level=false:latency=1,aresample=48000:filter_size=64:cutoff=0.97'


def loudness(path, dualmono=False):
    """EBU R128 integrated loudness, range and true peak, as ffmpeg's ebur128 reports them. dualmono measures a
    mono file as it plays on two speakers, the scale of the delivered stereo track."""
    err = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', str(path), '-map', '0:a:0', '-af', 'ebur128=peak=true' + (':dualmono=true' if dualmono else ''), '-f', 'null', '-'],
                         capture_output=True, text=True, check=True).stderr
    summary = err[err.rfind('Summary:'):]
    value = lambda key: float(re.search(key + r':\s+(-?[\d.]+|-inf)', summary)[1].replace('-inf', '-120'))
    return dict(integrated_lufs=value('I'), lra_lu=value('LRA'), true_peak_dbtp=value('Peak'))


def fade_edges(samples, rate, rows):
    """Raised-cosine fades at every sentence edge so no sentence starts or stops on a nonzero sample."""
    out = samples.copy()
    ramp = lambda n: .5 - .5 * np.cos(np.linspace(0, np.pi, n))
    for row in rows:
        a = int(round(row['start'] * rate))
        b = min(len(out), int(round((row['start'] + row['duration']) * rate)))
        n_in, n_out = min(int(FADE_IN * rate), (b - a) // 4), min(int(FADE_OUT * rate), (b - a) // 4)
        out[a:a + n_in] *= ramp(n_in)
        out[b - n_out:b] *= ramp(n_out)[::-1]
    return out


def floors(samples, rate, rows):
    """Noise floor where a listener hears it: inside sentences (quietest 50 ms) and in the pauses between them."""
    samples = samples if samples.ndim == 1 else samples[:, 0]
    window = int(.05 * rate)
    db = lambda v: round(float(20 * np.log10(max(v, 1e-6))), 1)
    inside, pauses, edges = [], [], []
    for row, following in zip(rows, rows[1:] + [None]):
        a, b = int(round(row['start'] * rate)), int(round((row['start'] + row['duration']) * rate))
        part = samples[a:b]
        edges += [abs(part[0]), abs(part[-1])]
        rms = np.sqrt(np.convolve(part ** 2, np.ones(window) / window, mode='valid'))
        inside.append(rms.min())
        if following:
            gap = samples[b + int(.02 * rate):int(round(following['start'] * rate))]
            if len(gap):
                pauses.append(np.sqrt(np.mean(gap ** 2)))
    return dict(sentence_floor_db_median=db(np.median(inside)), pause_rms_db_max=db(max(pauses) if pauses else 0),
                edge_sample_abs_max=round(float(max(edges)), 4))


def ffmpeg(source, target, chain):
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(source), '-af', chain, '-c:a', 'pcm_s24le', str(target)], check=True)


def master(narration, timing, output):
    rows = json.loads(Path(timing).read_text())
    samples, rate = sf.read(narration, dtype='float64')
    assert samples.ndim == 1 and rows, 'Mono narration with sentence timing required'
    before = dict(loudness(narration, dualmono=True), **floors(samples, rate, rows))
    with tempfile.TemporaryDirectory() as scratch:
        faded, shaped = Path(scratch) / 'faded.wav', Path(scratch) / 'shaped.wav'
        sf.write(faded, fade_edges(samples, rate, rows), rate, subtype='FLOAT')
        ffmpeg(faded, shaped, SHAPE)
        gain = TARGET_LUFS - loudness(shaped)['integrated_lufs']
        for _ in range(3):  # the limiter shaves a little loudness off peaks; correct the gain and run again
            chain = f'volume={gain:.3f}dB,' + LIMIT.format(limit=10 ** (CEILING_DBTP / 20))
            ffmpeg(shaped, output, chain)
            after = loudness(output)
            if abs(after['integrated_lufs'] - TARGET_LUFS) <= .2:
                break
            gain += TARGET_LUFS - after['integrated_lufs']
    mastered, mastered_rate = sf.read(output, dtype='float64')
    assert abs(len(mastered) / mastered_rate - len(samples) / rate) < .005, 'Mastering changed the timeline'
    after = dict(after, **floors(mastered, mastered_rate, rows))
    assert abs(after['integrated_lufs'] - TARGET_LUFS) <= .5 and after['true_peak_dbtp'] <= CEILING_DBTP + .3, after
    return dict(target_lufs=TARGET_LUFS, ceiling_dbtp=CEILING_DBTP, fade_in_s=FADE_IN, fade_out_s=FADE_OUT,
                chain=[f'raised-cosine edge fades on {len(rows)} sentences', SHAPE, chain], before=before, after=after)


if __name__ == '__main__':
    import sys
    print(json.dumps(master(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])), indent=2))
