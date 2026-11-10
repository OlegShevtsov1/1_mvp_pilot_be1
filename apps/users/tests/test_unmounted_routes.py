import pytest

from apps.users.models import User

# Conventional /users/sign_in and /users/sign_up routes are not mounted: they would check passwords
# without the failed sign-in limit and create users without the sign-up limit.


@pytest.mark.django_db
def test_answers_404_to_a_sign_in_at_users_sign_in_even_with_the_right_password(client, user):
    response = client.post(
        "/users/sign_in",
        {"user": {"email": user.email, "password": "password"}},
        content_type="application/json",
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_answers_404_to_a_sign_up_at_users_and_creates_no_user(client, user):
    response = client.post(
        "/users",
        {
            "user": {
                "email": "door@example.com",
                "password": "password123",
                "password_confirmation": "password123",
            }
        },
        content_type="application/json",
    )

    assert response.status_code == 404
    assert User.objects.count() == 1
