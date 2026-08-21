param(
  [ValidateSet('semantic', 'terms')]
  [string]$Profile = 'terms',
  [switch]$SkipCheck,
  [int]$Concurrency = 8
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$configPath = Join-Path $projectRoot 'pipeline.config.json'
$config = Get-Content -LiteralPath $configPath -Raw -Encoding utf8 | ConvertFrom-Json
$selected = $config.profiles.$Profile

if ($null -eq $selected) {
  throw "Unknown pipeline profile: $Profile"
}

function Resolve-ProjectPath([string]$relativePath) {
  return Join-Path $projectRoot ($relativePath -replace '/', '\\')
}

$timingPath = Resolve-ProjectPath $selected.timing
$outputPath = Resolve-ProjectPath $selected.output
$outputDirectory = Split-Path -Parent $outputPath
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null

$runtimeNode = 'C:\Users\106660\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin'
$runtimeFallback = 'C:\Users\106660\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback'
if (Test-Path $runtimeNode) { $env:PATH = "$runtimeNode;$env:PATH" }
if (Test-Path $runtimeFallback) { $env:PATH = "$runtimeFallback;$env:PATH" }

$pnpm = (Get-Command pnpm.cmd -ErrorAction SilentlyContinue).Source
if (-not $pnpm) {
  throw 'pnpm.cmd was not found. Install pnpm or load the Codex workspace runtime.'
}
$pythonCandidates = @(
  $env:TRANSFORMER_PIPELINE_PYTHON,
  'C:\Users\106660\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe',
  (Get-Command python.exe -ErrorAction SilentlyContinue).Source,
  (Get-Command python -ErrorAction SilentlyContinue).Source
)
$python = $pythonCandidates |
  Where-Object { $_ -and (Test-Path -LiteralPath $_) } |
  Select-Object -First 1
if (-not $python) {
  throw 'python.exe was not found. It is required for timing validation.'
}

Push-Location $projectRoot
try {
  if (-not $SkipCheck) {
    & $pnpm check
    if ($LASTEXITCODE -ne 0) { throw 'TypeScript check failed.' }
  }

  & $python (Join-Path $PSScriptRoot 'validate-timing.py') $timingPath
  if ($LASTEXITCODE -ne 0) { throw 'Timing validation failed.' }

  Write-Host "Rendering profile '$Profile' -> $($selected.composition)"
  & $pnpm exec remotion render src/index.ts $selected.composition $outputPath `
    '--codec=h264' "--concurrency=$Concurrency" '--log=info'
  if ($LASTEXITCODE -ne 0) { throw 'Remotion render failed.' }

  Write-Host "Rendered: $outputPath"
}
finally {
  Pop-Location
}
