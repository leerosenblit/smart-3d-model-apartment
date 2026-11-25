@echo off
setlocal
title RoomCraft 3D launcher
cd /d "%~dp0"

rem --- backend virtualenv + deps (first run only)
if not exist "backend\.venv\Scripts\python.exe" (
  echo Creating backend virtualenv...
  py -3.12 -m venv backend\.venv || py -3 -m venv backend\.venv || goto :error
  "backend\.venv\Scripts\python.exe" -m pip install -q -r backend\requirements.txt || goto :error
)

rem --- frontend deps (first run only)
if not exist "frontend\node_modules" (
  echo Installing frontend dependencies...
  pushd frontend
  call npm install --no-audit --no-fund || (popd & goto :error)
  popd
)

rem --- start both servers, each in its own window (close the windows to stop them)
start "RoomCraft API (:8000)" /D "%~dp0backend" cmd /k ""%~dp0backend\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"
start "RoomCraft Frontend (:5173)" /D "%~dp0frontend" cmd /k "npm run dev -- --host 127.0.0.1"

rem --- wait until the frontend answers (max ~60s), then open the browser
echo Waiting for the app to start...
set /a tries=0
:wait
set /a tries+=1
curl -s -o nul http://127.0.0.1:5173 && goto :open
if %tries% geq 60 goto :open
timeout /t 1 /nobreak >nul
goto :wait

:open
start "" http://localhost:5173
echo RoomCraft 3D is running. Close the two server windows to stop it.
timeout /t 3 /nobreak >nul
exit /b 0

:error
echo.
echo Setup failed. See the messages above.
pause
exit /b 1
