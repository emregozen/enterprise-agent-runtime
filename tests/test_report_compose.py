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


def test_compose_drops_the_raw_dump_the_duplicate_and_the_pointer():
    raw = "\n".join(f"| r{i} | {i} |" for i in range(91))
    template = (
        "## Ham\n"
        "| id | n |\n| --- | --- |\n"
        f"{raw}\n\n"
        "## Bölgeler\n{{region_table}}\n\n"
        "## Bölge kopyası\n"
        "| Bölge | Tutar | Karşılaştırma | Sapma | Adet |\n"
        "| --- | ---: | ---: | ---: | ---: |\n"
        "| Akdeniz | 2 | 2 | 0,00% | 1 |\n"
        "| İç Anadolu | 1 | 1 | 0,00% | 1 |\n\n"
        "## Aylık kırılım\n"
        "Aylık kırılım yukarıdaki tabloda.\n\n"
        "## Sapmalar\n{{anomaly_section}}\n"
    )
    report = compose_report(
        template,
        {
            "grand_total": 3,
            "sale_count": 2,
            "regions": [
                {
                    "region": "İç Anadolu",
                    "yesterday_amount": 1,
                    "baseline_daily": 1,
                    "deviation_pct": 0,
                    "sale_count": 1,
                },
                {
                    "region": "Akdeniz",
                    "yesterday_amount": 2,
                    "baseline_daily": 2,
                    "deviation_pct": 0,
                    "sale_count": 1,
                },
            ],
            "anomalies": [],
            "rows": [{"region": f"r{i}", "n": i} for i in range(91)],
        },
        [{"name": "grand_total", "ok": True, "sql_value": 3, "code_value": 3}],
    )
    assert "r0" not in report
    assert "yukarıdaki" not in report
    assert "Aylık kırılım" not in report
    assert report.count("Akdeniz") == 1
    assert "İç Anadolu" in report
    assert "Eşiği aşan bölge yok." in report
    assert "geçti" in report


def test_pointer_section_does_not_count_as_covered():
    from harness.sections import missing_sections

    report = "## Bölgeler\n\nMarmara 10\n\n## Aylık kırılım\n\nAylık kırılım yukarıdaki tabloda.\n"
    assert missing_sections(report, ["Bölge"]) == []
    assert missing_sections(report, ["Aylık kırılım"]) == ["Aylık kırılım"]


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
