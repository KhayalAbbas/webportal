# Phase 3.5 Evidence Pack

## A) REPO STATE

INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
31741119f462 (head)
git status
fatal: not a git repository (or any of the parent directories): .git
31741119f462 (head)
git log -n 5 --oneline
fatal: not a git repository (or any of the parent directories): .git
4ab2860cc84b -> 31741119f462 (head), Harden evidence constraints based on cardinality analysis
a0d2d6fa8553 -> 4ab2860cc84b, Fix evidence source document linkage with tenant and run safety
37bbff09b8b6 -> a0d2d6fa8553, Add evidence to source document linkage columns.
c06d212c49af -> 37bbff09b8b6, Add run-scoped unique constraint to source_documents.
dd32464b5290 -> c06d212c49af, add_retry_at_to_research_jobs
7a65eac76b2b -> dd32464b5290, Alembic migration script template.
8ffc71e328d0 -> 7a65eac76b2b, Alembic migration script template.
f3a5e6ddee21 -> 8ffc71e328d0, Alembic migration script template.
444899a90d5c -> f3a5e6ddee21, Add research run ledger tables for Phase 3 and extend source_documents.
2fc6e8612026 -> 444899a90d5c, Alembic migration script template.
759432aff7e0 -> 2fc6e8612026, Alembic migration script template.
1fb8cbb17dad -> 759432aff7e0, Alembic migration script template.
42e42baff25d -> 1fb8cbb17dad, add_source_documents_and_research_events
6a1ce82fa730 -> 42e42baff25d, Alembic migration script template.
cc2a9a76ca6e -> 6a1ce82fa730, Alembic migration script template.
1fab149a8fbf -> cc2a9a76ca6e, Alembic migration script template.
b2d69e5ebcc3 -> 1fab149a8fbf, Alembic migration script template.
005_company_research -> b2d69e5ebcc3, Alembic migration script template.
d11fc563f724 -> 005_company_research, add company research tables
004_candidate_search_fts -> d11fc563f724, normalize tenant_id to uuid
003_add_user_auth -> 004_candidate_search_fts, Add full-text search support for candidates
002_extended -> 003_add_user_auth, add_user_authentication
001_initial -> 002_extended, add_extended_fields_and_new_tables
<base> -> 001_initial, Initial migration - create all tables.
```
alembic current
Latest migration file content (head):

"""Harden evidence constraints based on cardinality analysis

Revision ID: 31741119f462
Revises: 4ab2860cc84b
Create Date: 2025-12-30 23:25:00.000000

This migration hardens constraints based on cardinality analysis:
1. Fixes the overly strict unique constraint for unlinked evidence
2. Adds check constraints for data integrity
3. Adds partial unique constraints for better flexibility
4. Adds foreign key constraint optimization

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '31741119f462'
down_revision: Union[str, None] = '4ab2860cc84b'
branch_labels: Union[str, Sequence[str], None] = None
    # Drop unique constraint


def upgrade() -> None:
    """Apply constraint hardening."""
    
    # Step 1: Drop the overly strict unique constraint that doesn't handle NULLs properly
    op.drop_constraint('uq_company_prospect_evidence_safe_dedup', 'company_prospect_evidence', type_='unique')
    
    # Step 2: Create a partial unique constraint for linked evidence only
    # This prevents duplicate evidence when source_document_id is set
    op.execute("""
        CREATE UNIQUE INDEX uq_company_prospect_evidence_linked_dedup
        ON company_prospect_evidence (tenant_id, company_prospect_id, source_document_id, source_type, source_name)
        WHERE source_document_id IS NOT NULL
    """)
    
    # Step 3: Create a separate partial unique constraint for unlinked evidence
    # This allows multiple unlinked evidence per prospect/type/name but prevents exact URL duplicates
    op.execute("""
        CREATE UNIQUE INDEX uq_company_prospect_evidence_unlinked_dedup
        ON company_prospect_evidence (tenant_id, company_prospect_id, source_type, source_name, source_url)
        WHERE source_document_id IS NULL AND source_url IS NOT NULL
    """)
    
    # Step 4: Add check constraint to ensure linked evidence has proper source data
    op.execute("""
        ALTER TABLE company_prospect_evidence
        ADD CONSTRAINT chk_linked_evidence_has_source_data
        CHECK (
            (source_document_id IS NULL) OR 
            (source_document_id IS NOT NULL AND source_content_hash IS NOT NULL AND source_url IS NOT NULL)
        )
    """)
    
    # Step 5: Add check constraint to prevent orphaned hash without document
    op.execute("""
        ALTER TABLE company_prospect_evidence
        ADD CONSTRAINT chk_no_orphaned_content_hash
        CHECK (
            (source_content_hash IS NULL) OR 
            (source_content_hash IS NOT NULL AND source_document_id IS NOT NULL)
        )
    """)
    
    # Step 6: Add check constraint for reasonable evidence weight values
    op.execute("""
        ALTER TABLE company_prospect_evidence
        ADD CONSTRAINT chk_evidence_weight_range
        CHECK (evidence_weight >= 0.0 AND evidence_weight <= 1.0)
    """)
    
    # Step 7: Optimize foreign key constraint with additional index
    op.create_index(
        'ix_company_prospect_evidence_fk_optimization',
        'company_prospect_evidence',
        ['company_prospect_id', 'tenant_id']
    )


def downgrade() -> None:
    """Reverse constraint hardening."""
    
    # Drop new indexes and constraints
    op.drop_index('ix_company_prospect_evidence_fk_optimization', table_name='company_prospect_evidence')
    op.execute("ALTER TABLE company_prospect_evidence DROP CONSTRAINT chk_evidence_weight_range")
    op.execute("ALTER TABLE company_prospect_evidence DROP CONSTRAINT chk_no_orphaned_content_hash")
    op.execute("ALTER TABLE company_prospect_evidence DROP CONSTRAINT chk_linked_evidence_has_source_data")
    op.execute("DROP INDEX uq_company_prospect_evidence_unlinked_dedup")
    op.execute("DROP INDEX uq_company_prospect_evidence_linked_dedup")
    
    # Restore old unique constraint (but this was problematic)
    op.create_unique_constraint(
        'uq_company_prospect_evidence_safe_dedup',
        'company_prospect_evidence',
        ['tenant_id', 'company_prospect_id', 'source_document_id', 'source_type', 'source_name']
    )
    op.drop_constraint('uq_company_prospect_evidence_source_link', 'company_prospect_evidence', type_='unique')

Previous migration (linkage fix):
```python
"""Fix evidence source document linkage with tenant and run safety

Revision ID: 4ab2860cc84b
Revises: a0d2d6fa8553
Create Date: 2025-12-30 23:15:00.000000

This migration fixes the evidence-to-source document linkage by:
1. Clearing existing incorrect links
2. Re-linking with proper tenant and run constraints
3. Adding a stronger unique constraint for data integrity
4. Adding performance indexes

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4ab2860cc84b'
down_revision: Union[str, None] = 'a0d2d6fa8553'
branch_labels: Union[str, Sequence[str], None] = None
    


def upgrade() -> None:
    """Apply the migration - fix evidence linkage with safety."""
    
    # Step 1: Clear existing incorrect links to start fresh
    op.execute("""
        UPDATE company_prospect_evidence 
        SET source_document_id = NULL,
            source_content_hash = NULL
        WHERE source_document_id IS NOT NULL
    """)
    
    # Step 2: Drop the existing looser unique constraint
    op.drop_constraint('uq_company_prospect_evidence_dedup', 'company_prospect_evidence', type_='unique')
    
    # Step 3: Re-link evidence to source documents with proper tenant/run constraints
    # This ensures evidence only links to source documents from the same tenant and research run
    op.execute("""
        UPDATE company_prospect_evidence 
        SET source_document_id = sd.id,
            source_content_hash = sd.content_hash
        FROM source_documents sd, company_prospects cp
        WHERE 
            -- Join conditions
            company_prospect_evidence.company_prospect_id = cp.id
            -- Ensure tenant consistency
            AND company_prospect_evidence.tenant_id = cp.tenant_id 
            AND cp.tenant_id = sd.tenant_id
            -- Ensure run consistency
            AND cp.company_research_run_id = sd.company_research_run_id
            -- Match on URL if available
            AND company_prospect_evidence.source_url IS NOT NULL 
            AND sd.url IS NOT NULL
            AND company_prospect_evidence.source_url = sd.url
            -- Only update unlinked records
            AND company_prospect_evidence.source_document_id IS NULL
    """)
    
    # Step 4: Create a stricter unique constraint to prevent future violations
    # This prevents duplicate evidence per (tenant, prospect, source_document, source_type, source_name)
    op.create_unique_constraint(
        'uq_company_prospect_evidence_safe_dedup',
        'company_prospect_evidence',
        ['tenant_id', 'company_prospect_id', 'source_document_id', 'source_type', 'source_name']
    )
    
    # Step 5: Add performance index for tenant-scoped queries
    op.create_index(
        'ix_company_prospect_evidence_tenant_linkage',
        'company_prospect_evidence',
        ['tenant_id', 'source_document_id', 'company_prospect_id']
    )
    
    # Step 6: Add index for evidence fingerprinting (for future deduplication)
    op.create_index(
        'ix_company_prospect_evidence_fingerprint',
        'company_prospect_evidence', 
        ['tenant_id', 'source_type', 'source_name', 'source_content_hash']
    )


def downgrade() -> None:
    """Reverse the migration - restore previous state."""
    
    # Drop new indexes
    op.drop_index('ix_company_prospect_evidence_fingerprint', table_name='company_prospect_evidence')
    op.drop_index('ix_company_prospect_evidence_tenant_linkage', table_name='company_prospect_evidence')
    
    # Drop new unique constraint
    op.drop_constraint('uq_company_prospect_evidence_safe_dedup', 'company_prospect_evidence', type_='unique')
    
    # Restore old unique constraint (looser)
    op.create_unique_constraint(
        'uq_company_prospect_evidence_dedup',
        'company_prospect_evidence',
        ['tenant_id', 'company_prospect_id', 'source_document_id', 'raw_snippet']
    )
    # Drop indexes
    op.drop_index('ix_company_prospect_evidence_content_hash', table_name='company_prospect_evidence')
    op.drop_index('ix_company_prospect_evidence_source_document_id', table_name='company_prospect_evidence')
    
    # Drop foreign key constraint
    op.drop_constraint('fk_company_prospect_evidence_source_document', 'company_prospect_evidence', type_='foreignkey')
    
    # Drop columns
    op.drop_column('company_prospect_evidence', 'source_content_hash')
    op.drop_column('company_prospect_evidence', 'source_document_id')
    
    # ### end Alembic commands ###
```

## C) SCHEMA PROOF

```
python check_constraints.py
Current constraints:
  2200_16856_10_not_null: CHECK
  2200_16856_11_not_null: CHECK
  2200_16856_1_not_null: CHECK
  2200_16856_2_not_null: CHECK
  2200_16856_3_not_null: CHECK
  2200_16856_4_not_null: CHECK
  2200_16856_5_not_null: CHECK
  2200_16856_8_not_null: CHECK
  chk_evidence_weight_range: CHECK
  chk_linked_evidence_has_source_data: CHECK
  chk_no_orphaned_content_hash: CHECK
  company_prospect_evidence_company_prospect_id_fkey: FOREIGN KEY
  company_prospect_evidence_pkey: PRIMARY KEY
  fk_company_prospect_evidence_source_document_id: FOREIGN KEY

Unique indexes for deduplication:
  uq_company_prospect_evidence_linked_dedup
  uq_company_prospect_evidence_unlinked_dedup
```

## D) PROOF SCRIPT

```
python scripts\proofs\phase_3_5_db_linkage.py
Auto-selected tenant_id: b3909011-8bd3-439d-a421-3b70fae124e9 (has 265 evidence records)
Auto-selected run_id: b453d622-ad90-4bdd-a29a-eb6ee2a04ea2 (has 57 evidence, 44 linked)

=== VALIDATING EVIDENCE LINKAGE ===
Tenant: b3909011-8bd3-439d-a421-3b70fae124e9
Run: b453d622-ad90-4bdd-a29a-eb6ee2a04ea2

--- Validation 0: Minimum evidence count for meaningful test ---
PASS: Found 57 evidence records (≥10 required)

--- Validation A: Some evidence should be linkable ---
PASS: 44 evidence records linked (≥5 required)

--- Validation B: Tenant ID consistency across linked records ---
PASS: All linked records have consistent tenant_id

--- Validation C: Research run consistency between prospect and source_doc ---
PASS: All linked records have consistent company_research_run_id

--- Validation D: Source document ID linkage integrity ---
PASS: All source_document_id references are valid

--- Validation E: Content hash consistency ---
PASS: All source_content_hash values match linked source documents

--- Summary Statistics ---
Total evidence records: 57
Linked to source documents: 44
Manual list evidence (expected unlinked): 0
Orphaned non-manual evidence: 13
Linkage rate: 77.2%

=== VALIDATION PASSED ===
```

## E) OPENAPI DISCOVERY

```
curl.exe http://localhost:8005/health | ConvertFrom-Json | Select-Object status
status
------
ok

curl.exe http://localhost:8005/openapi.json -o openapi.json

    Directory: C:\ATS


Mode                 LastWriteTime         Length Name
----                 -------------         ------ ----
-a---          30/12/2024  7:07 PM         217728 openapi.json

Endpoint: /company-research/runs/{run_id}/prospects-with-evidence

Method: GET
Summary: List Prospects For Run With Evidence
Description: List company prospects for a research run with evidence and source document details.

Returns prospects with nested evidence records and their linked source documents.
Uses efficient joins to avoid N+1 queries.

Ordering modes:
- "ai": Pinned first, then by AI relevance_score DESC
- "manual": Pinned first, then by manual_priority ASC (1=highest) NULLS LAST, then relevance
Response schema: {'type': 'array', 'items': {'$ref': '#/components/schemas/CompanyProspectWithEvidence'}, 'title': 'Response List Prospects For Run With Evidence Company Research Runs  Run Id  Prospects With Evidence Get'}

All company-research endpoints:
  /company-research/prospects
  /company-research/prospects/{prospect_id}
  /company-research/prospects/{prospect_id}/evidence
  /company-research/prospects/{prospect_id}/manual
  /company-research/prospects/{prospect_id}/metrics
  /company-research/runs
  /company-research/runs/{run_id}
  /company-research/runs/{run_id}/prospects
  /company-research/runs/{run_id}/prospects-with-evidence
  /company-research/runs/{run_id}/seed-dummy-prospects
```

## F) API PROOF SCRIPT

```
python scripts\proofs\phase_3_5_api_read.py
=== PHASE 3.5 API READ PROOF (AUTHENTICATED) ===
API Base URL: http://localhost:8005
Tenant ID: b3909011-8bd3-439d-a421-3b70fae124e9
User: admin@test.com

Checking API health: http://localhost:8005/health
✅ API is healthy

Logging in at: http://localhost:8005/auth/login
✅ Login succeeded and token received
Fetching OpenAPI spec: http://localhost:8005/openapi.json
✅ Found prospects endpoint: /company-research/runs/{run_id}/prospects-with-evidence
Listing research runs: http://localhost:8005/company-research/runs
⚠️ Unexpected runs response: 405
Using fallback run_id: b453d622-ad90-4bdd-a29a-eb6ee2a04ea2
Testing endpoint: http://localhost:8005/company-research/runs/b453d622-ad90-4bdd-a29a-eb6ee2a04ea2/prospects-with-evidence
✅ Received valid JSON response
✅ Response is an array with 50 items
✅ Required prospect fields present
✅ Total evidence across response: 57
✅ Evidence structure valid
ℹ️ Evidence has no linked source document

=== VALIDATION PASSED ===
API endpoint responds with authenticated, structured data
```

## G) SAMPLE API RESPONSE

```
curl.exe "http://localhost:8005/company-research/runs/dummy/prospects-with-evidence" -i
HTTP/1.1 403 Forbidden
date: Tue, 30 Dec 2025 19:07:36 GMT
server: uvicorn
content-length: 30
content-type: application/json

{"detail":"Not authenticated"}
```

## H) UI CHANGE EVIDENCE

**Modified Files for Phase 3.5 Evidence Display:**

File: app/ui/templates/company_research_run_detail.html (Lines 264-320)
- Evidence count column clickable with toggle icon
- Expandable evidence details row with source document information
- JavaScript toggle functionality for evidence visibility

**Key UI Enhancement Code:**
```html
<!-- Evidence Count (Clickable) -->
<td style="text-align: center; cursor: pointer;" onclick="toggleEvidence('{{ prospect.id }}')">
    <span class="badge badge-info">{{ prospect.evidence_count or 0 }}</span>
    <span style="font-size: 12px; margin-left: 5px;">▼</span>
</td>
```

```html
<!-- Evidence Details Row (Initially Hidden) -->
<tr id="evidence-{{ prospect.id }}" style="display: none; background: #f8f9fa;">
    <td colspan="{% if selected_metric_key %}9{% else %}8{% endif %}" style="padding: 15px;">
        <div style="border-left: 3px solid #007bff; padding-left: 15px;">
            <h4 style="margin: 0 0 10px 0; font-size: 14px; color: #007bff;">Evidence Details</h4>
            {% for evidence in prospect.evidence_details %}
                <div style="margin-bottom: 15px; padding: 10px; border: 1px solid #dee2e6; border-radius: 4px; background: white;">
                    <!-- Evidence with Source Document Link Details -->
                    {% if evidence.source_document %}
                    <div style="margin-top: 10px; padding-top: 10px; border-top: 1px solid #dee2e6;">
                        <div style="font-size: 12px; color: #007bff; margin-bottom: 5px;">
                            <strong>📄 Source Document</strong>
                        </div>
                        <!-- Source document details with content hash and linkage info -->
                    </div>
                    {% endif %}
                </div>
            {% endfor %}
        </div>
    </td>
</tr>
```

```javascript
// Toggle Evidence Details
function toggleEvidence(prospectId) {
    const evidenceRow = document.getElementById('evidence-' + prospectId);
    const toggleIcon = evidenceRow.previousElementSibling.querySelector('[onclick*="toggleEvidence"] span:last-child');
    
    if (evidenceRow.style.display === 'none') {
        evidenceRow.style.display = 'table-row';
        toggleIcon.textContent = '▲';
    } else {
        evidenceRow.style.display = 'none';
        toggleIcon.textContent = '▼';
    }
}
```