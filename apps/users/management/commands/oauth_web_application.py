import os

from django.core.management.base import BaseCommand
from oauth2_provider.models import Application


class Command(BaseCommand):
    help = "Create the public web client whose client_id is OAUTH_CLIENT_ID; nothing when unset"

    def handle(self, *args, **options):
        uid = os.environ.get("OAUTH_CLIENT_ID", "").strip()
        if not uid:
            return
        Application.objects.get_or_create(
            client_id=uid,
            defaults={
                "name": "todolist web",
                "client_type": Application.CLIENT_PUBLIC,
                "authorization_grant_type": Application.GRANT_PASSWORD,
            },
        )
