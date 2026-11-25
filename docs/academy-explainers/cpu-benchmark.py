"""One accepted sentence only. No source/reference upload, no external inference."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import time

parser = argparse.ArgumentParser()
parser.add_argument('root', type=Path)
parser.add_argument('--only', default='04-account-client-success')
args = parser.parse_args()
root = args.root.resolve()
assert not (root / 'HOLD.json').exists(), 'Held'
packet = json.loads((root / 'SCRIPT-ACCEPTED.json').read_text())
assert packet.get('accepted') is True and packet.get('course') == 'momentum-work'
row = next(row for row in packet['lessons'] if row['stem'] == args.only)
source = root / 'scripts' / (args.only + '.json')
sha = lambda path: hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()
assert sha(source) == row['sha256'], 'Source is not accepted'
ref = root / 'ref.wav'
assert ref.is_file(), 'Authorized reference required'
if packet.get('reference_sha256'):
    assert sha(ref) == packet['reference_sha256'], 'Reference differs from accepted source'
lesson = json.loads(source.read_text())
import re
sentences = re.split(r'(?<=[.!?])\s+', lesson['chapters'][0]['narration'])
text = next(sentence for sentence in sentences if 10 <= len(sentence.split()) <= 30)
models = json.loads((root / 'models-receipt.json').read_text())
model = Path(next(item['file'] for item in models['files'] if item['file'].endswith('safetensors')))
assert sha(model) == next(item['sha256'] for item in models['files'] if item['file'].endswith('safetensors'))
settings = dict(engine='pytorch-cpu', model='F5TTS_v1_Base', checkpoint_sha256=sha(model),
                method='euler', steps=32, seed=7, threads=2)
binding = dict(source_sha256=sha(source), reference_sha256=sha(ref), text=text, settings=settings)
job = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()[:16]
output = root / ('benchmark-' + job + '.wav')
assert not output.exists(), 'Preserve existing benchmark and inspect its receipt'
assert shutil.disk_usage('/mnt/c').free >= 10*1024**3
os.environ['OMP_NUM_THREADS'] = os.environ['MKL_NUM_THREADS'] = '2'
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['WANDB_MODE'] = 'disabled'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
import torch
import soundfile as sf
import numpy as np
torch.set_num_threads(2)
torch.set_num_interop_threads(2)
from f5_tts.api import F5TTS
started = time.monotonic()
engine = F5TTS(model='F5TTS_v1_Base', ckpt_file=str(model), device='cpu',
               vocoder_local_path=str(root / 'models/vocos-mel-24khz'), ode_method='euler')
load_seconds = time.monotonic() - started
started = time.monotonic()
partial = output.with_suffix('.pending.wav')
reference_text = 'Is this enough for you to be able to use my voice? Nice and deep, slow, relaxed, but knowledgeable.'
engine.infer(ref_file=str(ref), ref_text=reference_text, gen_text=text,
             nfe_step=32, seed=7, file_wave=str(partial), remove_silence=False)
samples, rate = sf.read(partial)
assert rate == 24000 and len(samples) > rate and np.isfinite(samples).all()
partial.replace(output)
wall = time.monotonic() - started
duration = len(samples)/rate
receipt = dict(status='benchmark-generated-unreviewed', binding=binding, output=str(output),
               sha256=sha(output), load_seconds=load_seconds, synth_seconds=wall,
               audio_seconds=duration, realtime_factor=wall/duration,
               sample_rate=rate, free_bytes=shutil.disk_usage('/mnt/c').free,
               note='ASR and actual own-voice/audio review still required; this is not a finished lesson.')
output.with_suffix('.json').write_text(json.dumps(receipt, indent=2))
print(json.dumps(receipt), flush=True)
