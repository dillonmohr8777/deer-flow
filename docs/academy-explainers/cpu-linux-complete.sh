#!/bin/sh
set -eu
jobroot="$HOME/academy-work-20261021-cpu"
cd "$jobroot"
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 UV_NO_CACHE=1 UV_LINK_MODE=copy
export HF_HUB_DISABLE_XET=1 WANDB_MODE=disabled
# Revised parent-authorized7GiB setup from19.23GiB baseline; 1GiB outputs;
# preserve hard10GiB free floor. Conservative setup floor12.25GiB.
check_budget() {
 free_kib=$(df -Pk /mnt/c | awk 'NR==2{print $4}')
 need_kib=${1:-0}
 if [ $((free_kib-need_kib)) -lt 12845056 ]; then printf 'BUDGET_STOP %s %s\n' "$free_kib" "$need_kib"; exit 2; fi
 printf 'BUDGET_READBACK free_kib=%s reserve_kib=%s\n' "$free_kib" "$need_kib"
}
check_budget 1950000
"$jobroot/tools/uv" pip install --python .venv/bin/python --dry-run wandb accelerate datasets > dependency-plan.txt 2>&1
cat dependency-plan.txt
.venv/bin/python - <<'PY'
import json,re,urllib.request
from packaging.tags import sys_tags
from packaging.utils import parse_wheel_filename
from pathlib import Path
text=Path('dependency-plan.txt').read_text()
allowed=set(sys_tags()); rows=[]
for name,version in re.findall(r'^\s*\+\s+([a-zA-Z0-9_-]+)==([^\s]+)',text,re.M):
 data=json.load(urllib.request.urlopen(f'https://pypi.org/pypi/{name}/{version}/json'))
 candidates=[]
 for file in data['urls']:
  if file['filename'].endswith('.whl'):
   _,_,_,tags=parse_wheel_filename(file['filename'])
   if tags & allowed:candidates.append(file)
 assert candidates, f'No measured compatible wheel: {name}'
 file=min(candidates,key=lambda item:item['size'])
 rows.append(dict(name=name,version=version,wheel=file['filename'],compressed_bytes=file['size']))
size=sum(row['compressed_bytes'] for row in rows)
receipt=dict(packages=rows,total_compressed_bytes=size,conservative_install_reserve_bytes=size*5)
assert size*5 <= 600*1024**2, 'Dependencies exceed reserved600MiB; inspect before install'
Path('dependency-size-plan.json').write_text(json.dumps(receipt,indent=2))
print('DEPENDENCY_SIZE_PLAN',json.dumps(receipt))
PY
"$jobroot/tools/uv" pip install --python .venv/bin/python wandb accelerate datasets
check_budget 1400000
.venv/bin/python - <<'PY'
import json,shutil
from pathlib import Path
import torch
torch.set_num_threads(2)
from f5_tts.api import F5TTS
root=Path.cwd()
# Root filesystem is sparse. All budget checks use host physical C:.
receipt=dict(status='dependencies-ready',initial_free_bytes=int(19.23*1024**3),free_bytes=shutil.disk_usage('/mnt/c').free,budget_bytes=7*1024**3,minimum_free_bytes=int(12.25*1024**3),threads=2,model_loaded=False,torch=torch.__version__)
(root/'setup-receipt.json').write_text(json.dumps(receipt,indent=2))
print('LINUX_F5_IMPORT_OK',json.dumps(receipt))
PY
