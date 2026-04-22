from __future__ import annotations

from pathlib import Path


def test_orchestration_schemas_and_mappings_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    schema_text = (root / "data" / "meta" / "schema_registry.yaml").read_text(encoding="utf-8")
    mapping_text = (root / "data" / "meta" / "task_data_map.yaml").read_text(encoding="utf-8")
    contract_text = (root / "data" / "meta" / "data_contract_version.json").read_text(encoding="utf-8")
    for key in [
        "orchestration_event_v1",
        "orchestration_state_v1",
        "orchestration_timeline_v1",
        "task_dependency_health_v1",
    ]:
        assert key in schema_text
        assert key in contract_text
    assert "orchestration-event-writer" in mapping_text
    assert "task-dependency-health-aggregation" in mapping_text
