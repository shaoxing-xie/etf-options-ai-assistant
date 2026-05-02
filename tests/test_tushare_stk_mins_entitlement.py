from src.tushare_stk_mins_entitlement import is_stk_mins_entitled


def test_stk_mins_denied_default_profile(monkeypatch):
    monkeypatch.delenv("TUSHARE_FORCE_STK_MINS", raising=False)
    monkeypatch.delenv("TUSHARE_STK_MINS_ENTITLED", raising=False)
    assert is_stk_mins_entitled({"tushare": {"permission_profile": "2000"}}) is False


def test_stk_mins_allowed_profile(monkeypatch):
    monkeypatch.delenv("TUSHARE_FORCE_STK_MINS", raising=False)
    assert is_stk_mins_entitled({"tushare": {"permission_profile": "minute_table2"}}) is True


def test_stk_mins_force_env(monkeypatch):
    monkeypatch.setenv("TUSHARE_FORCE_STK_MINS", "1")
    assert is_stk_mins_entitled({"tushare": {"permission_profile": "2000"}}) is True
