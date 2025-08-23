Param(
  [string]$CourseDir = "courses/pinetree_country_club",
  [string[]]$Scenarios = @("real_tee_sheet"),
  [int[]]$Orders = @(10,14,18,28,36,44),
  [string]$RunnerRange = "1-4",
  [int]$RunsPer = 5,
  [double]$RunnerSpeed = 6.0,
  [int]$PrepTime = 10,
  [double]$TargetOnTime = 0.95,
  [double]$MaxFailedRate = 0.05,
  [double]$MaxP90 = 40,
  [int]$TopHoles = 3,
  [string]$ExpName = "baseline",
  [int]$ParallelJobs = 2,
  [switch]$Resume,
  [int]$BaseSeed,
  [int]$MaxRetries = 2
)

Write-Host "[1/3] Running staffing experiments..." -ForegroundColor Cyan

# Build the command with optional parameters
$cmd = @(
  "python", "scripts/optimization/run_staffing_experiments.py",
  "--base-course-dir", $CourseDir
)
$cmd += "--tee-scenarios"
$cmd += $Scenarios
$cmd += "--order-levels"
$cmd += $Orders
$cmd += @(
  "--runner-range", $RunnerRange,
  "--runs-per", $RunsPer,
  "--runner-speed", $RunnerSpeed,
  "--prep-time", $PrepTime,
  "--prefer-real-tee-config",
  "--target-on-time", $TargetOnTime,
  "--max-failed-rate", $MaxFailedRate,
  "--max-p90", $MaxP90,
  "--top-holes", $TopHoles,
  "--exp-name", $ExpName,
  "--parallel-jobs", $ParallelJobs,
  "--max-retries", $MaxRetries
)

if ($Resume) {
  $cmd += "--resume"
}

if ($BaseSeed) {
  $cmd += @("--base-seed", $BaseSeed)
}

Write-Host "Command: $($cmd -join ' ')" -ForegroundColor Gray
& $cmd[0] $cmd[1..($cmd.Length-1)]

Write-Host "[2/3] Collecting flat metrics CSV..." -ForegroundColor Cyan
python scripts/optimization/collect_metrics_csv.py `
  --root outputs/experiments/$ExpName `
  --out outputs/experiments/$ExpName/metrics_flat.csv

Write-Host "[3/3] Generating Gemini executive summary..." -ForegroundColor Cyan
python scripts/optimization/gemini_client.py `
  --exp-root outputs/experiments/$ExpName

Write-Host "Done. See outputs/experiments/$ExpName for summaries, metrics, and executive summary." -ForegroundColor Green


