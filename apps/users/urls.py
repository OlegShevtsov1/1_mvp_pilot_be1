from django.urls import path

from apps.users import oauth, views

urlpatterns = [
    path("api/v1/users", views.UsersView.as_view()),
    path("api/v1/sign_in", views.SignInView.as_view()),
    path("api/v1/sign_out", views.SignOutView.as_view()),
    path("api/v1/me", views.MeView.as_view()),
    path("oauth/token", oauth.TokenView.as_view()),
    path("oauth/revoke", oauth.RevokeView.as_view()),
]
