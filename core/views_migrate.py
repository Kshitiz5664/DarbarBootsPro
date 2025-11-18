from django.http import HttpResponse
from django.core.management import call_command

def run_migrations(request):
    try:
        call_command("makemigrations")
        call_command("migrate")
        return HttpResponse("✔ Migrations completed successfully!")
    except Exception as e:
        return HttpResponse(f"❌ Migration error: {e}")
