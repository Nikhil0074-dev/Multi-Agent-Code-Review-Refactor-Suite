import pytest

from app.config import Config, ConfigError


def test_defaults_need_api_key_for_hosted():
    with pytest.raises(ConfigError, match="LLM_API_KEY"):
        Config.from_env({})


def test_mock_backend_needs_no_key():
    cfg = Config.from_env({"LLM_BACKEND": "mock"})
    assert cfg.backend == "mock" and cfg.mode == "debate" and cfg.resolved_model == "gpt-4o-mini"


def test_values_are_parsed():
    cfg = Config.from_env({
        "LLM_BACKEND": "local", "REVIEW_MODE": "single", "MAX_WORKERS": "5",
        "MIN_CONFIDENCE": "0.7", "ENABLE_INLINE_COMMENTS": "yes", "PR_NUMBER": "42",
        "OLLAMA_URL": "http://host:1/",
    })
    assert cfg.resolved_model == "llama3.1"
    assert (cfg.mode, cfg.max_workers, cfg.min_confidence, cfg.inline_comments, cfg.pr_number) == ("single", 5, 0.7, True, 42)
    assert cfg.ollama_url == "http://host:1"


@pytest.mark.parametrize("env,msg", [
    ({"LLM_BACKEND": "nope"}, "LLM_BACKEND"),
    ({"LLM_BACKEND": "mock", "REVIEW_MODE": "x"}, "REVIEW_MODE"),
    ({"LLM_BACKEND": "mock", "MAX_WORKERS": "abc"}, "MAX_WORKERS"),
    ({"LLM_BACKEND": "mock", "MAX_WORKERS": "0"}, "MAX_WORKERS"),
    ({"LLM_BACKEND": "mock", "MIN_CONFIDENCE": "2"}, "MIN_CONFIDENCE"),
    ({"LLM_BACKEND": "mock", "ENABLE_INLINE_COMMENTS": "maybe"}, "ENABLE_INLINE_COMMENTS"),
    ({"LLM_BACKEND": "mock", "PR_NUMBER": "x"}, "PR_NUMBER"),
    ({"LLM_BACKEND": "mock", "PR_NUMBER": "0"}, "PR_NUMBER"),
])
def test_bad_values_raise(env, msg):
    with pytest.raises(ConfigError, match=msg):
        Config.from_env(env)
