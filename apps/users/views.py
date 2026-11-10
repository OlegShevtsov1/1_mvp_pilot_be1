from django.http import HttpResponse
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import ValidationFailed
from apps.users import accounts
from apps.users.limits import check_sign_up_limit, limit_failed_sign_ins
from apps.users.tokens import revoke_device


class UsersView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        check_sign_up_limit(request)
        result = accounts.sign_up(request.data)
        if result.errors:
            raise ValidationFailed(result.errors, message="User could not be created")
        data = {
            "user_id": result.user.id,
            "email": result.user.email,
            "authentication_token": result.user.authentication_token,
        }
        if result.tokens:
            data |= {
                "access_token": result.tokens.access_token,
                "refresh_token": result.tokens.refresh_token,
                "expires_in": result.tokens.expires_in,
            }
        return Response(
            {"status": "success", "message": "User created successfully", "data": data}, status=201
        )


class SignInView(APIView):
    """Legacy sign-in, kept until the cutoff; new clients sign in through /oauth/token."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        return limit_failed_sign_ins(
            request, lambda: self._sign_in(request), is_failure=lambda r: r.status_code == 401
        )

    def _sign_in(self, request):
        result = accounts.sign_in(request.data)
        if result.errors:
            return Response({"status": "error", "message": result.errors[0]}, status=401)
        return Response(
            {
                "status": "success",
                "message": "Signed in successfully",
                "data": {
                    "user_id": result.user.id,
                    "email": result.user.email,
                    "authentication_token": result.user.authentication_token,
                },
            }
        )


class SignOutView(APIView):
    """Ends this device's access (AC-11)."""

    def post(self, request):
        revoke_device(request.user, request.auth)
        return HttpResponse(status=204)


class MeView(APIView):
    def get(self, request):
        user = request.user
        return Response(
            {
                "status": "success",
                "message": "User profile",
                "data": {"user_id": user.id, "email": user.email},
            }
        )
