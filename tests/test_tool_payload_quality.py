from src.tool_payload_quality import effective_quality_score, fused_confidence_hint, quality_warn_message


def test_effective_quality_score_missing_defaults():
    s, missing = effective_quality_score({})
    assert missing is True
    assert s == 75


def test_effective_quality_score_present():
    s, missing = effective_quality_score({"quality_score": 82})
    assert missing is False
    assert s == 82


def test_quality_warn_below_threshold():
    msg = quality_warn_message({"quality_score": 50})
    assert msg and "质量分" in msg


def test_fused_confidence_hint_shape():
    out = fused_confidence_hint(quality_score=80, technical_score=60, sentiment_dispersion=10.0)
    assert "fused_confidence" in out
    assert 0 <= out["fused_confidence"] <= 1
