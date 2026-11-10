import logging

import pytest
from oauth2_provider.models import AccessToken, RefreshToken

from apps.users.tokens import access_token_for, issue_tokens


@pytest.mark.django_db
def test_issues_one_token_pair_for_the_configured_web_client(monkeypatch, user, web_client):
    monkeypatch.setenv("OAUTH_CLIENT_ID", "web-client-test")

    tokens = issue_tokens(user)

    assert tokens.refresh_token
    assert tokens.expires_in == 3600
    token = access_token_for(tokens.access_token)
    assert token.user == user
    assert token.application == web_client
    assert RefreshToken.objects.get(access_token=token).user == user


@pytest.mark.django_db
def test_issues_and_reports_nothing_while_oauth_client_id_is_unset(monkeypatch, user, caplog):
    monkeypatch.delenv("OAUTH_CLIENT_ID", raising=False)

    with caplog.at_level(logging.WARNING):
        assert issue_tokens(user) is None
    assert caplog.records == []


@pytest.mark.django_db
def test_issues_nothing_and_reports_an_unknown_client_id(monkeypatch, user, caplog):
    monkeypatch.setenv("OAUTH_CLIENT_ID", "no-such-client")

    with caplog.at_level(logging.WARNING):
        assert issue_tokens(user) is None
    assert AccessToken.objects.count() == 0
    assert "OAUTH_CLIENT_ID" in caplog.text
