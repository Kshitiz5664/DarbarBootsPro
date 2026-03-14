@echo off

echo ==========================================
echo Starting Darbar Boot House System
echo ==========================================

docker compose up -d --build

echo Waiting for system startup...
timeout /t 25 >nul

echo ==========================================
echo SYSTEM READY
echo Open browser: http://localhost:8000
echo ==========================================

start http://localhost:8000

pause
