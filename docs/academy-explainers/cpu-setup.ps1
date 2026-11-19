$ErrorActionPreference='Stop'
$root='C:\Users\dillo\academy-work-20261021'
New-Item -ItemType Directory -Path $root -Force | Out-Null
$startFree=(Get-PSDrive C).Free
if($startFree -lt 16GB){throw 'Need10GiB reserve plus6GiB setup budget'}
$env:UV_CACHE_DIR=Join-Path $root 'uv-cache'
$env:HF_HOME=Join-Path $root 'hf-cache'
$env:OMP_NUM_THREADS='2'
$env:MKL_NUM_THREADS='2'
$uv=(Get-Command uv.exe -ErrorAction Stop).Source
& 'C:\Users\dillo\AppData\Roaming\uv\python\cpython-3.11.15-windows-x86_64-none\python.exe' -m venv --copies (Join-Path $root '.venv-cpu')
if($LASTEXITCODE -ne 0){throw 'venv setup failed'}
$python=Join-Path $root '.venv-cpu\Scripts\python.exe'
& $uv pip install --python $python --index-url https://download.pytorch.org/whl/cpu torch==2.8.0 torchaudio==2.8.0
if($LASTEXITCODE -ne 0){throw 'CPU Torch installation failed'}
if((Get-PSDrive C).Free -lt 10GB -or ($startFree-(Get-PSDrive C).Free) -gt 6GB){throw 'Setup disk budget reached'}
& $uv pip install --python $python --no-deps f5-tts==1.1.22
if($LASTEXITCODE -ne 0){throw 'Official F5 package failed'}
& $uv pip install --python $python 'numpy<2.4' soundfile librosa matplotlib pydub pypinyin rjieba safetensors hydra-core torchdiffeq transformers vocos ema-pytorch x-transformers cached-path tomli transformers-stream-generator unidecode
if($LASTEXITCODE -ne 0){throw 'Inference dependencies failed'}
if((Get-PSDrive C).Free -lt 10GB -or ($startFree-(Get-PSDrive C).Free) -gt 6GB){throw 'Setup disk budget reached'}
& $python -c "import torch; torch.set_num_threads(2); from f5_tts.api import F5TTS; print('F5_IMPORT_OK',torch.__version__,'cuda_available',torch.cuda.is_available())"
if($LASTEXITCODE -ne 0){throw 'F5 import failed'}
$receipt=@{status='dependencies-ready';initial_free_bytes=$startFree;free_bytes=(Get-PSDrive C).Free;used_delta_bytes=($startFree-(Get-PSDrive C).Free);threads=2;model_loaded=$false;reference_transferred=$false}
$receipt | ConvertTo-Json | Set-Content (Join-Path $root 'setup-receipt.json')
