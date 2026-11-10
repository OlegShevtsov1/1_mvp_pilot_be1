import sentry_sdk
from django.apps import AppConfig


class ErrorsConfig(AppConfig):
    name = "apps.errors"
    label = "errors"

    def ready(self):
        from corsheaders.signals import check_request_enabled

        from apps.errors.cors import allow_configured_origin
        from apps.errors.sentry import sentry_options

        # Here rather than in settings: the environment default reads APP_ENVIRONMENT, which the
        # test settings override after base.py has run.
        sentry_sdk.init(**sentry_options())
        check_request_enabled.connect(allow_configured_origin, weak=False)
