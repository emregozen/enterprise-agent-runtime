from shared.report import compose_report, turkish_sort_key


REGIONS = ["Marmara", "İç Anadolu", "Ege", "Akdeniz", "Karadeniz", "Doğu Anadolu", "Güneydoğu Anadolu"]


def test_turkish_order_puts_ic_anadolu_before_karadeniz():
    ordered = sorted(REGIONS, key=turkish_sort_key)
    assert ordered == [
        "Akdeniz",
        "Doğu Anadolu",
        "Ege",
        "Güneydoğu Anadolu",
        "İç Anadolu",
        "Karadeniz",
        "Marmara",
    ]


def test_compose_writes_computed_stats_and_the_real_verification():
    template = "## Özet\n{{grand_total}}\n\n### Doğrulama\nSonuçlar psql ile çapraz kontrol edilmeli.\n"
    output = {
        "grand_total": 10160,
        "sale_count": 3,
        "regions": [
            {
                "region": "İç Anadolu",
                "yesterday_amount": 1,
                "baseline_daily": 1,
                "deviation_pct": 0,
                "sale_count": 1,
                "median": 12.5,
                "p95": 40,
            },
            {
                "region": "Akdeniz",
                "yesterday_amount": 2,
                "baseline_daily": 2,
                "deviation_pct": 0,
                "sale_count": 1,
                "median": 8,
                "p95": 9,
            },
        ],
    }
    checks = [{"name": "grand_total", "ok": True, "sql_value": 10160, "code_value": 10160}]
    report = compose_report(template, output, checks)
    assert "edilmeli" not in report
    assert "Çapraz kontrol **geçti**." in report
    assert "10.160" in report
    assert "median" in report
    assert "p95" in report
    assert "12,50" in report
    assert report.index("Akdeniz") < report.index("İç Anadolu")


def test_failed_verification_states_the_numbers():
    report = compose_report(
        "## Özet\n",
        {"grand_total": 1, "sale_count": 1, "regions": []},
        [{"name": "grand_total", "ok": False, "sql_value": 10, "code_value": 1}],
    )
    assert "başarısız" in report
    assert "SQL 10" in report
    assert "kod 1" in report
    assert "**kaldı**" in report
