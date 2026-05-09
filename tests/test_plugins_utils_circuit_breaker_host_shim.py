"""
Regression: symlinked ``plugins.data_collection`` (plugin repo) imports
``plugins.utils.circuit_breaker``; that package resolves to the **host**
``etf-options-ai-assistant/plugins/utils``, which must ship this module.
"""


def test_plugins_utils_circuit_breaker_importable():
    from plugins.utils import circuit_breaker as cb

    assert callable(cb.call_or_pass_through)
    assert callable(cb.get_breaker)


def test_call_or_pass_through_disabled_runs_fn():
    from plugins.utils.circuit_breaker import call_or_pass_through

    assert call_or_pass_through("t", lambda: {"success": True, "data": [1]}) == {
        "success": True,
        "data": [1],
    }
