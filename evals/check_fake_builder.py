"""Offline check: the fake builder emits an AgentSpec without a database or cluster."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml

from harness.loop import builder_messages
from shared.fake_llm import FakeLLM
from shared.llm import parse_json_response
from shared.spec import AgentSpec
CATALOG = {
    "name": "postgres-sales",
    "dialect": "postgres",
    "allow_tables": ["sales"],
    "sensitivity": "internal",
    "catalog": {
        "tables": [
            {
                "name": "sales",
                "columns": [
                    {"name": "sale_date", "type": "date"},
                    {"name": "region", "type": "text"},
                    {"name": "amount", "type": "numeric"},
                ],
            }
        ]
    },
}


def main() -> None:
    cases = yaml.safe_load((ROOT / "evals" / "sales_questions.yaml").read_text())["questions"]
    llm = FakeLLM()
    for case in cases:
        raw = parse_json_response(
            llm.complete(
                builder_messages(
                    {
                        "description": case["description"],
                        "owner": "finans-ekibi",
                        "datasources": [CATALOG],
                    }
                )
            )
        )
        spec = AgentSpec.model_validate(raw)
        tools = spec.spec.tools
        mode = spec.spec.schedule.mode if spec.spec.schedule else "manual"
        expect_tool = case["expect_tool"]
        if expect_tool and expect_tool not in tools:
            raise SystemExit(f"{case['id']}: {expect_tool} yok")
        if mode != case["expect_schedule"]:
            raise SystemExit(f"{case['id']}: zamanlama {mode}, beklenen {case['expect_schedule']}")
        print(f"ok {case['id']} {spec.metadata.name} {mode}")


if __name__ == "__main__":
    main()
