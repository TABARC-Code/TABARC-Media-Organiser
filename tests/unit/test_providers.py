import io
import json
import urllib.error

import pytest

from tabarc_media.identity import providers as P


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeNet:
    """Replays a queue of responses. Each item is a dict (JSON), an exception, or a status code."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append((req, timeout))
        item = self.replies.pop(0)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, int):
            raise urllib.error.HTTPError(req.full_url, item, "x", {}, None)
        return FakeResp(json.dumps(item).encode("utf-8"))


def client(net, sleeps=None):
    sleeps = [] if sleeps is None else sleeps
    return P.Client("ops@example.org", opener=net, sleep=sleeps.append,
                    clock=lambda: 1000.0, attempts=3), sleeps


def test_contact_is_required_and_sent_in_user_agent():
    with pytest.raises(ValueError):
        P.Client("   ")
    net = FakeNet([])
    c, _ = client(net)
    c.get_json("tvmaze", "https://example.test/x", {"q": "a"})
    req, timeout = net.requests[0]
    assert req.get_header("User-agent").startswith("TABARC-Media-Organiser/")
    assert "(ops@example.org)" in req.get_header("User-agent")
    assert timeout == P.DEFAULT_TIMEOUT


def test_tvmaze_parses_shows_and_keeps_provenance():
    net = FakeNet([
        {"score": 0.9, "show": {"id": 1, "name": "Show Name", "premiered": "2008-01-20",
                                "language": "English", "url": "https://www.tvmaze.com/shows/1"}},
        {"score": 0.5, "show": {"id": None, "name": "Broken"}},
    ])
    c, _ = client(net)
    found = P.TVmaze(c).search("show name")
    assert [f.title for f in found] == ["Show Name"]
    assert found[0].year == 2008
    assert found[0].kind == "tv"
    assert found[0].licence.startswith("CC BY-SA 4.0")
    assert found[0].source_url == "https://www.tvmaze.com/shows/1"


def test_wikidata_filters_non_media_and_reads_year_from_description():
    net = FakeNet({"search": [
        {"id": "Q1", "label": "Some Film", "description": "1994 film directed by someone"},
        {"id": "Q2", "label": "Some Film", "description": "village in Wales"},
        {"id": "Q3", "label": "Series", "description": "American television series, 2001 to 2005"},
    ]})
    c, _ = client(net)
    found = P.Wikidata(c).search("some film")
    assert [(f.provider_id, f.kind, f.year) for f in found] == [
        ("Q1", "film", 1994), ("Q3", "tv", 2001)]
    assert found[0].licence == "CC0 1.0"
    assert "language=en-gb" in net.requests[0][0].full_url


def test_openlibrary_parses_docs():
    net = FakeNet({"docs": [
        {"key": "/works/OL1W", "title": "A Book", "first_publish_year": 1999,
         "language": ["eng"]},
        {"title": "No key here"},
    ]})
    c, _ = client(net)
    found = P.OpenLibrary(c).search("a book")
    assert len(found) == 1
    assert found[0].kind == "book" and found[0].year == 1999 and found[0].language == "eng"


def test_retries_transient_then_succeeds():
    net = FakeNet(429, 503, [])
    c, sleeps = client(net)
    assert P.TVmaze(c).search("x") == []
    assert len(net.requests) == 3
    # Backoff doubles from 1 second. The limiter shares the same sleep, so check
    # both backoff steps are present rather than an exact list.
    assert 1.0 in sleeps and 2.0 in sleeps


def test_permanent_error_is_not_retried():
    net = FakeNet(404)
    c, sleeps = client(net)
    with pytest.raises(P.ProviderError) as info:
        P.TVmaze(c).search("x")
    assert info.value.transient is False
    assert len(net.requests) == 1
    assert sleeps == []


def test_timeout_gives_up_after_attempts_and_raises_transient():
    net = FakeNet(TimeoutError(), TimeoutError(), TimeoutError())
    c, _ = client(net)
    with pytest.raises(P.ProviderError) as info:
        P.Wikidata(c).search("x")
    assert info.value.transient is True
    assert len(net.requests) == 3


def test_bad_json_is_permanent():
    class BadResp(FakeResp):
        pass

    def opener(req, timeout=None):
        return BadResp(b"<html>not json</html>")

    c = P.Client("ops@example.org", opener=opener, sleep=lambda s: None, clock=lambda: 0.0)
    with pytest.raises(P.ProviderError) as info:
        P.OpenLibrary(c).search("x")
    assert info.value.transient is False


def test_rate_limiter_waits_the_remaining_gap():
    now = [100.0]
    sleeps = []
    lim = P.RateLimiter(1.0, clock=lambda: now[0], sleep=sleeps.append)
    lim.wait()
    now[0] = 100.25
    lim.wait()
    assert sleeps == [pytest.approx(0.75)]


def _throttled_then_ok(retry_after):
    state = {"n": 0}
    sleeps = []

    def opener(req, timeout=None):
        state["n"] += 1
        if state["n"] == 1:
            hdrs = {"Retry-After": retry_after} if retry_after is not None else {}
            raise urllib.error.HTTPError(req.full_url, 429, "slow down", hdrs, None)
        return FakeResp(json.dumps([]).encode("utf-8"))

    c = P.Client("ops@example.org", opener=opener, sleep=sleeps.append,
                 clock=lambda: 1000.0, attempts=3)
    return c, sleeps


def test_retry_after_seconds_is_honoured():
    c, sleeps = _throttled_then_ok("7")
    c.get_json("tvmaze", "https://example.test/x", {})
    assert 7.0 in sleeps


def test_retry_after_is_capped():
    c, sleeps = _throttled_then_ok("86400")
    c.get_json("tvmaze", "https://example.test/x", {})
    assert P.MAX_RETRY_AFTER in sleeps and 86400.0 not in sleeps


@pytest.mark.parametrize("value", [None, "Wed, 21 Oct 2026 07:28:00 GMT", "soon"])
def test_missing_or_unparseable_retry_after_falls_back_to_backoff(value):
    c, sleeps = _throttled_then_ok(value)
    c.get_json("tvmaze", "https://example.test/x", {})
    assert 1.0 in sleeps
