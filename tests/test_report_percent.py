from shared.report import format_percent, render_report


def test_percent_uses_the_same_shape_for_zero_and_large_values():
    assert format_percent(0) == "0,00%"
    assert format_percent(300) == "300,00%"
    assert format_percent(12.5) == "12,50%"
    report = render_report(
        "{{region_table}}\n{{anomaly_section}}",
        {
            "regions": [
                {"region": "Marmara", "yesterday_amount": 10, "baseline_daily": 10, "deviation_pct": 0, "sale_count": 1},
                {"region": "Doğu", "yesterday_amount": 40, "baseline_daily": 10, "deviation_pct": 300, "sale_count": 2},
            ],
            "anomalies": [{"region": "Doğu", "deviation_pct": 300, "direction": "yuksek"}],
        },
    )
    assert "0,00%" in report
    assert "300,00%" in report
    assert "300%" not in report.replace("300,00%", "")
