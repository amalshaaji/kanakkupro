"""Read-only availability check. Does not authenticate, send mail, or write data."""

import json
import os
from urllib.request import urlopen


def check_service(base_url):
    if not base_url.startswith("https://"):
        raise ValueError("Monitoring requires an HTTPS service URL.")
    with urlopen(base_url.rstrip("/") + "/health/ready/", timeout=90) as response:
        if (
            response.status != 200
            or json.loads(response.read(4096)).get("status") != "ok"
        ):
            raise RuntimeError("Service is not ready.")


if __name__ == "__main__":
    try:
        check_service(os.environ.get("SERVICE_URL", "https://kanakkupro.onrender.com"))
    except Exception:
        # Response bodies and connection details are deliberately excluded.
        print("Readiness check failed. Inspect Render logs and provider status.")
        raise SystemExit(1) from None
    print("Service readiness verified.")
