from sqlguard import guard_sql

ALLOW = ["sales", "regions"]


def ok(sql: str, dialect: str = "postgres"):
    result = guard_sql(sql, dialect=dialect, allow_tables=ALLOW, max_limit=1000)
    assert result.ok, result.reason
    return result


def bad(sql: str, dialect: str = "postgres"):
    result = guard_sql(sql, dialect=dialect, allow_tables=ALLOW, max_limit=1000)
    assert not result.ok, sql
    return result


def test_aggregate_and_limit_are_accepted():
    result = ok("SELECT region, SUM(amount) AS total_amount FROM sales GROUP BY region")
    assert result.aggregate
    ok("SELECT region, amount FROM sales LIMIT 10")
    ok(
        """
        WITH recent AS (SELECT region, SUM(amount) AS total_amount FROM sales GROUP BY region)
        SELECT region, total_amount FROM recent
        """
    )


def test_writes_and_unbounded_selects_are_rejected():
    bad("DELETE FROM sales")
    bad("UPDATE sales SET amount = 0")
    bad("INSERT INTO sales (sale_id) VALUES (1)")
    bad("DROP TABLE sales")
    bad("SELECT 1; DROP TABLE sales")
    bad("SELECT * FROM sales")
    bad("SELECT * FROM secrets LIMIT 5")
    bad("SELECT pg_read_file('/etc/passwd') FROM sales LIMIT 1")
    bad("SELECT * FROM sales FOR UPDATE LIMIT 1")
    bad("SELECT * INTO copy_sales FROM sales")


def test_generated_daily_sql_passes():
    from shared.fake_llm import _daily_sql

    sql, checks = _daily_sql("postgres", "sales", "sale_date", "amount", "region")
    ok(sql)
    for check in checks:
        ok(check["sql"])
    oracle_sql, oracle_checks = _daily_sql("oracle", "sales", "sale_date", "amount", "region")
    ok(oracle_sql, dialect="oracle")
    for check in oracle_checks:
        ok(check["sql"], dialect="oracle")
