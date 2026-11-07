"""Download only the official CPU-compatible F5 weights into this owned workspace."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
from huggingface_hub import hf_hub_download

root = Path(sys.argv[1])
setup = json.loads((root / 'setup-receipt.json').read_text(encoding='utf-8-sig'))
start = setup['initial_free_bytes']
volume = Path('/mnt/c') if sys.platform == 'linux' else root
budget = setup.get('budget_bytes', 6*1024**3)
minimum = setup.get('minimum_free_bytes', 10*1024**3)

def check(extra=0):
    free = shutil.disk_usage(volume).free
    assert free-extra >= minimum and start-free+extra <= budget, 'CPU setup/cache budget reached'

check(1_500_000_000)
paths = []
for repo, name in [('SWivid/F5-TTS', 'F5TTS_v1_Base/model_1250000.safetensors'),
                   ('charactr/vocos-mel-24khz', 'config.yaml'),
                   ('charactr/vocos-mel-24khz', 'pytorch_model.bin')]:
    folder = root / 'models' / repo.split('/')[1]
    target = Path(hf_hub_download(repo_id=repo, filename=name, local_dir=folder))
    digest = hashlib.file_digest(target.open('rb'), 'sha256').hexdigest()
    if name.endswith('safetensors'):
        assert digest == '670900fd14e6c458b95da6e9ed317cdb20dbaf7a1c02ac06a05475a9d32b6a38', 'Official checkpoint hash mismatch'
    paths.append(dict(repo=repo, file=str(target), bytes=target.stat().st_size, sha256=digest))
    check()
receipt = dict(status='weights-downloaded-not-loaded', initial_free_bytes=start,
               free_bytes=shutil.disk_usage(volume).free, files=paths)
(root / 'models-receipt.json').write_text(json.dumps(receipt, indent=2))
print(json.dumps(receipt), flush=True)
