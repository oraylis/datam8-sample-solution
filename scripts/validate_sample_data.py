"""Manifest-driven data, key, history, relationship and financial checks."""
from __future__ import annotations

import re


def identifier(value):
    return "`" + value.replace("`", "``") + "`"


def table(catalog, key):
    return ".".join(identifier(part) for part in [catalog, *key.split(".")])


def semantic_dataset(datasets, zone, name):
    """Resolve a model entity from optional manifest metadata or its dataset key."""
    normalized = name.replace("_", "").casefold()
    matches = [
        item
        for item in datasets
        if item["zone"] == zone
        and any(
            candidate and candidate.replace("_", "").casefold() == normalized
            for candidate in (
                item.get("entity_name"),
                item.get("name"),
                item["key"].rsplit("_", 1)[-1],
            )
        )
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one semantic object: {zone}/{name}")
    return matches[0]


def normalize_type(value):
    value = re.sub(r"\s+", "", value).lower()
    return {"integer": "int", "long": "bigint", "short": "smallint", "bit": "boolean", "datetime": "timestamp"}.get(value, value)


def validate_append_fixture(query):
    """Read-only warehouse fixture for a monotonic cursor, with repeated event IDs."""
    rows = query("""WITH initial AS (
        SELECT * FROM VALUES (1,10),(2,20) AS t(MovementID,ModifiedAt)
    ), unchanged_delta AS (
        SELECT * FROM initial WHERE ModifiedAt > (SELECT MAX(ModifiedAt) FROM initial)
    ), inserted_delta AS (
        SELECT * FROM VALUES (3,30) AS t(MovementID,ModifiedAt)
        WHERE ModifiedAt > (SELECT MAX(ModifiedAt) FROM initial)
    ), after_insert AS (
        SELECT * FROM initial UNION ALL SELECT * FROM inserted_delta
    ), changed_delta AS (
        SELECT * FROM VALUES (1,40) AS t(MovementID,ModifiedAt)
        WHERE ModifiedAt > (SELECT MAX(ModifiedAt) FROM after_insert)
    ), accumulated_stage AS (
        SELECT * FROM after_insert UNION ALL SELECT * FROM changed_delta
    ), overwrite_core AS (SELECT * FROM accumulated_stage)
    SELECT (SELECT COUNT(*) FROM initial), (SELECT COUNT(*) FROM unchanged_delta),
        (SELECT COUNT(*) FROM inserted_delta), (SELECT COUNT(*) FROM changed_delta),
        COUNT(*), SUM(CASE WHEN MovementID=1 THEN 1 ELSE 0 END) FROM overwrite_core""")
    if not rows or [int(value) for value in rows[0]] != [2, 0, 1, 1, 4, 2]:
        raise ValueError("Delta/append fixture failed; repeated MovementID must be allowed only with a later cursor")
    return "passed"


def validate_data(query, catalog, manifest, *, date_start="2000-01-01", date_end="2030-12-31"):
    datasets = manifest["datasets"]
    known = {item["key"]: item for item in datasets}
    objects = {schema + "." + name: kind for schema, name, kind in query(f"SELECT table_schema,table_name,table_type FROM {identifier(catalog)}.information_schema.tables WHERE table_schema IN ('raw','stage','core','curated')")}
    columns = {}
    for schema, name, column, datatype in query(f"SELECT table_schema,table_name,column_name,full_data_type FROM {identifier(catalog)}.information_schema.columns WHERE table_schema IN ('raw','stage','core','curated')"):
        columns.setdefault(schema + "." + name, {})[column.lower()] = datatype
    checks = []

    def no_rows(label, sql):
        checks.append("SELECT '" + label.replace("'", "''") + "' AS check_name,COUNT(*) AS violations FROM (" + sql + ") violations")

    for item in datasets:
        key = item["key"]
        if key not in objects:
            raise ValueError("Missing modeled object: " + key)
        expected_kind = {"delta_table": "MANAGED", "materialized_view": "MATERIALIZED_VIEW", "streaming_table": "STREAMING_TABLE"}[item["kind"]]
        if objects[key] != expected_kind:
            raise ValueError(f"{key}: expected {expected_kind}, got {objects[key]}")
        for column in item["columns"]:
            actual = columns[key].get(column["name"].lower())
            if actual is None or normalize_type(actual) != normalize_type(column["type"]):
                raise ValueError(f"{key}.{column['name']}: schema mismatch ({actual}, expected {column['type']})")
        relation = table(catalog, key)
        for column in item["columns"]:
            if not column.get("nullable", True):
                no_rows(key + ": null non-nullable column " + column["name"], f"SELECT 1 FROM {relation} WHERE {identifier(column['name'])} IS NULL")
        active = " WHERE __IsCurrent" if item["scd2"] else ""
        if item["keys"]:
            keys = ",".join(identifier(key) for key in item["keys"])
            no_rows(key + ": duplicate keys", f"SELECT {keys} FROM {relation}{active} GROUP BY {keys} HAVING COUNT(*)>1")
            no_rows(key + ": null key", f"SELECT 1 FROM {relation}{active + ' AND ' if active else ' WHERE '}" + " OR ".join(identifier(key) + " IS NULL" for key in item["keys"]))
        for surrogate in item["surrogates"]:
            column = identifier(surrogate)
            no_rows(key + ": null surrogate", f"SELECT 1 FROM {relation} WHERE {column} IS NULL")
            no_rows(key + ": surrogate collision", f"SELECT {column} FROM {relation} GROUP BY {column} HAVING COUNT(*)>1")
        if item["scd2"]:
            keys = ",".join(identifier(value) for value in item["keys"])
            start, end = ("__START_AT", "__END_AT") if item["kind"] != "delta_table" else ("__ValidFrom", "__ValidTo")
            no_rows(key + ": invalid history interval", f"SELECT 1 FROM {relation} WHERE {end} IS NOT NULL AND {start} >= {end}")
            no_rows(key + ": overlapping history", f"SELECT 1 FROM (SELECT {start} AS version_start,LAG({end}) OVER(PARTITION BY {keys} ORDER BY {start} NULLS FIRST) AS previous_end FROM {relation}) WHERE previous_end>version_start")
        local_columns = {column["name"] for column in item["columns"]}
        for relationship in item.get("relationships", []):
            target = relationship["dataset"]
            pairs = [pair for pair in relationship["attributes"] if pair["source"] in local_columns]
            # Intermediate lookup business keys may not be persisted in a fact.
            if not pairs or target not in known:
                continue
            condition = " AND ".join("f." + identifier(pair["source"]) + "=d." + identifier(pair["target"]) for pair in pairs)
            present = " AND ".join("f." + identifier(pair["source"]) + " IS NOT NULL" for pair in pairs)
            no_rows(key + ": relationship " + target, f"SELECT 1 FROM {relation} f LEFT ANTI JOIN {table(catalog, target)} d ON {condition} WHERE {present}")
    if checks:
        violations = [(name, count) for name, count in query(" UNION ALL ".join(checks)) if int(count)]
        if violations:
            raise ValueError("Data integrity violations: " + str(violations))
    count_sql = " UNION ALL ".join(f"SELECT '{item['key']}',COUNT(*) FROM {table(catalog,item['key'])}" for item in datasets)
    counts = {name: int(count) for name, count in query(count_sql)}
    empty = [name for name, count in counts.items() if not count]
    if empty:
        raise ValueError("Empty modeled objects: " + ", ".join(empty))

    def equal(label, left, right):
        row = query(f"SELECT ({left}) <=> ({right})")[0][0]
        if str(row).lower() != "true":
            raise ValueError("Business reconciliation failed: " + label)

    def t(zone, name):
        return table(catalog, semantic_dataset(datasets, zone, name)["key"])

    equal("sales header totals", f"SELECT SUM(TotalCosts) FROM {t('curated','FactSalesOrder')}", f"SELECT CAST(SUM(TotalDue) AS DECIMAL(38,4)) FROM {t('stage','SalesOrderHeader')}")
    equal("estimated purchase value", f"SELECT SUM(EstimatedPurchaseValue) FROM {t('curated','FactPurchaseOrder')}", f"SELECT SUM(CAST(p.Quantity*s.UnitCost AS DECIMAL(18,4))) FROM {t('core','PurchaseOrder')} p JOIN {t('core','ProductSupplier')} s ON p.ProductID=s.ProductID AND p.SupplierID=s.SupplierID")
    equal("available inventory", f"SELECT SUM(AvailableQuantity) FROM {t('curated','FactInventorySnapshot')}", f"SELECT SUM(OnHand-Reserved) FROM {t('core','Inventory')}")
    equal("web sessions", f"SELECT COUNT(*) FROM {t('curated','FactWebSession')}", f"SELECT COUNT(*) FROM {t('core','WebSession')}")
    equal("cart quantities", f"SELECT SUM(CartQuantity) FROM {t('curated','FactWebSession')}", f"SELECT SUM(Quantity) FROM {t('core','CartItem')}")
    equal("returns", f"SELECT COUNT(*) FROM {t('curated','FactReturn')}", f"SELECT COUNT(*) FROM {t('core','ReturnRequest')}")
    equal(
        "tracking event coverage for shipments",
        f"SELECT SUM(EventCount) FROM {t('curated','FactShipment')}",
        f"SELECT COUNT(*) FROM {t('core','TrackingEvent')} e JOIN {t('core','Shipment')} s ON e.SalesOrderID=s.SalesOrderID",
    )
    equal("unknown date member", f"SELECT COUNT(*) FROM {t('curated','DimDate')} WHERE DateID=0 AND CalendarYear='Unknown' AND MonthName='Unknown'", "SELECT 1")
    equal("date range", f"SELECT COUNT(*) FROM {t('curated','DimDate')}", f"SELECT datediff(DATE '{date_end}',DATE '{date_start}')+2")
    return {"counts": counts, "integrity_checks": len(checks), "business_checks": 9}


def business_fingerprints(query, catalog, manifest, canonical=None):
    """Compare multisets by normalized business columns, independent of identities."""
    canonical = canonical or {item["key"]: item for item in manifest["datasets"]}
    statements = []
    for item in manifest["datasets"]:
        if item["zone"] == "raw":
            continue
        key = item["key"]
        columns = []
        for column in sorted(canonical[key]["columns"], key=lambda field: field["name"].lower()):
            name = column["name"]
            if name in item["surrogates"] or name.endswith("SID") or name == "SnapshotAsOfUTC":
                continue
            value = f"CAST(f.{identifier(name)} AS {column['type']})"
            columns.extend(["'" + name.lower() + "'", value])
        source = table(catalog, key) + " f"
        if item["zone"] == "curated" and item is semantic_dataset(manifest["datasets"], "curated", "FactSalesOrder"):
            dimension = semantic_dataset(manifest["datasets"], "curated", "DimCustomer")["key"]
            source += " JOIN " + table(catalog, dimension) + " d ON f.CustomerSID=d.CustomerSID"
            columns += ["'customerid'", "d.CustomerID"]
        statements.append(f"SELECT '{key}' AS dataset,COUNT(*) AS rows,CAST(SUM(CAST(xxhash64(to_json(named_struct({','.join(columns)}))) AS DECIMAL(38,0))) AS STRING) AS digest FROM {source}")
    return {name: {"rows": int(rows), "digest": digest} for name, rows, digest in query(" UNION ALL ".join(statements))}
