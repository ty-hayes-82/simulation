#!/usr/bin/env powershell
<#
.SYNOPSIS
    Generates an executive summary for a golf course simulation using Google Gemini.
.DESCRIPTION
    This script is a wrapper around the `generate_gemini_executive_summary.py` Python script.
    It takes a path to a simulation output directory, validates it, and then invokes the
    Python script to perform the analysis and generate a summary.
.PARAMETER SimulationDir
    The relative path to the simulation output directory. This is a mandatory parameter.
.EXAMPLE
    .\scripts\analysis\run_gemini_summary.ps1 -SimulationDir "output/keswick_hall/20250901_125539_real_tee_sheet"
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$SimulationDir
)

$ErrorActionPreference = "Stop"

try {
    # Get the script's directory to resolve other paths relative to it.
    # $PSScriptRoot is an automatic variable that contains the directory of the script.
    $RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")

    # Construct absolute paths
    $AbsoluteSimDir = Join-Path $RepoRoot $SimulationDir
    $PythonScriptPath = Join-Path $RepoRoot "scripts\analysis\generate_gemini_executive_summary.py"

    # Validate paths
    if (-not (Test-Path -Path $AbsoluteSimDir -PathType Container)) {
        throw "Simulation directory not found: $AbsoluteSimDir"
    }

    if (-not (Test-Path -Path $PythonScriptPath -PathType Leaf)) {
        throw "Gemini analysis script not found: $PythonScriptPath"
    }

    # Write-Host "Activating Python virtual environment if activate_env.ps1 exists..."
    # $envActivateScript = Join-Path $RepoRoot "activate_env.ps1"
    # if (Test-Path $envActivateScript) {
    #     . $envActivateScript
    # }

    Write-Host "Running Gemini executive summary for: $AbsoluteSimDir"

    # Execute the python script
    # We pass the relative path from the repo root, as the python script might expect that.
    python $PythonScriptPath $SimulationDir
    
    Write-Host "Executive summary generation complete."

}
catch {
    Write-Host -ForegroundColor Red "An error occurred:"
    Write-Host -ForegroundColor Red $_.Exception.Message
    exit 1
}
