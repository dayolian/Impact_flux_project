@echo off
cd /d "%~dp0"

echo Step 1: Generating 200px crops and lat/lon (skips already-done hits)...
python crop_generator.py
echo.
echo Step 2: Starting review server...
python review_server.py
pause
