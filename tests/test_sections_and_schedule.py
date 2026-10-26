import copy

from control_plane.seed import EXAMPLE_SPEC
from control_plane.service import create_agent
from harness.sections import missing_sections, requested_sections
from shared.fake_llm import FakeLLM
from shared.spec import apply_default_schedule


def test_requested_sections_come_from_the_goal_and_the_spec():
    titles = requested_sections(
        "Son 12 ayın aylık kırılımı ve ilk 5 ürün",
        {"spec": {"output": {"sections": ["Kanal"]}}},
    )
    assert titles[0] == "Kanal"
    assert "Aylık kırılım" in titles
    assert "İlk 5" in titles


def test_missing_sections_notice_a_skipped_heading():
    report = "## Bölgeler\n\nMarmara\n\n## Sapmalar\n\nyok\n"
    assert missing_sections(report, ["Bölge", "Sapma"]) == []
    assert missing_sections(report, ["Aylık kırılım", "İlk 5"]) == ["Aylık kırılım", "İlk 5"]


def test_builder_stays_manual_when_the_description_has_no_time():
    spec = FakeLLM()._build(
        {
            "description": "Satışları bölge bazında özetle",
            "datasources": [{"name": "postgres-sales", "allow_tables": ["sales"]}],
        }
    )
    schedule = spec["spec"]["schedule"]
    assert schedule["mode"] == "manual"
    assert schedule.get("cron") in (None, "")
    assert "Bölge" in spec["spec"]["output"]["sections"]


def test_builder_keeps_a_morning_cron():
    spec = FakeLLM()._build(
        {
            "description": "Her sabah satış özeti hazırla",
            "datasources": [{"name": "postgres-sales", "allow_tables": ["sales"]}],
        }
    )
    assert spec["spec"]["schedule"]["cron"] == "0 7 * * 1-5"


def test_invented_cron_is_dropped_unless_the_description_asked():
    invented = {"spec": {"schedule": {"mode": "cron", "cron": "15 8 * * *", "timeZone": "Europe/Istanbul"}}}
    stripped = apply_default_schedule(invented, "Satışları bölge bazında özetle")
    assert stripped["spec"]["schedule"]["mode"] == "manual"
    assert stripped["spec"]["schedule"]["cron"] is None
    daily = apply_default_schedule(
        {"spec": {"schedule": {"mode": "cron", "cron": "15 8 * * *"}}},
        "Günlük satış raporu, saat yok",
    )
    assert daily["spec"]["schedule"]["mode"] == "manual"
    assert daily["spec"]["schedule"]["cron"] is None
    kept = apply_default_schedule(
        {"spec": {"schedule": {"mode": "cron", "cron": "0 7 * * 1-5"}}},
        "Her sabah satış özeti",
    )
    assert kept["spec"]["schedule"]["cron"] == "0 7 * * 1-5"


def test_allow_tables_match_without_case(datasource, db):
    spec = copy.deepcopy(EXAMPLE_SPEC)
    spec["metadata"]["name"] = "oracle-buyuk-harf"
    spec["spec"]["datasources"][0]["allowTables"] = ["SALES"]
    agent = create_agent(db, spec, publish=True, actor="test")
    assert agent.name == "oracle-buyuk-harf"
