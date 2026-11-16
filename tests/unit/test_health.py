"""C9: health and the uptime log (D-21)."""

from __future__ import annotations

from shared_layer.capabilities import health as cap
from shared_layer.contracts import contract_versions


def test_health_reports_seeds_contracts_and_writes_the_uptime_log(db):
    out = cap.run(db, cap.Input(), contracts=contract_versions())
    assert out.ok and out.status == "ok" and out.db_writable and out.db_path == ":memory:"
    assert out.seeds == {"claims": 9, "brand_rules": 12, "brand_policies": 1, "contacts": 20, "rubrics": 3}
    assert out.contracts == {"claims.registry": "1", "brand.policy": "1", "audience.consent": "1", "measurement": "1", "evaluation": "1", "observability": "1", "health": "1"}
    assert out.rubrics == ["claim_rule_v1", "digest_item_v1", "post_angle_v1"] and out.policy_versions == ["1"]
    assert out.uptime_s >= 0 and out.server_version
    assert db.conn.execute("SELECT COUNT(*) FROM health_log").fetchone()[0] == 1
    cap.run(db, cap.Input())
    assert db.conn.execute("SELECT COUNT(*) FROM health_log").fetchone()[0] == 2


def test_health_is_degraded_when_a_seed_is_empty(db):
    with db.conn:
        db.conn.execute("DELETE FROM claims")
    out = cap.run(db, cap.Input())
    assert out.status == "degraded" and out.seeds["claims"] == 0
