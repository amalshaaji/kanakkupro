import base64
import hashlib
import os

from allauth.mfa.adapter import DefaultMFAAdapter
from allauth.mfa.models import Authenticator
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def encryption_cipher():
    keys = settings.MFA_ENCRYPTION_KEYS
    if not keys:
        # Development/tests only. Production validation requires separate keys.
        if settings.DEPLOYMENT_ENVIRONMENT == "production":
            raise ImproperlyConfigured("MFA encryption keys are required.")
        if settings.DEPLOYMENT_ENVIRONMENT == "development" and not os.environ.get(
            "SECRET_KEY"
        ):
            raise ImproperlyConfigured(
                "Set a persistent SECRET_KEY or MFA_ENCRYPTION_KEYS "
                "before enrolling MFA."
            )
        keys = [
            base64.urlsafe_b64encode(
                hashlib.sha256(settings.SECRET_KEY.encode()).digest()
            ).decode()
        ]
    return MultiFernet([Fernet(key.encode("ascii")) for key in keys])


class EncryptedMFAAdapter(DefaultMFAAdapter):
    def encrypt(self, text):
        return "fernet:v1:" + encryption_cipher().encrypt(text.encode()).decode("ascii")

    def decrypt(self, encrypted_text):
        if not encrypted_text.startswith("fernet:v1:"):
            raise ImproperlyConfigured(
                "Unrecognized MFA ciphertext; restore the correct encryption keys."
            )
        try:
            return (
                encryption_cipher()
                .decrypt(encrypted_text.removeprefix("fernet:v1:").encode("ascii"))
                .decode()
            )
        except (InvalidToken, UnicodeError) as error:
            raise ImproperlyConfigured(
                "MFA secret cannot be decrypted with the configured keys."
            ) from error

    def can_delete_authenticator(self, authenticator):
        if authenticator.type == Authenticator.Type.TOTP and (
            authenticator.user.is_staff or authenticator.user.is_superuser
        ):
            return False
        return super().can_delete_authenticator(authenticator)
