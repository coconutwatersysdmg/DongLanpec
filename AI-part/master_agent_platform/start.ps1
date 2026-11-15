$ErrorActionPreference = 'Stop'
$platformDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$platformCandidates = @()
if ($env:DONGLANPEC_AGENT_PYTHON) { $platformCandidates += $env:DONGLANPEC_AGENT_PYTHON }
$platformCandidates += (Join-Path $platformDir 'python\python.exe')
if ($env:CONDA_PREFIX) { $platformCandidates += (Join-Path $env:CONDA_PREFIX 'python.exe') }
$platformCandidates += @('D:\ProgramData\anaconda3\python.exe', 'C:\ProgramData\anaconda3\python.exe', (Join-Path $env:USERPROFILE 'anaconda3\python.exe'), (Join-Path $env:USERPROFILE 'miniconda3\python.exe'), 'D:\python3.9\python.exe')
$platformPython = $platformCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $platformPython) {
    $platformCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $platformCommand) { throw 'No Python environment found. Set DONGLANPEC_AGENT_PYTHON to python.exe.' }
    $platformPython = $platformCommand.Source
}
& $platformPython (Join-Path $platformDir 'run.py')
exit $LASTEXITCODE
