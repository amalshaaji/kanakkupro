"""Production security defaults with Render's assigned staging hostname."""

import os

hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "")
if hostname:
    os.environ.setdefault("ALLOWED_HOSTS", hostname)
    os.environ.setdefault("CSRF_TRUSTED_ORIGINS", f"https://{hostname}")

from .production import *  # noqa: E402, F403
