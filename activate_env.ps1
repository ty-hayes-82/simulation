# PowerShell script to activate the virtual environment
# Usage: .\activate_env.ps1

Write-Host "Activating virtual environment..." -ForegroundColor Green
& ".\.venv\Scripts\Activate.ps1"
Write-Host "Virtual environment activated!" -ForegroundColor Green
Write-Host "You can now run your Python scripts." -ForegroundColor Yellow

