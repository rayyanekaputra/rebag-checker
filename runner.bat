@echo off

echo Step 1
cd /d D:\coding\rebag_semi_automate

echo Step 2
call .venv\Scripts\activate.bat

echo Step 3
python --version

echo Step 4
python rebag_semi_automate_v5.py

pause