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


def test_raw_cte_read_only_by_aggregates_is_allowed():
    sql = """
    WITH ref AS (SELECT MAX(sale_date) AS d FROM sales),
    w AS (SELECT s.region, s.amount, r.d FROM sales s CROSS JOIN ref r WHERE s.sale_date >= r.d - 7),
    a AS (SELECT region, SUM(amount) AS t FROM w GROUP BY region),
    b AS (SELECT COUNT(*) AS c FROM w)
    SELECT * FROM a UNION ALL SELECT 'x', c FROM b
    """
    result = guard_sql(sql, dialect="postgres", allow_tables=["sales"], max_limit=1000)
    assert result.ok, result.reason


def test_raw_cte_returned_directly_is_rejected():
    result = bad("WITH w AS (SELECT region, amount FROM sales) SELECT * FROM w")
    assert "CTE w" in (result.reason or "")


def test_raw_cte_with_one_raw_reader_is_rejected():
    sql = """
    WITH w AS (SELECT region, amount FROM sales),
    a AS (SELECT region, SUM(amount) AS t FROM w GROUP BY region)
    SELECT * FROM a
    UNION ALL
    SELECT region, amount FROM w
    """
    result = bad(sql)
    assert "CTE w" in (result.reason or "")


def test_raw_derived_table_under_aggregate_is_allowed():
    ok("SELECT region, SUM(amount) AS t FROM (SELECT region, amount FROM sales) s GROUP BY region")


def test_oracle_fetch_first_counts_as_limit():
    ok("SELECT region, amount FROM sales FETCH FIRST 5 ROWS ONLY", dialect="oracle")
    ok("SELECT region, amount FROM sales OFFSET 0 ROWS FETCH NEXT 10 ROWS ONLY", dialect="oracle")
    bad("SELECT region, amount FROM sales FETCH FIRST 5000 ROWS ONLY", dialect="oracle")
    bad("SELECT region, amount FROM sales FETCH FIRST 5 PERCENT ROWS ONLY", dialect="oracle")
    bad("SELECT region, amount FROM sales FETCH FIRST 5 ROWS WITH TIES", dialect="oracle")
    bad("SELECT region, amount FROM sales", dialect="oracle")


def test_oracle_rownum_counts_as_limit():
    ok("SELECT region, amount FROM sales WHERE ROWNUM <= 10", dialect="oracle")
    ok(
        "SELECT * FROM (SELECT region, amount FROM sales ORDER BY amount DESC) t WHERE ROWNUM <= 5",
        dialect="oracle",
    )
    ok("SELECT region, amount FROM sales WHERE region = 'Ege' AND ROWNUM < 4", dialect="oracle")
    ok("SELECT region, amount FROM sales WHERE 10 >= ROWNUM", dialect="oracle")
    bad("SELECT region, amount FROM sales WHERE ROWNUM <= 5000", dialect="oracle")
    bad("SELECT region, amount FROM sales WHERE ROWNUM <= 10 OR region = 'Ege'", dialect="oracle")


def test_scalar_max_subquery_does_not_mark_raw_export_as_aggregate():
    result = ok("SELECT region, amount, (SELECT MAX(sale_date) FROM sales) AS d FROM sales LIMIT 50")
    assert result.aggregate is False
    assert ok("SELECT region, SUM(amount) FROM sales GROUP BY region").aggregate is True
