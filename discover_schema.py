#!/usr/bin/env python3

import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

conn = psycopg2.connect(
    host=os.getenv('DB_HOST', 'localhost'),
    port=os.getenv('DB_PORT', 5432),
    database=os.getenv('DB_NAME', 'ats_db'),
    user=os.getenv('DB_USER', 'postgres'),
    password=os.getenv('DB_PASSWORD', 'postgres')
)
cur = conn.cursor()

print('=== TABLE: company_prospect_evidence ===')
cur.execute("""
    SELECT column_name, data_type, is_nullable, column_default
    FROM information_schema.columns
    WHERE table_name = 'company_prospect_evidence'
    ORDER BY ordinal_position;
""")
for row in cur.fetchall():
    print(f'  {row[0]}: {row[1]} (nullable: {row[2]}, default: {row[3]})')

cur.execute("""
    SELECT indexname, indexdef
    FROM pg_indexes
    WHERE tablename = 'company_prospect_evidence';
""")
print('  INDEXES:')
for row in cur.fetchall():
    print(f'    {row[0]}: {row[1]}')

cur.execute("""
    SELECT conname, pg_get_constraintdef(oid)
    FROM pg_constraint
    WHERE conrelid = 'company_prospect_evidence'::regclass;
""")
print('  CONSTRAINTS:')
for row in cur.fetchall():
    print(f'    {row[0]}: {row[1]}')

print()
print('=== TABLE: source_documents ===')
cur.execute("""
    SELECT column_name, data_type, is_nullable, column_default
    FROM information_schema.columns
    WHERE table_name = 'source_documents'
    ORDER BY ordinal_position;
""")
for row in cur.fetchall():
    print(f'  {row[0]}: {row[1]} (nullable: {row[2]}, default: {row[3]})')

cur.execute("""
    SELECT indexname, indexdef
    FROM pg_indexes
    WHERE tablename = 'source_documents';
""")
print('  INDEXES:')
for row in cur.fetchall():
    print(f'    {row[0]}: {row[1]}')

cur.execute("""
    SELECT conname, pg_get_constraintdef(oid)
    FROM pg_constraint
    WHERE conrelid = 'source_documents'::regclass;
""")
print('  CONSTRAINTS:')
for row in cur.fetchall():
    print(f'    {row[0]}: {row[1]}')

print()
print('=== TABLE: company_prospects ===')
cur.execute("""
    SELECT column_name, data_type, is_nullable, column_default
    FROM information_schema.columns
    WHERE table_name = 'company_prospects'
    ORDER BY ordinal_position;
""")
for row in cur.fetchall():
    print(f'  {row[0]}: {row[1]} (nullable: {row[2]}, default: {row[3]})')

print()
print('=== TABLE: company_research_runs ===')
cur.execute("""
    SELECT column_name, data_type, is_nullable, column_default
    FROM information_schema.columns
    WHERE table_name = 'company_research_runs'
    ORDER BY ordinal_position;
""")
for row in cur.fetchall():
    print(f'  {row[0]}: {row[1]} (nullable: {row[2]}, default: {row[3]})')

cur.close()
conn.close()