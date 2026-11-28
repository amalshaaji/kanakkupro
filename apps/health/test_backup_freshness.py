import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from scripts.check_backup_freshness import (
    MAX_RESPONSE_BYTES,
    MAX_RUNS,
    UPLOAD_STEP,
    check_backup_freshness,
    github_reader,
    main,
)

NOW = datetime(2026, 11, 28, 10, tzinfo=UTC)


def run(run_id=10, **changes):
    return {
        "id": run_id,
        "run_attempt": 2,
        "status": "completed",
        "conclusion": "success",
        "head_branch": "main",
        "event": "workflow_dispatch",
        "path": ".github/workflows/backup.yml",
        **changes,
    }


def job(*, age=timedelta(hours=2), **step_changes):
    started = NOW - age
    return {
        "status": "completed",
        "conclusion": "success",
        "steps": [
            {
                "name": UPLOAD_STEP,
                "status": "completed",
                "conclusion": "success",
                "started_at": started.isoformat(),
                "completed_at": (started + timedelta(minutes=1)).isoformat(),
                **step_changes,
            }
        ],
    }


def reader(runs, jobs):
    def read(path):
        if path.startswith("workflows/"):
            return {"workflow_runs": runs}
        return {"jobs": jobs[path]}

    return read


@pytest.mark.parametrize(
    ("age", "expected"),
    [(timedelta(hours=24), "fresh"), (timedelta(hours=24, seconds=1), "stale")],
)
def test_age_uses_capture_step_start_not_recent_completion(age, expected):
    read = reader(
        [run()],
        {
            "runs/10/attempts/2/jobs?per_page=100": [
                job(age=age, completed_at=NOW.isoformat())
            ]
        },
    )
    result = check_backup_freshness(read, now=NOW)
    assert result["status"] == expected
    assert result["event"] == "workflow_dispatch"  # Not proof of a scheduled run.


def test_storage_checks_skips_and_failed_uploads_cannot_refresh_backup_age():
    read = reader(
        [run(12), run(11), run(10)],
        {
            "runs/12/attempts/2/jobs?per_page=100": [job(name="Check storage access")],
            "runs/11/attempts/2/jobs?per_page=100": [job(conclusion="skipped")],
            "runs/10/attempts/2/jobs?per_page=100": [job(conclusion="failure")],
        },
    )
    assert check_backup_freshness(read, now=NOW)["status"] == "no_verified_upload"


@pytest.mark.parametrize(
    "change",
    [
        {"conclusion": "failure"},
        {"status": "in_progress"},
        {"head_branch": "untrusted"},
        {"path": ".github/workflows/other.yml"},
        {"event": "pull_request"},
    ],
)
def test_nonrelease_runs_never_qualify(change):
    assert check_backup_freshness(reader([run(**change)], {}), now=NOW)["status"] == (
        "no_verified_upload"
    )


def test_only_successful_job_from_current_attempt_qualifies():
    calls = []

    def read(path):
        calls.append(path)
        if path.startswith("workflows/"):
            return {"workflow_runs": [run(run_attempt=3)]}
        return {"jobs": [{**job(), "conclusion": "failure"}]}

    assert check_backup_freshness(read, now=NOW)["status"] == "no_verified_upload"
    assert calls[-1] == "runs/10/attempts/3/jobs?per_page=100"


def test_latest_actual_upload_wins_even_when_old_run_is_rerun():
    read = reader(
        [run(12), run(10)],
        {
            "runs/12/attempts/2/jobs?per_page=100": [job(age=timedelta(days=2))],
            "runs/10/attempts/2/jobs?per_page=100": [job(age=timedelta(hours=1))],
        },
    )
    assert check_backup_freshness(read, now=NOW)["run_id"] == 10


@pytest.mark.parametrize(
    "timestamp", ["not-a-date", "2026-11-28T10:00:00", "2099-01-01T00:00:00Z"]
)
def test_invalid_or_future_timestamps_fail_closed(timestamp):
    read = reader(
        [run()], {"runs/10/attempts/2/jobs?per_page=100": [job(started_at=timestamp)]}
    )
    with pytest.raises(ValueError):
        check_backup_freshness(read, now=NOW)


def test_run_scan_is_bounded_and_absence_fails_closed():
    calls = []

    def read(path):
        calls.append(path)
        if path.startswith("workflows/"):
            return {"workflow_runs": [run(i + 1) for i in range(MAX_RUNS + 10)]}
        return {"jobs": []}

    assert check_backup_freshness(read, now=NOW)["status"] == "no_verified_upload"
    assert len(calls) == MAX_RUNS + 1


@pytest.mark.parametrize(
    "repository", ["", "../private", "owner/repo?token=private", "owner/.."]
)
def test_repository_cannot_change_api_destination(repository):
    with pytest.raises(ValueError):
        github_reader(repository, "private-token")


def test_api_reader_bounds_response_and_uses_only_read_request():
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = b"x" * (MAX_RESPONSE_BYTES + 1)
    opener = MagicMock()
    opener.open.return_value = response
    with patch("scripts.check_backup_freshness.build_opener", return_value=opener):
        with pytest.raises(ValueError, match="monitoring limit"):
            github_reader("owner/repo", "private-token")("workflows/backup.yml/runs")
    request = opener.open.call_args.args[0]
    assert request.get_method() == "GET"
    assert request.full_url.startswith("https://api.github.com/repos/owner/repo/")
    assert "private-token" not in request.full_url


def test_cli_api_failure_does_not_expose_token_or_error(capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    with patch(
        "scripts.check_backup_freshness.github_reader",
        side_effect=RuntimeError("private-token and private response"),
    ):
        assert main() == 1
    assert json.loads(capsys.readouterr().out) == {"status": "verification_unavailable"}


@pytest.mark.parametrize("status", ["fresh", "stale", "no_verified_upload"])
def test_cli_exit_status_drives_workflow_failure(status, capsys):
    with (
        patch("scripts.check_backup_freshness.github_reader"),
        patch(
            "scripts.check_backup_freshness.check_backup_freshness",
            return_value={"status": status},
        ),
    ):
        assert main() == (0 if status == "fresh" else 1)
    assert json.loads(capsys.readouterr().out)["status"] == status
