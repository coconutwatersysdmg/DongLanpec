$ErrorActionPreference = 'Stop'
$platformDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$platformPython = if ($env:DONGLANPEC_AGENT_PYTHON) { $env:DONGLANPEC_AGENT_PYTHON } elseif (Test-Path -LiteralPath 'D:\python3.9\python.exe') { 'D:\python3.9\python.exe' } else { 'python' }
& $platformPython (Join-Path $platformDir 'run.py')
exit $LASTEXITCODE
