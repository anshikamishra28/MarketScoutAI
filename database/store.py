"""SQLite persistence using only the Python standard library."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import uuid

from models.price_comparison import (
    ComparisonStatus,
    PriceComparisonRequest,
    PriceOffer,
    RetailerResult,
    RetailerStatus,
)
from models.comparison import (
    AttributeDefinition,
    ComparisonRequest as GenericComparisonRequest,
    ComparisonResult as GenericComparisonResult,
    ComparisonStatus as GenericComparisonStatus,
    EntityReference,
    Observation,
    SourceCheck,
    SourceReference,
)

DB_PATH = os.getenv("MARKETSCOUT_DB", os.path.join(os.path.dirname(__file__), "market_scout.sqlite3"))


@contextmanager
def connect():
    db = sqlite3.connect(DB_PATH, timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        with db:
            yield db
    finally:
        db.close()


def init_db():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS research_runs (id TEXT PRIMARY KEY, question TEXT NOT NULL, status TEXT NOT NULL, iterations INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, plan TEXT NOT NULL DEFAULT '{}', activity TEXT NOT NULL DEFAULT '[]', missing TEXT NOT NULL DEFAULT '[]', coverage TEXT NOT NULL DEFAULT '{}', conflicts TEXT NOT NULL DEFAULT '[]', error TEXT);
        CREATE TABLE IF NOT EXISTS sources (id TEXT PRIMARY KEY, research_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE, url TEXT NOT NULL, fetch_url TEXT, title TEXT, publisher TEXT, published_at TEXT, source_type TEXT, content_scope TEXT, search_query TEXT, snippet TEXT, content TEXT, fetch_error TEXT, evaluation TEXT, UNIQUE(research_id, url));
        CREATE TABLE IF NOT EXISTS evidence (id TEXT PRIMARY KEY, research_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE, source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE, claim TEXT, evidence_text TEXT, source_url TEXT, source_title TEXT, publisher TEXT, published_at TEXT, source_type TEXT, content_scope TEXT, relevance REAL, confidence REAL, extracted_at TEXT, source_quality_score REAL NOT NULL DEFAULT 0, recency_score REAL NOT NULL DEFAULT 0, geographic_relevance REAL NOT NULL DEFAULT 0, direct_support INTEGER NOT NULL DEFAULT 0, quality_score REAL NOT NULL DEFAULT 0, category_relevance REAL NOT NULL DEFAULT 0, segment_relevance REAL NOT NULL DEFAULT 0, evidence_scope TEXT NOT NULL DEFAULT 'INDIA_MARKET_CONTEXT');
        CREATE TABLE IF NOT EXISTS reports (research_id TEXT PRIMARY KEY REFERENCES research_runs(id) ON DELETE CASCADE, content TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS price_comparisons (
            comparison_id TEXT PRIMARY KEY,
            input_data TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('queued','running','completed','failed')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            error TEXT
        );
        CREATE TABLE IF NOT EXISTS price_retailer_checks (
            id TEXT PRIMARY KEY,
            comparison_id TEXT NOT NULL REFERENCES price_comparisons(comparison_id) ON DELETE CASCADE,
            retailer TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('checked','unavailable','blocked','failed')),
            message TEXT,
            checked_at TEXT NOT NULL,
            diagnostics TEXT NOT NULL DEFAULT '{}',
            UNIQUE(comparison_id, retailer)
        );
        CREATE TABLE IF NOT EXISTS price_observations (
            id TEXT PRIMARY KEY,
            comparison_id TEXT NOT NULL REFERENCES price_comparisons(comparison_id) ON DELETE CASCADE,
            product_brand TEXT NOT NULL,
            product_model TEXT NOT NULL DEFAULT '',
            product_model_number TEXT NOT NULL DEFAULT '',
            product_ram TEXT NOT NULL DEFAULT '',
            product_storage TEXT NOT NULL DEFAULT '',
            product_variant TEXT NOT NULL DEFAULT '',
            retailer TEXT NOT NULL,
            price TEXT NOT NULL,
            currency TEXT NOT NULL,
            seller TEXT,
            discount TEXT,
            observed_at TEXT NOT NULL,
            source_url TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_price_retailer_checks_comparison ON price_retailer_checks(comparison_id);
        CREATE INDEX IF NOT EXISTS idx_price_observations_comparison ON price_observations(comparison_id);
        CREATE TABLE IF NOT EXISTS comparison_runs (
            comparison_id TEXT PRIMARY KEY,
            user_request TEXT NOT NULL,
            request_data TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('queued','running','completed','failed')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            error TEXT,
            analysis TEXT,
            unresolved TEXT NOT NULL DEFAULT '[]',
            errors TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS comparison_entities (
            entity_id TEXT PRIMARY KEY,
            comparison_id TEXT NOT NULL REFERENCES comparison_runs(comparison_id) ON DELETE CASCADE,
            entity_key TEXT NOT NULL,
            display_name TEXT NOT NULL,
            entity_type TEXT,
            identifiers TEXT NOT NULL DEFAULT '{}',
            aliases TEXT NOT NULL DEFAULT '[]',
            UNIQUE(comparison_id, entity_key),
            UNIQUE(comparison_id, entity_id)
        );
        CREATE TABLE IF NOT EXISTS comparison_attributes (
            attribute_id TEXT PRIMARY KEY,
            comparison_id TEXT NOT NULL REFERENCES comparison_runs(comparison_id) ON DELETE CASCADE,
            attribute_key TEXT NOT NULL,
            label TEXT NOT NULL,
            value_type TEXT NOT NULL CHECK(value_type IN ('scalar','range','categorical','boolean','structured')),
            unit TEXT,
            currency TEXT,
            comparison_rule TEXT,
            UNIQUE(comparison_id, attribute_key),
            UNIQUE(comparison_id, attribute_id)
        );
        CREATE TABLE IF NOT EXISTS comparison_source_checks (
            source_check_id TEXT PRIMARY KEY,
            comparison_id TEXT NOT NULL REFERENCES comparison_runs(comparison_id) ON DELETE CASCADE,
            source_key TEXT NOT NULL,
            source_name TEXT NOT NULL,
            source_type TEXT,
            source_url TEXT,
            status TEXT NOT NULL CHECK(status IN ('pending','checked','unavailable','blocked','failed','unsupported')),
            checked_at TEXT,
            diagnostics TEXT,
            error TEXT,
            UNIQUE(comparison_id, source_key),
            UNIQUE(comparison_id, source_check_id)
        );
        CREATE TABLE IF NOT EXISTS comparison_observations (
            observation_id TEXT PRIMARY KEY,
            comparison_id TEXT NOT NULL REFERENCES comparison_runs(comparison_id) ON DELETE CASCADE,
            entity_id TEXT NOT NULL,
            attribute_id TEXT NOT NULL,
            source_check_id TEXT NOT NULL,
            raw_value TEXT NOT NULL,
            normalized_value TEXT,
            value_type TEXT NOT NULL CHECK(value_type IN ('scalar','range','categorical','boolean','structured')),
            unit TEXT,
            currency TEXT,
            observed_at TEXT NOT NULL,
            source_url TEXT,
            context TEXT,
            FOREIGN KEY(comparison_id, entity_id) REFERENCES comparison_entities(comparison_id, entity_id) ON DELETE CASCADE,
            FOREIGN KEY(comparison_id, attribute_id) REFERENCES comparison_attributes(comparison_id, attribute_id) ON DELETE CASCADE,
            FOREIGN KEY(comparison_id, source_check_id) REFERENCES comparison_source_checks(comparison_id, source_check_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_comparison_entities_run ON comparison_entities(comparison_id);
        CREATE INDEX IF NOT EXISTS idx_comparison_attributes_run ON comparison_attributes(comparison_id);
        CREATE INDEX IF NOT EXISTS idx_comparison_source_checks_run ON comparison_source_checks(comparison_id);
        CREATE INDEX IF NOT EXISTS idx_comparison_observations_run ON comparison_observations(comparison_id);
        """)
        columns = {row[1] for row in db.execute("PRAGMA table_info(research_runs)")}
        if "coverage" not in columns:
            db.execute("ALTER TABLE research_runs ADD COLUMN coverage TEXT NOT NULL DEFAULT '{}'")
        evidence_columns = {row[1] for row in db.execute("PRAGMA table_info(evidence)")}
        add_evidence_scope = "evidence_scope" not in evidence_columns
        additions = {"source_quality_score": "REAL NOT NULL DEFAULT 0", "recency_score": "REAL NOT NULL DEFAULT 0", "geographic_relevance": "REAL NOT NULL DEFAULT 0", "direct_support": "INTEGER NOT NULL DEFAULT 0", "quality_score": "REAL NOT NULL DEFAULT 0", "category_relevance": "REAL NOT NULL DEFAULT 0", "segment_relevance": "REAL NOT NULL DEFAULT 0", "evidence_scope": "TEXT NOT NULL DEFAULT 'INDIA_MARKET_CONTEXT'"}
        for name, definition in additions.items():
            if name not in evidence_columns:
                db.execute(f"ALTER TABLE evidence ADD COLUMN {name} {definition}")
        if add_evidence_scope:
            # Backfill old evidence from its original question and verbatim claim;
            # the schema default alone would incorrectly label premium/global claims.
            from models.evidence import classify_evidence_scope, segment_relevance
            rows = db.execute("""SELECT e.id,e.evidence_text,e.source_title,e.category_relevance,e.geographic_relevance,e.segment_relevance,e.quality_score,r.question
                FROM evidence e JOIN research_runs r ON r.id=e.research_id""").fetchall()
            for row in rows:
                text = row["evidence_text"] or ""
                question = row["question"] or ""
                new_segment = segment_relevance(text, row["source_title"] or "", question)
                scope = classify_evidence_scope(text, question, row["category_relevance"] or 0,
                                                row["geographic_relevance"] or 0, row["source_title"] or "")
                new_quality = round((row["quality_score"] or 0) + 0.08 * (new_segment - (row["segment_relevance"] or 0)), 3)
                db.execute("UPDATE evidence SET segment_relevance=?, evidence_scope=?, quality_score=? WHERE id=?",
                           (new_segment, scope, new_quality, row["id"]))
        retailer_check_columns = {row[1] for row in db.execute("PRAGMA table_info(price_retailer_checks)")}
        if "diagnostics" not in retailer_check_columns:
            db.execute("ALTER TABLE price_retailer_checks ADD COLUMN diagnostics TEXT NOT NULL DEFAULT '{}'" )


def create_run(run_id, question):
    now = datetime.now(timezone.utc).isoformat()
    with connect() as db:
        db.execute("INSERT INTO research_runs(id,question,status,created_at,updated_at) VALUES(?,?, 'queued',?,?)", (run_id, question, now, now))


def update_run(run_id, **fields):
    fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    allowed = {"status", "iterations", "plan", "activity", "missing", "coverage", "conflicts", "error", "updated_at"}
    values = {k: json.dumps(v, ensure_ascii=False) if k in {"plan", "activity", "missing", "coverage", "conflicts"} else v for k, v in fields.items() if k in allowed}
    if not values: return
    with connect() as db:
        db.execute("UPDATE research_runs SET " + ",".join(f"{k}=?" for k in values) + " WHERE id=?", (*values.values(), run_id))


def add_source(run_id, source):
    import uuid
    sid = source.get("id") or str(uuid.uuid4())
    source["id"] = sid
    with connect() as db:
        db.execute("""INSERT OR IGNORE INTO sources(id,research_id,url,fetch_url,title,publisher,published_at,source_type,content_scope,search_query,snippet,content,fetch_error,evaluation)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (sid, run_id, source.get("url", ""), source.get("fetch_url", ""), source.get("title", ""), source.get("publisher", ""), source.get("published_at", ""), source.get("source_type", "unknown"), source.get("content_scope", "unknown"), source.get("search_query", ""), source.get("snippet", ""), source.get("content", ""), source.get("fetch_error", ""), json.dumps(source.get("evaluation", {}))))
    return sid


def add_evidence(run_id, item):
    with connect() as db:
        db.execute("""INSERT OR IGNORE INTO evidence(id,research_id,source_id,claim,evidence_text,source_url,source_title,publisher,published_at,source_type,content_scope,relevance,confidence,extracted_at,source_quality_score,recency_score,geographic_relevance,direct_support,quality_score,category_relevance,segment_relevance,evidence_scope)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (item["id"], run_id, item["source_id"], item["claim"], item["evidence_text"], item["source_url"], item["source_title"], item["publisher"], item.get("published_at", ""), item["source_type"], item["content_scope"], item["relevance"], item["confidence"], item["extracted_at"], item.get("source_quality_score", 0), item.get("recency_score", 0), item.get("geographic_relevance", 0), int(item.get("direct_support", False)), item.get("quality_score", 0), item.get("category_relevance", 0), item.get("segment_relevance", 0), item.get("evidence_scope", "INDIA_MARKET_CONTEXT")))


def get_run(run_id):
    with connect() as db:
        row = db.execute("SELECT * FROM research_runs WHERE id=?", (run_id,)).fetchone()
    if not row: return None
    data = dict(row)
    for key in ("plan", "activity", "missing", "coverage", "conflicts"):
        data[key] = json.loads(data[key] or ("{}" if key in {"plan", "coverage"} else "[]"))
    return data


def get_sources(run_id):
    with connect() as db:
        return [dict(r) for r in db.execute("SELECT id,url,title,publisher,published_at,source_type,content_scope,search_query,snippet,fetch_error,evaluation FROM sources WHERE research_id=? ORDER BY rowid", (run_id,))]


def get_evidence(run_id):
    with connect() as db:
        return [dict(r) for r in db.execute("SELECT * FROM evidence WHERE research_id=? ORDER BY rowid", (run_id,))]


def save_report(run_id, content):
    with connect() as db:
        db.execute("INSERT OR REPLACE INTO reports VALUES(?,?,?)", (run_id, content, datetime.now(timezone.utc).isoformat()))


def get_report(run_id):
    with connect() as db:
        row = db.execute("SELECT content,created_at FROM reports WHERE research_id=?", (run_id,)).fetchone()
    return dict(row) if row else None


def _comparison_timestamp(value=None):
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp must be a non-empty ISO 8601 value")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must be an ISO 8601 value") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _request_dict(request):
    if isinstance(request, PriceComparisonRequest):
        return request.to_dict()
    if isinstance(request, dict):
        return PriceComparisonRequest(**request).to_dict()
    raise ValueError("request must be a PriceComparisonRequest or dictionary")


def create_price_comparison(comparison_id, request, status=ComparisonStatus.QUEUED, created_at=None, updated_at=None):
    """Persist a comparison request in tables separate from research data."""
    comparison_id = comparison_id.strip() if isinstance(comparison_id, str) else ""
    if not comparison_id:
        raise ValueError("comparison_id is required")
    try:
        status = ComparisonStatus(status).value
    except (ValueError, TypeError) as exc:
        raise ValueError("status must be queued, running, completed, or failed") from exc
    created_at = _comparison_timestamp(created_at)
    updated_at = _comparison_timestamp(updated_at) if updated_at is not None else created_at
    completed_at = updated_at if status == ComparisonStatus.COMPLETED.value else None
    with connect() as db:
        db.execute(
            "INSERT INTO price_comparisons(comparison_id,input_data,status,created_at,updated_at,completed_at) VALUES(?,?,?,?,?,?)",
            (comparison_id, json.dumps(_request_dict(request), ensure_ascii=False), status, created_at, updated_at, completed_at),
        )
    return comparison_id


def update_price_comparison(comparison_id, **fields):
    """Update comparison lifecycle fields without touching research runs."""
    allowed = {"status", "updated_at", "completed_at", "error"}
    values = {key: value for key, value in fields.items() if key in allowed}
    if "status" in values:
        try:
            values["status"] = ComparisonStatus(values["status"]).value
        except (ValueError, TypeError) as exc:
            raise ValueError("status must be queued, running, completed, or failed") from exc
        if values["status"] == ComparisonStatus.COMPLETED.value and "completed_at" not in values:
            values["completed_at"] = _comparison_timestamp()
    if "updated_at" not in values:
        values["updated_at"] = _comparison_timestamp()
    for key in ("updated_at", "completed_at"):
        if key in values and values[key] is not None:
            values[key] = _comparison_timestamp(values[key])
    if not values:
        return
    with connect() as db:
        db.execute("UPDATE price_comparisons SET " + ",".join(f"{key}=?" for key in values) + " WHERE comparison_id=?", (*values.values(), comparison_id))


def upsert_price_retailer_check(comparison_id, retailer_result):
    """Persist one retailer's availability/check result for a comparison."""
    if isinstance(retailer_result, dict):
        retailer_result = RetailerResult(**retailer_result)
    if not isinstance(retailer_result, RetailerResult):
        raise ValueError("retailer_result must be a RetailerResult or dictionary")
    check_id = str(uuid.uuid4())
    with connect() as db:
        existing_offers = db.execute(
            "SELECT 1 FROM price_observations WHERE comparison_id=? AND retailer=? LIMIT 1",
            (comparison_id, retailer_result.retailer),
        ).fetchone()
        if existing_offers and retailer_result.status is not RetailerStatus.CHECKED:
            raise ValueError("a retailer with stored price observations cannot be marked unavailable, blocked, or failed")
        db.execute("""INSERT INTO price_retailer_checks(id,comparison_id,retailer,status,message,checked_at,diagnostics)
            VALUES(?,?,?,?,?,?,?) ON CONFLICT(comparison_id,retailer) DO UPDATE SET
            status=excluded.status,message=excluded.message,checked_at=excluded.checked_at,diagnostics=excluded.diagnostics""",
            (check_id, comparison_id, retailer_result.retailer, retailer_result.status.value,
             retailer_result.message, retailer_result.checked_at, json.dumps(retailer_result.diagnostics or {}, ensure_ascii=False)),
        )


def add_price_observation(comparison_id, offer):
    """Persist an observed offer; price remains exact text, never SQLite REAL."""
    if isinstance(offer, dict):
        offer = PriceOffer(**offer)
    if not isinstance(offer, PriceOffer):
        raise ValueError("offer must be a PriceOffer or dictionary")
    observation_id = str(uuid.uuid4())
    product = offer.product
    with connect() as db:
        check = db.execute(
            "SELECT status FROM price_retailer_checks WHERE comparison_id=? AND retailer=?",
            (comparison_id, offer.retailer),
        ).fetchone()
        if not check or check["status"] != RetailerStatus.CHECKED.value:
            raise ValueError("a checked retailer result is required before storing a price observation")
        db.execute("""INSERT INTO price_observations(
            id,comparison_id,product_brand,product_model,product_model_number,product_ram,product_storage,
            product_variant,retailer,price,currency,seller,discount,observed_at,source_url
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            observation_id, comparison_id, product.brand, product.model, product.model_number, product.ram,
            product.storage, product.variant, offer.retailer, format(offer.price, "f"), offer.currency,
            offer.seller, offer.discount, offer.observed_at, offer.source_url,
        ))
    return observation_id


def get_price_retailer_checks(comparison_id, include_diagnostics=True):
    with connect() as db:
        fields = "retailer,status,message,checked_at,diagnostics" if include_diagnostics else "retailer,status,message,checked_at"
        rows = db.execute(f"""SELECT {fields} FROM price_retailer_checks
            WHERE comparison_id=? ORDER BY rowid""", (comparison_id,)).fetchall()
    results = [dict(row) for row in rows]
    if include_diagnostics:
        for result in results:
            result["diagnostics"] = json.loads(result.get("diagnostics") or "{}")
    return results


def get_price_observations(comparison_id):
    with connect() as db:
        rows = db.execute("""SELECT id,product_brand,product_model,product_model_number,product_ram,
            product_storage,product_variant,retailer,price,currency,seller,discount,observed_at,source_url
            FROM price_observations WHERE comparison_id=? ORDER BY rowid""", (comparison_id,)).fetchall()
    offers = []
    for row in rows:
        offer = dict(row)
        offer["product"] = {
            "brand": offer.pop("product_brand"), "model": offer.pop("product_model"),
            "model_number": offer.pop("product_model_number"), "ram": offer.pop("product_ram"),
            "storage": offer.pop("product_storage"), "variant": offer.pop("product_variant"),
        }
        offer["price"] = Decimal(offer["price"])
        offers.append(offer)
    return offers


def get_price_comparison(comparison_id, include_diagnostics=True):
    with connect() as db:
        row = db.execute("SELECT * FROM price_comparisons WHERE comparison_id=?", (comparison_id,)).fetchone()
    if not row:
        return None
    comparison = dict(row)
    comparison["input_data"] = json.loads(comparison["input_data"])
    comparison["retailer_checks"] = get_price_retailer_checks(comparison_id, include_diagnostics=include_diagnostics)
    comparison["offers"] = get_price_observations(comparison_id)
    return comparison


def _generic_value(value):
    """Convert Stage 1 JSON-compatible values to JSON without losing types."""
    from enum import Enum

    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {key: _generic_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_generic_value(item) for item in value]
    return value


def _generic_json(value):
    return json.dumps(_generic_value(value), ensure_ascii=False, allow_nan=False)


def _generic_request_dict(request):
    if isinstance(request, GenericComparisonRequest):
        return request.to_dict()
    if isinstance(request, dict):
        return GenericComparisonRequest(**request).to_dict()
    raise ValueError("request must be a generic ComparisonRequest or dictionary")


def _generic_entity(value):
    if isinstance(value, dict):
        value = EntityReference(**value)
    if not isinstance(value, EntityReference):
        raise ValueError("entity must be an EntityReference or dictionary")
    return value


def _generic_attribute(value):
    if isinstance(value, dict):
        value = AttributeDefinition(**value)
    if not isinstance(value, AttributeDefinition):
        raise ValueError("attribute must be an AttributeDefinition or dictionary")
    return value


def _generic_source_check(value):
    if isinstance(value, dict):
        value = SourceCheck(**value)
    if not isinstance(value, SourceCheck):
        raise ValueError("source_check must be a SourceCheck or dictionary")
    return value


def _generic_observation(value):
    if isinstance(value, dict):
        value = Observation(**value)
    if not isinstance(value, Observation):
        raise ValueError("observation must be an Observation or dictionary")
    return value


def create_comparison_run(comparison_id, request, status=GenericComparisonStatus.QUEUED,
                          created_at=None, updated_at=None):
    """Create an additive, domain-neutral comparison and its request dimensions."""
    comparison_id = comparison_id.strip() if isinstance(comparison_id, str) else ""
    if not comparison_id:
        raise ValueError("comparison_id is required")
    try:
        status = GenericComparisonStatus(status).value
    except (ValueError, TypeError) as exc:
        raise ValueError("status must be queued, running, completed, or failed") from exc
    request_data = _generic_request_dict(request)
    created_at = _comparison_timestamp(created_at)
    updated_at = _comparison_timestamp(updated_at) if updated_at is not None else created_at
    with connect() as db:
        db.execute("""INSERT INTO comparison_runs
            (comparison_id,user_request,request_data,status,created_at,updated_at)
            VALUES(?,?,?,?,?,?)""", (comparison_id, request_data["user_request"],
            _generic_json(request_data), status, created_at, updated_at))
        for entity_data in request_data["entities"]:
            entity = EntityReference(**entity_data)
            db.execute("""INSERT INTO comparison_entities
                (entity_id,comparison_id,entity_key,display_name,entity_type,identifiers,aliases)
                VALUES(?,?,?,?,?,?,?)""", (str(uuid.uuid4()), comparison_id, entity.key,
                entity.display_name, entity.entity_type, _generic_json(entity.identifiers),
                _generic_json(entity.aliases)))
        for attribute_data in request_data["attributes"]:
            attribute = AttributeDefinition(**attribute_data)
            db.execute("""INSERT INTO comparison_attributes
                (attribute_id,comparison_id,attribute_key,label,value_type,unit,currency,comparison_rule)
                VALUES(?,?,?,?,?,?,?,?)""", (str(uuid.uuid4()), comparison_id, attribute.key,
                attribute.label, attribute.value_type.value, attribute.unit, attribute.currency,
                attribute.comparison_rule))
    return comparison_id


def update_comparison_run(comparison_id, **fields):
    """Update generic comparison lifecycle/output fields."""
    allowed = {"status", "updated_at", "error", "analysis", "unresolved", "errors"}
    values = {key: value for key, value in fields.items() if key in allowed}
    if "status" in values:
        try:
            values["status"] = GenericComparisonStatus(values["status"]).value
        except (ValueError, TypeError) as exc:
            raise ValueError("status must be queued, running, completed, or failed") from exc
    if "updated_at" not in values:
        values["updated_at"] = _comparison_timestamp()
    else:
        values["updated_at"] = _comparison_timestamp(values["updated_at"])
    for key in ("unresolved", "errors"):
        if key in values:
            if not isinstance(values[key], list) or not all(isinstance(item, str) for item in values[key]):
                raise ValueError(f"{key} must be a list of strings")
            values[key] = _generic_json(values[key])
    if not values:
        return
    with connect() as db:
        db.execute("UPDATE comparison_runs SET " + ",".join(f"{key}=?" for key in values) +
                   " WHERE comparison_id=?", (*values.values(), comparison_id))


def add_comparison_entities(comparison_id, entities):
    """Persist request-local entities for an existing generic comparison."""
    ids = []
    with connect() as db:
        for item in entities:
            entity = _generic_entity(item)
            entity_id = str(uuid.uuid4())
            db.execute("""INSERT INTO comparison_entities
                (entity_id,comparison_id,entity_key,display_name,entity_type,identifiers,aliases)
                VALUES(?,?,?,?,?,?,?)""", (entity_id, comparison_id, entity.key, entity.display_name,
                entity.entity_type, _generic_json(entity.identifiers), _generic_json(entity.aliases)))
            ids.append(entity_id)
    return ids


def add_comparison_attributes(comparison_id, attributes):
    """Persist dynamic attributes for an existing generic comparison."""
    ids = []
    with connect() as db:
        for item in attributes:
            attribute = _generic_attribute(item)
            attribute_id = str(uuid.uuid4())
            db.execute("""INSERT INTO comparison_attributes
                (attribute_id,comparison_id,attribute_key,label,value_type,unit,currency,comparison_rule)
                VALUES(?,?,?,?,?,?,?,?)""", (attribute_id, comparison_id, attribute.key, attribute.label,
                attribute.value_type.value, attribute.unit, attribute.currency, attribute.comparison_rule))
            ids.append(attribute_id)
    return ids


def upsert_comparison_source_check(comparison_id, source_check):
    """Persist the state of a generic source check (not necessarily a retailer)."""
    check = _generic_source_check(source_check)
    check_id = str(uuid.uuid4())
    source = check.source
    with connect() as db:
        db.execute("""INSERT INTO comparison_source_checks
            (source_check_id,comparison_id,source_key,source_name,source_type,source_url,status,checked_at,diagnostics,error)
            VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(comparison_id,source_key) DO UPDATE SET
            source_name=excluded.source_name,source_type=excluded.source_type,source_url=excluded.source_url,
            status=excluded.status,checked_at=excluded.checked_at,diagnostics=excluded.diagnostics,error=excluded.error""",
            (check_id, comparison_id, source.key, source.name, source.source_type, source.url,
             check.status.value, check.checked_at,
             _generic_json(check.diagnostics) if check.diagnostics is not None else None, check.error))
        row = db.execute("SELECT source_check_id FROM comparison_source_checks WHERE comparison_id=? AND source_key=?",
                         (comparison_id, source.key)).fetchone()
    return row["source_check_id"]


def add_comparison_observation(comparison_id, observation):
    """Persist a raw/normalized observation linked to this run's three references."""
    item = _generic_observation(observation)
    observation_id = str(uuid.uuid4())
    with connect() as db:
        entity = db.execute("SELECT entity_id FROM comparison_entities WHERE comparison_id=? AND entity_key=?",
                            (comparison_id, item.entity_key)).fetchone()
        attribute = db.execute("SELECT attribute_id FROM comparison_attributes WHERE comparison_id=? AND attribute_key=?",
                               (comparison_id, item.attribute_key)).fetchone()
        source = db.execute("SELECT source_check_id FROM comparison_source_checks WHERE comparison_id=? AND source_key=?",
                            (comparison_id, item.source_key)).fetchone()
        if not entity or not attribute or not source:
            raise ValueError("observation entity, attribute, and source check must exist in this comparison")
        db.execute("""INSERT INTO comparison_observations
            (observation_id,comparison_id,entity_id,attribute_id,source_check_id,raw_value,normalized_value,
             value_type,unit,currency,observed_at,source_url,context)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", (observation_id, comparison_id, entity["entity_id"],
            attribute["attribute_id"], source["source_check_id"], _generic_json(item.raw_value),
            _generic_json(item.normalized_value), item.value_type.value, item.unit, item.currency,
            item.observed_at, item.source_url, _generic_json(item.context) if item.context is not None else None))
    return observation_id


def get_comparison_result(comparison_id):
    """Read a complete generic comparison result, or None when absent."""
    with connect() as db:
        run = db.execute("SELECT * FROM comparison_runs WHERE comparison_id=?", (comparison_id,)).fetchone()
        if not run:
            return None
        entities = db.execute("SELECT * FROM comparison_entities WHERE comparison_id=? ORDER BY rowid", (comparison_id,)).fetchall()
        attributes = db.execute("SELECT * FROM comparison_attributes WHERE comparison_id=? ORDER BY rowid", (comparison_id,)).fetchall()
        checks = db.execute("SELECT * FROM comparison_source_checks WHERE comparison_id=? ORDER BY rowid", (comparison_id,)).fetchall()
        observations = db.execute("""SELECT o.*,e.entity_key,a.attribute_key,s.source_key
            FROM comparison_observations o
            JOIN comparison_entities e ON e.comparison_id=o.comparison_id AND e.entity_id=o.entity_id
            JOIN comparison_attributes a ON a.comparison_id=o.comparison_id AND a.attribute_id=o.attribute_id
            JOIN comparison_source_checks s ON s.comparison_id=o.comparison_id AND s.source_check_id=o.source_check_id
            WHERE o.comparison_id=? ORDER BY o.rowid""", (comparison_id,)).fetchall()
    request = GenericComparisonRequest(**json.loads(run["request_data"]))
    entity_models = [EntityReference(key=row["entity_key"], display_name=row["display_name"],
        entity_type=row["entity_type"], identifiers=json.loads(row["identifiers"] or "{}"),
        aliases=json.loads(row["aliases"] or "[]")) for row in entities]
    attribute_models = [AttributeDefinition(key=row["attribute_key"], label=row["label"],
        value_type=row["value_type"], unit=row["unit"], currency=row["currency"],
        comparison_rule=row["comparison_rule"]) for row in attributes]
    source_models = [SourceCheck(source=SourceReference(key=row["source_key"], name=row["source_name"],
        source_type=row["source_type"], url=row["source_url"]), status=row["status"],
        checked_at=row["checked_at"], diagnostics=json.loads(row["diagnostics"]) if row["diagnostics"] is not None else None,
        error=row["error"]) for row in checks]
    observation_models = [Observation(entity_key=row["entity_key"], attribute_key=row["attribute_key"],
        source_key=row["source_key"], raw_value=json.loads(row["raw_value"]),
        normalized_value=json.loads(row["normalized_value"]) if row["normalized_value"] is not None else None,
        value_type=row["value_type"], unit=row["unit"], currency=row["currency"],
        observed_at=row["observed_at"], source_url=row["source_url"],
        context=json.loads(row["context"]) if row["context"] is not None else None) for row in observations]
    errors = json.loads(run["errors"] or "[]")
    if run["error"] and run["error"] not in errors:
        errors.append(run["error"])
    result = GenericComparisonResult(comparison_id=run["comparison_id"], status=run["status"],
        request=request, entities=entity_models, attributes=attribute_models, source_checks=source_models,
        observations=observation_models, analysis=run["analysis"],
        unresolved=json.loads(run["unresolved"] or "[]"), errors=errors,
        created_at=run["created_at"], updated_at=run["updated_at"])
    return result.to_dict()
