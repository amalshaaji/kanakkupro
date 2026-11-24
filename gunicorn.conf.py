import os

bind = f"0.0.0.0:{int(os.environ.get('PORT', '10000'))}"
workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
worker_class = "sync"
timeout = 90
graceful_timeout = 30
max_requests = 500
max_requests_jitter = 50
# Django's structured logger records routes without query strings or tokens.
accesslog = None
errorlog = "-"
forwarded_allow_ips = ""  # Transport trust is configured explicitly in Django.
