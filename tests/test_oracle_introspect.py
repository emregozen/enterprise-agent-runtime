from datasources.base import SchemaCatalog
from datasources.oracle import OracleSource


class _Cursor:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchall(self):
        name = self.calls[-1][1]["name"]
        if name == "SALES":
            return [("REGION", "VARCHAR2", "Y"), ("AMOUNT", "NUMBER", "N")]
        return []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_introspect_reads_all_tables_and_synonyms_for_a_select_only_user():
    source = OracleSource.__new__(OracleSource)
    source.allow_tables = ["sales"]
    source.dialect = "oracle"
    cursor = _Cursor()
    source.conn = type("Conn", (), {"cursor": lambda self: cursor})()
    catalog = source.introspect(["SALES", "SALES_OWNER.OTHER"])
    assert isinstance(catalog, SchemaCatalog)
    sql = cursor.calls[0][0].lower()
    assert "all_tables" in sql
    assert "all_views" in sql
    assert "all_synonyms" in sql
    assert "all_tab_columns" in sql
    assert "user_tab_columns" not in sql
    assert cursor.calls[0][1] == {"owner": None, "name": "SALES"}
    assert cursor.calls[1][1] == {"owner": "SALES_OWNER", "name": "OTHER"}
    assert catalog.tables[0].name == "SALES"
    assert [column.name for column in catalog.tables[0].columns] == ["REGION", "AMOUNT"]
    assert catalog.tables[0].columns[0].nullable is True
    assert len(catalog.tables) == 1
