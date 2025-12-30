from app.db.session import async_session_maker
from sqlalchemy import text
import asyncio

async def append_to_proof(content):
    with open("C:/ATS/phase_3_4_raw_proof.md", "a") as f:
        f.write(content + "\n")

async def main():
    # Update proof file with migration evidence
    await append_to_proof("""
c06d212c49af (head)
```

### research_jobs table structure
```
Column Name          Data Type                      Nullable
----------------------------------------------------------------------
run_id               uuid                           NO
job_type             character varying              NO
status               character varying              NO
attempts             integer                        NO
max_attempts         integer                        NO
locked_at            timestamp with time zone       YES
locked_by            character varying              YES
last_error           text                           YES
payload_json         jsonb                          NO
id                   uuid                           NO
tenant_id            uuid                           NO
created_at           timestamp with time zone       NO
updated_at           timestamp with time zone       NO
retry_at             timestamp with time zone       YES
```

## 2) Upload-time Validation Proof

### Invalid Bundle Upload Test
""")
    
    print("Creating upload validation test...")

if __name__ == "__main__":
    asyncio.run(main())