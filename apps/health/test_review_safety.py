import pytest
from scripts.pilot_review import guard_database


@pytest.mark.parametrize(
    ("host", "name"),
    [
        ("db.neon.tech", "test_pilot_review_example"),
        ("localhost", "production"),
        ("localhost.example.com", "test_pilot_review_example"),
        ("", "test_pilot_review_example"),
        ("127.0.0.1", ""),
    ],
)
def test_review_tools_refuse_hosted_or_non_review_databases(host, name):
    with pytest.raises(ValueError):
        guard_database({"HOST": host, "NAME": name})


def test_review_tools_accept_only_the_named_local_review_database():
    guard_database({"HOST": "127.0.0.1", "NAME": "test_pilot_review_disposable"})


def test_review_tools_refuse_hidden_remote_connection_overrides(monkeypatch):
    local = {"HOST": "localhost", "NAME": "test_pilot_review_disposable"}
    with pytest.raises(ValueError):
        guard_database({**local, "OPTIONS": {"hostaddr": "203.0.113.1"}})
    monkeypatch.setenv("PGHOSTADDR", "203.0.113.1")
    with pytest.raises(ValueError):
        guard_database(local)
