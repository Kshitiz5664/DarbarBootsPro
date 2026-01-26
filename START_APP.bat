@echo off
echo ====================================
echo Starting Darbar Boots Application
echo ====================================

docker compose up -d --build

echo Waiting for containers...
timeout /t 5 >nul

docker exec -it darbar_django python manage.py migrate
docker exec -it darbar_django python manage.py collectstatic --noinput

echo ====================================
echo Application is READY
echo Open: http://localhost:8000
echo ====================================

pause
