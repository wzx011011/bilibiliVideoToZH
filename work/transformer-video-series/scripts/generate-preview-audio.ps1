param(
  [ValidateRange(1, 5)]
  [int]$Episode = 1,
  [string]$Voice = 'zh-CN-XiaoxiaoNeural',
  [string]$Rate = '-4%'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$workRoot = Split-Path -Parent $projectRoot
$python = Join-Path $workRoot 'gpt-sovits\.venv\Scripts\python.exe'
$generator = Join-Path $PSScriptRoot 'generate-neural-audio.py'

if (-not (Test-Path $python)) {
  throw "Neural TTS Python runtime was not found at $python"
}

& $python $generator --episode $Episode --voice $Voice "--rate=$Rate" --strip-leading-directive
if ($LASTEXITCODE -ne 0) {
  throw "Neural narration generation failed for episode $Episode"
}
