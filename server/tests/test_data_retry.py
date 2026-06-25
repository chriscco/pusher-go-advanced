import pytest
from app.data.retry import with_retry


def test_returns_first_success():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return "ok"

    assert with_retry(fn, attempts=3, base_delay=0.0) == "ok"
    assert calls["n"] == 1


def test_retries_until_success():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("boom")
        return "ok"

    assert with_retry(fn, attempts=3, base_delay=0.0) == "ok"
    assert calls["n"] == 3


def test_raises_after_exhausting():
    def fn():
        raise RuntimeError("always")

    with pytest.raises(RuntimeError):
        with_retry(fn, attempts=2, base_delay=0.0)
