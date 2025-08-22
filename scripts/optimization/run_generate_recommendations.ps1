Param(
  [string]$ExpRoot = "outputs/experiments/baseline",
  [string]$Course = "Pinetree Country Club",
  [string]$Out = "docs/recommendations_baseline.md"
)

python scripts/optimization/generate_recommendations.py `
  --exp-root $ExpRoot `
  --course $Course `
  --out $Out

Write-Host "Recommendations written to $Out" -ForegroundColor Green


