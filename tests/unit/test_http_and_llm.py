import io
import json
import urllib.error

import pytest

from app.config import Config
from app.http_util import HTTPFailure, request
from app.jsonutil import JSONExtractError, extract_json_object
from app.llm.hosted_client import HostedClient
from app.llm.local_client import LocalClient
from app.llm.provider import LLMError, MockLLMClient, create_client


class FakeResp:
    def __init__(self, body: bytes, status=200):
        self.status, self.headers, self._body = status, {"X": "y"}, body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


def http_error(code, body=b"", headers=None):
    return urllib.error.HTTPError("http://x", code, "err", headers or {}, io.BytesIO(body))


def scripted(*items):
    seq = list(items)
    seen = []

    def opener(req, timeout=None):
        seen.append(req)
        item = seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    opener.seen = seen
    return opener


def test_request_success_and_retry_then_success():
    sleeps = []
    op = scripted(http_error(503), FakeResp(b"ok"))
    status, _, body = request("GET", "https://x", urlopen=op, sleep=sleeps.append)
    assert (status, body) == (200, b"ok") and sleeps == [1.0]


def test_request_honours_retry_after_and_gives_up():
    sleeps = []
    op = scripted(http_error(429, headers={"Retry-After": "3"}), http_error(429), http_error(429))
    with pytest.raises(HTTPFailure) as ei:
        request("GET", "https://x", urlopen=op, sleep=sleeps.append, retries=2)
    assert ei.value.status == 429 and sleeps[0] == 3.0 and len(sleeps) == 2


def test_request_no_retry_on_client_error_and_network_error():
    with pytest.raises(HTTPFailure) as ei:
        request("GET", "https://x", urlopen=scripted(http_error(404, b"nope")), sleep=lambda s: None)
    assert ei.value.status == 404 and "nope" in ei.value.body
    with pytest.raises(HTTPFailure) as ei2:
        request("GET", "https://x", urlopen=scripted(urllib.error.URLError("down")), sleep=lambda s: None, retries=0)
    assert ei2.value.status == 0
    with pytest.raises(HTTPFailure):
        request("GET", "file:///etc/passwd")


def test_extract_json():
    assert extract_json_object('{"a": 1}') == {"a": 1}
    assert extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json_object('Sure! {"a": {"b": 2}} done') == {"a": {"b": 2}}
    for bad in ["", "   ", "no json", "[1,2]", '{"a": ', None]:
        with pytest.raises(JSONExtractError):
            extract_json_object(bad)


def chat(content):
    return FakeResp(json.dumps({"choices": [{"message": {"content": content}}]}).encode())


def test_hosted_client_ok_and_request_shape():
    op = scripted(chat('{"x": 1}'))
    c = HostedClient("k", "m", "https://api.test/v1/", urlopen=op)
    assert c.complete("sys", "usr") == '{"x": 1}'
    req = op.seen[0]
    body = json.loads(req.data)
    assert req.full_url == "https://api.test/v1/chat/completions"
    assert req.get_header("Authorization") == "Bearer k" and body["messages"][1]["content"] == "usr"
    assert c.stats.calls == 1 and c.stats.prompt_chars == 6


def test_hosted_client_drops_response_format_on_400():
    op = scripted(http_error(400, b"bad response_format"), chat("{}"))
    c = HostedClient("k", "m", urlopen=op)
    assert c.complete("s", "u") == "{}"
    assert "response_format" not in json.loads(op.seen[1].data)


@pytest.mark.parametrize("resp", [FakeResp(b"not json"), FakeResp(b'{"choices": []}'), chat("  ")])
def test_hosted_client_bad_responses(resp):
    with pytest.raises(LLMError):
        HostedClient("k", "m", urlopen=scripted(resp)).complete("s", "u")


def test_hosted_client_http_error_and_missing_key():
    with pytest.raises(LLMError, match="401"):
        HostedClient("k", "m", urlopen=scripted(http_error(401, b"no"))).complete("s", "u")
    with pytest.raises(LLMError):
        HostedClient("", "m")


def test_local_client():
    op = scripted(FakeResp(json.dumps({"message": {"content": '{"ok": true}'}}).encode()))
    c = LocalClient("http://h:1", "llama", urlopen=op)
    assert c.complete("s", "u") == '{"ok": true}'
    assert op.seen[0].full_url == "http://h:1/api/chat" and json.loads(op.seen[0].data)["format"] == "json"
    with pytest.raises(LLMError):
        LocalClient(urlopen=scripted(FakeResp(b"{}"))).complete("s", "u")


def test_mock_client_and_factory():
    m = MockLLMClient(responses=["first"])
    assert m.complete("s", "u") == "first"
    assert '"findings": []' in m.complete("s", "TASK: ANALYZE")
    assert "challenges" in m.complete("s", "TASK: CHALLENGE")
    assert isinstance(create_client(Config(backend="mock")), MockLLMClient)
    assert isinstance(create_client(Config(backend="local")), LocalClient)
    assert isinstance(create_client(Config(backend="hosted", api_key="k")), HostedClient)
