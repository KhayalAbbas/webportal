import psycopg2
dsn="postgresql://postgres:postgres@localhost:5432/ats_db"
tenant_id="33333333-3333-3333-3333-333333333333"
run_id="a28031b9-7df9-4ec3-847b-8e1d3f636847"

conn=psycopg2.connect(dsn)
cur=conn.cursor()
cur.execute("""
SELECT COUNT(*) AS orphan_evidence
FROM company_prospect_evidence cpe
JOIN company_prospects cp ON cp.id=cpe.company_prospect_id
LEFT JOIN source_documents sd
  ON sd.tenant_id=cp.tenant_id
 AND sd.company_research_run_id=cp.company_research_run_id
 AND cpe.source_name LIKE CONCAT('%%', sd.content_hash, '%%')
WHERE cp.tenant_id=%s
  AND cp.company_research_run_id=%s
  AND sd.id IS NULL
""", (tenant_id, run_id))
print("Orphan evidence rows:", cur.fetchone()[0])
cur.close(); conn.close()
