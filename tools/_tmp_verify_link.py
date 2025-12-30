import psycopg2
dsn="postgresql://postgres:postgres@localhost:5432/ats_db"
tenant_id="33333333-3333-3333-3333-333333333333"
run_id="a28031b9-7df9-4ec3-847b-8e1d3f636847"

conn=psycopg2.connect(dsn)
cur=conn.cursor()
cur.execute("""
SELECT
  cpe.id AS evidence_id,
  cp.company_research_run_id AS prospect_run_id,
  sd.id AS source_doc_id,
  sd.company_research_run_id AS source_run_id,
  sd.content_hash
FROM company_prospect_evidence cpe
JOIN company_prospects cp ON cp.id=cpe.company_prospect_id
JOIN source_documents sd
  ON sd.tenant_id=cp.tenant_id
 AND sd.company_research_run_id=cp.company_research_run_id
 AND cpe.source_name LIKE CONCAT('%%', sd.content_hash, '%%')
WHERE cp.tenant_id=%s AND cp.company_research_run_id=%s
ORDER BY cpe.created_at DESC
LIMIT 1
""", (tenant_id, run_id))
print(cur.fetchone())
cur.close()
conn.close()
