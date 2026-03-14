#!/bin/sh

echo "Applying migrations..."
python manage.py migrate

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Creating superuser if not exists..."

python manage.py shell << END
import os
from django.contrib.auth import get_user_model

User = get_user_model()

username = os.getenv("DJANGO_SUPERUSER_USERNAME", "admin")
email = os.getenv("DJANGO_SUPERUSER_EMAIL", "admin@darbarboots.com")
password = os.getenv("DJANGO_SUPERUSER_PASSWORD", "Admin@123")

user = User.objects.filter(username=username).first()

if not user:
    print("Creating superuser...")
    user = User.objects.create_superuser(username=username, email=email, password=password)
else:
    print("User exists, ensuring superuser permissions and resetting password...")
    user.is_staff = True
    user.is_superuser = True
    user.set_password(password)
    user.save()

print("Admin user ready.")
END

echo "Starting server..."

gunicorn DarbarBootsPro.wsgi:application --bind 0.0.0.0:8000
