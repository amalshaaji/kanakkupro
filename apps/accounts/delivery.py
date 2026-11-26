"""Bound email outages without weakening verification or exposing provider errors."""

import logging
from smtplib import SMTPAuthenticationError, SMTPException

from django.core.mail.backends.smtp import EmailBackend
from django.shortcuts import render
from django.utils.cache import patch_cache_control

logger = logging.getLogger("kanakkupro.email")


class EmailDeliveryUnavailable(Exception):
    pass


class SafeSMTPBackend(EmailBackend):
    def send_messages(self, email_messages):
        try:
            return super().send_messages(email_messages)
        except (SMTPException, OSError) as error:
            reason = (
                "authentication"
                if isinstance(error, SMTPAuthenticationError)
                else "transport"
            )
            logger.error(
                "email_delivery_failed",
                extra={"dependency": "smtp", "delivery_reason": reason},
            )
            raise EmailDeliveryUnavailable from None


class EmailDeliveryMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if not isinstance(exception, EmailDeliveryUnavailable):
            return None
        response = render(request, "account/email_unavailable.html", status=503)
        patch_cache_control(response, private=True, no_store=True)
        response["Retry-After"] = "60"
        return response
