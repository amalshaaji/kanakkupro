"""Measure authenticated HTTP latency against disposable local review data only."""

import argparse
import json
import math
import os
import statistics
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from scripts.pilot_review import guard_database


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def measure(base, path, cookie, *, status=200, contains=None, excludes=None):
    request = Request(base + path, headers={"Cookie": cookie})
    started = time.perf_counter()
    try:
        response = build_opener(NoRedirect).open(request, timeout=20)
    except HTTPError as error:
        response = error
    with response:
        body = response.read(4 * 1024 * 1024)
        if response.code != status:
            raise RuntimeError("Unexpected HTTP response during local benchmark.")
        if contains and contains not in body:
            raise RuntimeError("Expected workspace content was not rendered.")
        if excludes and excludes in body:
            raise RuntimeError("Foreign workspace content appeared in a response.")
    return (time.perf_counter() - started) * 1000


def summarize(values):
    ordered = sorted(values)
    return {
        "samples": len(values),
        "median_ms": round(statistics.median(values), 2),
        "p95_ms": round(ordered[math.ceil(len(ordered) * 0.95) - 1], 2),
        "max_ms": round(max(values), 2),
    }


def benchmark(base, *, include_pdf=False):
    from apps.sales.models import Invoice, InvoiceLine
    from apps.sales.selectors import financial_summary
    from apps.tenants.models import Tenant
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.db import close_old_connections
    from django.test import Client
    from django.urls import reverse

    guard_database(settings.DATABASES["default"])
    target = urlsplit(base)
    if (
        target.scheme != "http"
        or target.hostname not in {"127.0.0.1", "localhost"}
        or target.path
        or target.query
        or target.fragment
        or target.username
    ):
        raise ValueError("Benchmark only an explicit localhost HTTP origin.")
    workspaces = []
    before = {}
    for label in ("a", "b"):
        tenant = Tenant.objects.get(slug=f"review-{label}")
        owner = get_user_model().objects.get(email=f"owner-{label}@pilot.example.test")
        invoice = Invoice.objects.filter(tenant=tenant, kind="invoice").first()
        if invoice is None:
            raise ValueError("Prepare the synthetic review dataset first.")
        before[label] = financial_summary(tenant)
        workspaces.append((label, tenant, owner, invoice))
    workers = []
    for index in range(4):
        label, tenant, owner, invoice = workspaces[index % 2]
        client = Client()
        client.force_login(owner)
        session_name = settings.SESSION_COOKIE_NAME
        cookie = f"{session_name}={client.cookies[session_name].value}"
        paths = [
            (name, reverse(name))
            for name in (
                "dashboard:index",
                "customers:list",
                "catalog:list",
                "sales:list",
                "reports:financial",
                "dashboard:pilot",
            )
        ]
        paths.append(("sales:detail", reverse("sales:detail", args=[invoice.pk])))
        workers.append((cookie, label, tenant.name, paths))
    first_ms = measure(base, workers[0][3][0][1], workers[0][0])
    for cookie, _, _, paths in workers:
        measure(base, paths[0][1], cookie)

    def worker(data):
        cookie, label, name, paths = data
        rows = []
        other_name = b"Review business B" if label == "a" else b"Review business A"
        for _ in range(3):
            for route, path in paths:
                rows.append(
                    (
                        route,
                        measure(
                            base,
                            path,
                            cookie,
                            contains=name.encode(),
                            excludes=other_name,
                        ),
                    )
                )
        return rows

    by_route = defaultdict(list)
    with ThreadPoolExecutor(max_workers=4) as pool:
        for rows in pool.map(worker, workers):
            for route, elapsed in rows:
                by_route[route].append(elapsed)
    # A valid session from one business cannot read another business's document.
    foreign_ms = measure(
        base,
        reverse("sales:detail", args=[workspaces[1][3].pk]),
        workers[0][0],
        status=404,
        excludes=b"Review business B",
    )
    pdf_ms = None
    if include_pdf:
        pdf_ms = measure(
            base,
            reverse("sales:pdf", args=[workspaces[0][3].pk]),
            workers[0][0],
            contains=b"%PDF",
        )
    for label, tenant, _, _ in workspaces:
        if financial_summary(tenant) != before[label]:
            raise RuntimeError("Financial totals changed during read-only HTTP checks.")
    close_old_connections()
    return {
        "captured_at": datetime.now(UTC).isoformat(),
        "scope": "isolated_local_http",
        "concurrent_clients": 4,
        "tenants": 2,
        "customers": 100,
        "catalog_items": 20,
        "issued_documents": Invoice.objects.count(),
        "invoice_lines": InvoiceLine.objects.count(),
        "routes": {route: summarize(values) for route, values in by_route.items()},
        "all_routes": summarize([v for values in by_route.values() for v in values]),
        "first_measured_request_ms": round(first_ms, 2),
        "cross_tenant_404_ms": round(foreign_ms, 2),
        "pdf_ms": round(pdf_ms, 2) if pdf_ms is not None else None,
        "financial_totals_unchanged": True,
        "production_latency_or_cold_start_verified": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--include-pdf", action="store_true")
    args = parser.parse_args()
    try:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.review")
        if os.environ["DJANGO_SETTINGS_MODULE"] != "config.settings.review":
            raise ValueError("Use isolated review settings.")
        import django

        django.setup()
        result = benchmark(args.base_url.rstrip("/"), include_pdf=args.include_pdf)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))
    except Exception:
        print(
            "Local pilot benchmark failed; inspect the isolated review server.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
