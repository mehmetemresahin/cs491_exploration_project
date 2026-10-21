-- Bronze manifest + Silver tables. Idempotent: safe to run on every startup.

CREATE TABLE IF NOT EXISTS bronze_files (
    sha256        VARCHAR PRIMARY KEY,
    tenant_id     VARCHAR NOT NULL,
    original_name VARCHAR NOT NULL,
    uri           VARCHAR NOT NULL,
    size_bytes    BIGINT  NOT NULL,
    ingested_at   TIMESTAMP NOT NULL DEFAULT current_timestamp
);

-- Golden records produced by entity resolution.
CREATE TABLE IF NOT EXISTS entities (
    master_entity_id VARCHAR PRIMARY KEY,
    canonical_name   VARCHAR NOT NULL,
    vkn              VARCHAR
);

CREATE TABLE IF NOT EXISTS extractions (
    extraction_id      VARCHAR PRIMARY KEY,
    sha256             VARCHAR NOT NULL REFERENCES bronze_files (sha256),
    tenant_id          VARCHAR NOT NULL,
    doc_type           VARCHAR NOT NULL,
    document_ref       VARCHAR,
    document_date      DATE,
    counterparty_name  VARCHAR NOT NULL,
    counterparty_vkn   VARCHAR,
    amount             DOUBLE  NOT NULL,
    currency           VARCHAR NOT NULL,
    penalty_rate_daily DOUBLE,
    paid               BOOLEAN,
    page_number        INTEGER,
    bounding_box       DOUBLE[4],
    row_number         INTEGER,
    confidence         DOUBLE  NOT NULL,
    issues             VARCHAR[] NOT NULL,
    status             VARCHAR NOT NULL,
    master_entity_id   VARCHAR REFERENCES entities (master_entity_id),
    created_at         TIMESTAMP NOT NULL DEFAULT current_timestamp
);

-- Fixed mock FX rates (TRY per unit). Stand-in for a central bank feed.
CREATE TABLE IF NOT EXISTS fx_rates (
    currency    VARCHAR PRIMARY KEY,
    rate_to_try DOUBLE NOT NULL
);

INSERT OR IGNORE INTO fx_rates VALUES ('TRY', 1.0), ('USD', 34.2), ('EUR', 37.0);
