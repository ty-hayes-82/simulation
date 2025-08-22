Param(
  [string]$CourseDir = "courses/pinetree_country_club",
  [string[]]$Scenarios = @("typical_weekday", "busy_weekend"),
  [int[]]$Orders = @(10,14,18,28,36,44),
  [string]$RunnerRange = "1-4",
  [int]$RunsPer = 5,
  [double]$RunnerSpeed = 6.0,
  [int]$PrepTime = 10,
  [double]$TargetOnTime = 0.95,
  [double]$MaxFailedRate = 0.05,
  [double]$MaxP90 = 40,
  [int]$TopHoles = 3,
  [string]$ExpName = "baseline"
)

Write-Host "[1/3] Running staffing experiments..." -ForegroundColor Cyan
python scripts/optimization/run_staffing_experiments.py `
  --base-course-dir $CourseDir `
  --tee-scenarios $($Scenarios -join ' ') `
  --order-levels $($Orders -join ' ') `
  --runner-range $RunnerRange `
  --runs-per $RunsPer `
  --runner-speed $RunnerSpeed `
  --prep-time $PrepTime `
  --target-on-time $TargetOnTime `
  --max-failed-rate $MaxFailedRate `
  --max-p90 $MaxP90 `
  --top-holes $TopHoles `
  --exp-name $ExpName

Write-Host "[2/3] Collecting flat metrics CSV..." -ForegroundColor Cyan
python scripts/optimization/collect_metrics_csv.py `
  --root outputs/experiments/$ExpName `
  --out outputs/experiments/$ExpName/metrics_flat.csv

Write-Host "Done. See outputs/experiments/$ExpName for summaries and per-scenario recommendations." -ForegroundColor Green


