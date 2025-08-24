$ErrorActionPreference = 'Stop'

param(
    [switch]$GenerateRecommendations,
    [string]$CourseName = 'Pinetree Country Club'
)

# Resolve repo root (this script lives in scripts/optimization)
$repoRoot = Resolve-Path "$PSScriptRoot\..\.."
Set-Location $repoRoot

# Activate local env if available
if (Test-Path .\activate_env.ps1) {
    . .\activate_env.ps1
}

$expName = 'sla95_baseline'
$expRoot = Join-Path $repoRoot "outputs/experiments/$expName"
New-Item -ItemType Directory -Force -Path $expRoot | Out-Null

Write-Host "Running staffing optimization → $expName" -ForegroundColor Cyan

$pythonExe = 'py'
$argsList = @(
    'scripts/optimization/run_staffing_experiments.py',
    '--base-course-dir','courses/pinetree_country_club',
    '--tee-scenarios','real_tee_sheet',
    '--order-levels','20','28','36','44',
    '--runner-range','1-3',
    '--runs-per','5',
    '--runner-speed','6.0',
    '--prep-time','10',
    '--opening-ramp-min','0',
    '--target-on-time','0.95',
    '--max-failed-rate','0.05',
    '--max-p90','40',
    '--run-blocking-variants',
    '--parallel-jobs','3',
    '--prefer-real-tee-config',
    '--exp-name',$expName
)

$logPath = Join-Path $expRoot 'run.log'
& $pythonExe @argsList 2>&1 | Tee-Object -FilePath $logPath

if ($LASTEXITCODE -ne 0) {
    Write-Host "Run failed with exit code $LASTEXITCODE. See log: $logPath" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "Run completed. Staffing summary at: $expRoot\staffing_summary.csv" -ForegroundColor Green

if ($GenerateRecommendations) {
    $outMd = Join-Path $repoRoot "docs/recommendations_${expName}.md"
    Write-Host "Generating recommendations → $outMd" -ForegroundColor Cyan
    & $pythonExe 'scripts/optimization/generate_recommendations.py' `
        --exp-root $expRoot `
        --course $CourseName `
        --out $outMd
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Recommendations generation failed with exit code $LASTEXITCODE" -ForegroundColor Red
        exit $LASTEXITCODE
    }
    Write-Host "Recommendations written to: $outMd" -ForegroundColor Green
}

Write-Host "Done. View live log with: Get-Content $logPath -Wait" -ForegroundColor Yellow


