#!/bin/sh
set -eu
jobroot="$HOME/academy-work-20261021-cpu"
mkdir -p "$jobroot/tools"
cd "$jobroot"
start_kib=$(df -Pk /mnt/c | awk 'NR==2{print $4}')
printf '%s\n' "$start_kib" > setup-start-kib.txt
# Shared C: physical headroom governs the sparse WSL filesystem. Additional
# setup budget2.8GiB; retain at least13.25GiB from19.23GiB initial baseline.
check_budget() {
 free_kib=$(df -Pk /mnt/c | awk 'NR==2{print $4}')
 need_kib=${1:-0}
 if [ $((free_kib-need_kib)) -lt 13893632 ] || [ $((start_kib-free_kib+need_kib)) -gt 2936012 ]; then
  printf 'BUDGET_STOP free_kib=%s extra_kib=%s\n' "$free_kib" "$need_kib"; exit 2
 fi
 printf 'BUDGET_READBACK free_kib=%s delta_kib=%s\n' "$free_kib" "$((start_kib-free_kib))"
}
check_budget 1300000
export UV_INSTALL_DIR="$jobroot/tools" UV_NO_MODIFY_PATH=1 UV_NO_CACHE=1
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 HF_HUB_DISABLE_XET=1
curl -LsSf https://astral.sh/uv/install.sh -o uv-install.sh
sh uv-install.sh
"$jobroot/tools/uv" python install 3.11 --install-dir "$jobroot/python"
export UV_PYTHON_INSTALL_DIR="$jobroot/python"
python_path=$("$jobroot/tools/uv" python find 3.11)
"$jobroot/tools/uv" venv --python "$python_path" .venv
"$jobroot/tools/uv" pip install --python .venv/bin/python --index-url https://download.pytorch.org/whl/cpu torch==2.8.0 torchaudio==2.8.0
check_budget 1500000
"$jobroot/tools/uv" pip install --python .venv/bin/python --no-deps f5-tts==1.1.22
"$jobroot/tools/uv" pip install --python .venv/bin/python 'numpy<2.4' soundfile librosa matplotlib pydub pypinyin rjieba safetensors hydra-core torchdiffeq transformers vocos ema-pytorch x-transformers cached-path tomli transformers-stream-generator unidecode
check_budget 1500000
.venv/bin/python -c "import torch; torch.set_num_threads(2); from f5_tts.api import F5TTS; print('LINUX_F5_IMPORT_OK',torch.__version__,torch.cuda.is_available())"
.venv/bin/python - <<'PYCODE'
import json,shutil
from pathlib import Path
root=Path.cwd()
(root/'setup-receipt.json').write_text(json.dumps(dict(status='dependencies-ready',initial_free_bytes=int((root/'setup-start-kib.txt').read_text())*1024,free_bytes=shutil.disk_usage('/mnt/c').free,budget_bytes=int(2.8*1024**3),minimum_free_bytes=int(13.25*1024**3),threads=2,model_loaded=False),indent=2))
PYCODE
