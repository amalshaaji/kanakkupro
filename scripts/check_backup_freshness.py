"""Read-only backup freshness signal from successful, upload-verified Actions jobs."""

import json
import os
import re
from datetime import UTC, datetime, timedelta
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_RESPONSE_BYTES = 1024 * 1024
MAX_RUNS = 20
MAX_AGE = timedelta(hours=24)
UPLOAD_STEP = "Encrypt and upload backup"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the read-only Actions token to a redirected destination.
        return None


def github_reader(repository, token=""):
    if not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+", repository) or (
        repository.split("/")[-1] in {".", ".."}
    ):
        raise ValueError("Use a GitHub owner/repository name.")
    base = f"https://api.github.com/repos/{repository}/actions/"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "KanakkuPro-backup-freshness",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    opener = build_opener(NoRedirect())

    def read(path):
        with opener.open(Request(base + path, headers=headers), timeout=10) as response:
            data = response.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            raise ValueError("GitHub response exceeds the monitoring limit.")
        return json.loads(data)

    return read


def check_backup_freshness(read, *, now=None):
    now = now or datetime.now(UTC)
    if now.utcoffset() is None:
        raise ValueError("Monitoring requires a timezone-aware clock.")
    runs = read(
        f"workflows/backup.yml/runs?branch=main&status=success&per_page={MAX_RUNS}"
    )["workflow_runs"]
    newest = None
    for run in runs[:MAX_RUNS]:
        if (
            run.get("status") != "completed"
            or run.get("conclusion") != "success"
            or run.get("head_branch") != "main"
            or run.get("event") not in {"schedule", "workflow_dispatch"}
            or run.get("path") != ".github/workflows/backup.yml"
        ):
            continue
        run_id, attempt = run["id"], run["run_attempt"]
        if (
            type(run_id) is not int
            or type(attempt) is not int
            or min(run_id, attempt) < 1
        ):
            raise ValueError("Invalid workflow attempt metadata.")
        jobs = read(f"runs/{run_id}/attempts/{attempt}/jobs?per_page=100")["jobs"]
        for job in jobs:
            if job.get("status") != "completed" or job.get("conclusion") != "success":
                continue
            for step in job.get("steps", []):
                if (
                    step.get("name") != UPLOAD_STEP
                    or step.get("status") != "completed"
                    or step.get("conclusion") != "success"
                ):
                    continue
                # Step start precedes the dump: completion/retry time must not
                # make an old source snapshot look newer than it really is.
                started = datetime.fromisoformat(step["started_at"])
                finished = datetime.fromisoformat(step["completed_at"])
                if (
                    started.utcoffset() is None
                    or finished.utcoffset() is None
                    or not started <= finished <= now
                ):
                    raise ValueError("Invalid upload verification timestamps.")
                if newest is None or started > newest["verified_upload_started_at"]:
                    newest = {
                        "verified_upload_started_at": started,
                        "run_id": run_id,
                        "event": run["event"],
                    }
    if newest is None:
        return {"status": "no_verified_upload", "max_age_hours": 24}
    started = newest.pop("verified_upload_started_at")
    age = now - started
    return {
        **newest,
        "status": "fresh" if age <= MAX_AGE else "stale",
        "verified_upload_started_at": started.isoformat(),
        "age_hours": round(age.total_seconds() / 3600, 3),
        "max_age_hours": 24,
    }


def main():
    try:
        result = check_backup_freshness(
            github_reader(
                os.environ.get("GITHUB_REPOSITORY", ""),
                os.environ.get("GITHUB_TOKEN", ""),
            )
        )
    except Exception:
        # API errors, tokens and response bodies never enter workflow logs.
        print(json.dumps({"status": "verification_unavailable"}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "fresh" else 1


if __name__ == "__main__":
    raise SystemExit(main())
