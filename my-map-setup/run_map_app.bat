@echo off
title GPS Coordinate Selector and Map App Runner

echo Starting GPS Coordinate Selector...
echo.

REM Activate conda environment and run the Python script
conda activate my_gemini_env && python run_map_app.py

echo.
echo Press any key to close this window...
pause > nul
