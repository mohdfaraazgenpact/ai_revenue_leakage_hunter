# Task runner. Usage: .\scripts\tasks.ps1 <setup|smoke|generate|extract|run|eval|test|lint|app|offline|all>
param([Parameter(Position = 0)][string]$Task = "all")

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Py = Join-Path $Root ".venv\Scripts\python.exe"

function Invoke-Py([string[]]$PyArgs) {
    & $Py @PyArgs
    if ($LASTEXITCODE -ne 0) { throw "Failed: python $($PyArgs -join ' ')" }
}

switch ($Task) {
    "setup" {
        if (-not (Test-Path $Py)) { python -m venv .venv }
        Invoke-Py @("-m", "pip", "install", "--timeout", "30", "--retries", "5", "-r", "requirements.txt")
        & (Join-Path $Root ".venv\Scripts\pre-commit.exe") install
        if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host "Created .env - add GEMINI_API_KEY" }
    }
    "smoke"    { Invoke-Py @("-m", "src.llm.smoke") }
    "generate" { Invoke-Py @("-m", "src.generate_synthetic_data") }
    "extract"  { Invoke-Py @("-m", "src.extract.run_extraction", "--extractor", "both"); Invoke-Py @("-m", "src.evaluate_extraction") }
    "run"      { Invoke-Py @("-m", "src.pipeline", "--explain") }
    "eval"     { Invoke-Py @("-m", "src.evaluate", "--check") }
    "test"     { Invoke-Py @("-m", "pytest", "-q") }
    "lint"     { Invoke-Py @("-m", "ruff", "check", "."); Invoke-Py @("-m", "ruff", "format", "--check", ".") }
    "app"      { Invoke-Py @("-m", "streamlit", "run", "app/streamlit_app.py") }
    "offline"  { $env:LLM_CACHE_MODE = "readonly"; Invoke-Py @("-m", "streamlit", "run", "app/streamlit_app.py") }
    "all"      { Invoke-Py @("-m", "src.build_all", "--check"); Invoke-Py @("-m", "pytest", "-q") }
    default    { Write-Host "Unknown task '$Task'"; exit 1 }
}
