"""Captures the events the Sentry SDK would send, without any network."""

from contextlib import contextmanager

import sentry_sdk
from sentry_sdk.transport import Transport

from apps.errors.sentry import sentry_options


class CaptureTransport(Transport):
    def __init__(self, options=None):
        super().__init__(options)
        self.events = []

    def capture_envelope(self, envelope):
        self.events.extend(item.payload.json for item in envelope.items if item.type == "event")


@contextmanager
def capture_sentry_events():
    """Yield the list of events sent while the block runs, through the app's own options."""
    transport = CaptureTransport()
    sentry_sdk.init(
        **{**sentry_options(), "dsn": "https://public@sentry.invalid/1", "transport": transport}
    )
    try:
        yield transport.events
    finally:
        sentry_sdk.init(**sentry_options())


def last_exception(event):
    return event["exception"]["values"][-1]
