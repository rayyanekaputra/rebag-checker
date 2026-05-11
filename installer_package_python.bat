@echo off

cd /d D:\coding\rebag_semi_automate

echo =========================
echo Creating virtual env
echo =========================

python -m venv .venv

echo.
echo =========================
echo Activating virtual env
echo =========================

call .venv\Scripts\activate.bat

echo.
echo =========================
echo Installing requirements
echo =========================

python -m pip install --upgrade pip

pip install -r requirements.txt

echo.
echo =========================
echo DONE
echo =========================

pause
