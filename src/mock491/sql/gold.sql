-- Gold layer: read-only views the dashboard (and later Text-to-SQL) query.
-- Rejected and still-pending extractions are excluded from KPIs.

CREATE OR REPLACE VIEW gold_extractions AS
SELECT
    e.*,
    e.amount * fx.rate_to_try AS amount_try
FROM extractions e
JOIN fx_rates fx USING (currency)
WHERE e.status IN ('auto_approved', 'approved');

CREATE OR REPLACE VIEW gold_entity_exposure AS
SELECT
    ent.master_entity_id,
    ent.canonical_name,
    ent.vkn,
    count(DISTINCT g.tenant_id)          AS tenant_count,
    list(DISTINCT g.tenant_id ORDER BY g.tenant_id) AS tenants,
    count(*)                             AS document_count,
    sum(g.amount_try)                    AS total_exposure_try,
    max(g.penalty_rate_daily)            AS max_penalty_rate_daily
FROM gold_extractions g
JOIN entities ent USING (master_entity_id)
GROUP BY ALL
ORDER BY total_exposure_try DESC;

CREATE OR REPLACE VIEW gold_tenant_summary AS
SELECT
    tenant_id,
    count(*)          AS document_count,
    sum(amount_try)   AS total_try
FROM gold_extractions
GROUP BY tenant_id
ORDER BY total_try DESC;

CREATE OR REPLACE VIEW gold_review_queue AS
SELECT
    e.extraction_id,
    e.tenant_id,
    e.doc_type,
    e.counterparty_name,
    e.amount,
    e.currency,
    e.counterparty_vkn,
    e.confidence,
    e.issues,
    b.original_name AS source_file,
    e.page_number,
    e.row_number,
    b.uri AS source_uri,
    e.bounding_box
FROM extractions e
JOIN bronze_files b USING (sha256)
WHERE e.status = 'pending_review'
ORDER BY e.confidence;
