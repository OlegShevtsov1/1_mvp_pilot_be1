import pytest
from django.core.management import call_command
from oauth2_provider.models import Application


@pytest.mark.django_db
def test_does_nothing_while_oauth_client_id_is_unset(monkeypatch):
    monkeypatch.delenv("OAUTH_CLIENT_ID", raising=False)

    call_command("oauth_web_application")

    assert Application.objects.count() == 0


@pytest.mark.django_db
def test_creates_the_public_web_client_once(monkeypatch):
    monkeypatch.setenv("OAUTH_CLIENT_ID", " web-client-test ")

    call_command("oauth_web_application")
    call_command("oauth_web_application")

    application = Application.objects.get()
    assert application.client_id == "web-client-test"
    assert application.name == "todolist web"
    assert application.client_type == Application.CLIENT_PUBLIC
