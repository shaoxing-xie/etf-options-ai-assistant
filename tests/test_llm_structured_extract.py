"""llm_structured_extract：解析 OpenClaw 模型链 + LLM JSON 输出（mock）。"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

def test_resolve_openclaw_chat_model(tmp_path: Path) -> None:
    from plugins.utils.llm_structured_extract import resolve_openclaw_chat_model

    oc = {
        "models": {
            "providers": {
                "test-prov": {
                    "baseUrl": "https://example.invalid/v1",
                    "apiKey": "sk-unit-test-key",
                    "models": [{"id": "vendor/model-one"}],
                }
            }
        }
    }
    p = tmp_path / "openclaw.json"
    p.write_text(json.dumps(oc), encoding="utf-8")
    base, key, mid, err = resolve_openclaw_chat_model(
        "test-prov/vendor/model-one",
        openclaw_path=p,
    )
    assert err is None
    assert base == "https://example.invalid/v1"
    assert key == "sk-unit-test-key"
    assert mid == "vendor/model-one"


def test_resolve_unknown_provider(tmp_path: Path) -> None:
    from plugins.utils.llm_structured_extract import resolve_openclaw_chat_model

    p = tmp_path / "openclaw.json"
    p.write_text(json.dumps({"models": {"providers": {}}}), encoding="utf-8")
    _, _, _, err = resolve_openclaw_chat_model("nope/x/y", openclaw_path=p)
    assert err and "unknown_provider" in err


@patch("plugins.utils.llm_structured_extract.resolve_openclaw_chat_model")
@patch("openai.OpenAI")
def test_llm_json_from_unstructured_happy(mock_openai, mock_resolve) -> None:
    from plugins.utils.llm_structured_extract import llm_json_from_unstructured

    mock_resolve.return_value = ("https://example.com/v1", "k", "m1", None)
    msg = MagicMock()
    msg.content = '{"indices":[{"code":"^GSPC","price":null,"change_pct":0.1,"direction":"up","evidence":""}]}'
    mock_openai.return_value.chat.completions.create.return_value = MagicMock(choices=[MagicMock(message=msg)])

    cfg = {
        "llm_structured_extract": {
            "enabled": True,
            "timeout_seconds": 30,
            "max_tokens": 500,
            "temperature": 0.0,
            "profiles": {"default": {"models": ["p/m"]}},
        }
    }
    r = llm_json_from_unstructured(
        "snippet says S&P up 0.1%",
        "Extract per instructions.",
        profile="default",
        config=cfg,
    )
    assert r.get("success") is True
    data = r.get("data")
    assert isinstance(data, dict)
    assert data["indices"][0]["code"] == "^GSPC"


def test_tool_disabled(monkeypatch) -> None:
    import plugins.utils.llm_structured_extract as mod

    monkeypatch.setattr(mod, "_cfg_llm_extract", lambda c=None: {"enabled": False})
    r = mod.tool_llm_json_extract("x", "y", profile="default")
    assert r.get("success") is False
    assert "disabled" in str(r.get("message", ""))
