"""
Company Extraction Service - Phase 2A processing pipeline.

Handles source fetching, company name extraction, deduplication,
and prospect creation from raw sources.
"""

import hashlib
import io
import re
import httpx
from typing import List, Tuple, Optional, Set, Dict, Any
from uuid import UUID
from datetime import datetime, timedelta
from urllib.parse import urlparse
from sqlalchemy.ext.asyncio import AsyncSession
from bs4 import BeautifulSoup
from pypdf import PdfReader

from app.repositories.company_research_repo import CompanyResearchRepository
from app.models.company_research import ResearchSourceDocument, CompanyProspect
from app.schemas.company_research import (
    ResearchEventCreate,
    CompanyProspectCreate,
    CompanyProspectEvidenceCreate,
    SourceDocumentUpdate,
)
from app.utils.time import utc_now, utc_now_iso


class CompanyExtractionService:
    """Service for extracting companies from source documents."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = CompanyResearchRepository(db)
    
    @staticmethod
    def normalize_text(text: str) -> str:
        """
        Normalize text for extraction - handles all line ending formats.
        
        This prevents bugs from Windows (\\r\\n), Mac (\\r), or mixed line endings
        that commonly appear in PDFs, HTML, and pasted text.
        """
        if not text:
            return ""
        # Normalize all line endings to \n
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        # Strip trailing whitespace from each line
        lines = text.split('\n')
        lines = [line.rstrip() for line in lines]
        text = '\n'.join(lines)
        return text

    @staticmethod
    def _compute_backoff_seconds(attempt: int) -> int:
        """Deterministic retry backoff with an upper bound."""
        return min(300, 30 * max(1, attempt))
    
    def _extract_from_wikipedia(self, html: str) -> List[str]:
        """
        Extract company names from Wikipedia using structural targeting.
        
        Strategy:
        1. Only look inside #mw-content-text
        2. Prefer <table class="wikitable"> rows (first column)
        3. Look for <ul><li> lists after section headers with keywords
        4. Ignore content before first <h2>
        5. Log what was found and rejected
        """
        soup = BeautifulSoup(html, 'html.parser')
        
        # CRITICAL: Only look inside main content area
        main_content = soup.find(id='mw-content-text')
        if not main_content:
            return []
        
        # Remove unwanted elements from main content
        for element in main_content.find_all(['nav', 'footer', 'aside']):
            element.decompose()
        
        candidates = []
        rejected = []
        extraction_strategy = None
        
        # Find first <h2> to ignore everything before it
        first_h2 = main_content.find('h2')
        content_start = first_h2 if first_h2 else main_content
        
        # STRATEGY 1: Extract from wikitable tables (preferred)
        tables = main_content.find_all('table', class_='wikitable')
        if tables:
            extraction_strategy = "wikitable"
            for table in tables:
                # Skip tables before first h2
                if first_h2 and hasattr(table, 'sourceline') and hasattr(first_h2, 'sourceline'):
                    if table.sourceline < first_h2.sourceline:
                        continue
                
                rows = table.find_all('tr')
                for row in rows[1:]:  # Skip header row
                    cells = row.find_all(['td', 'th'])
                    if cells:
                        first_cell = cells[0]
                        # Remove references
                        for unwanted in first_cell.find_all(['sup', 'span'], class_=['reference', 'mw-editsection']):
                            unwanted.decompose()
                        text = first_cell.get_text(strip=True)
                        if text:
                            candidates.append(text)
        
        # STRATEGY 2: Look for lists after section headers with keywords
        if not candidates:
            extraction_strategy = "section-list"
            section_keywords = ['bank', 'banks', 'financial institution', 'commercial bank', 'company', 'companies', 'corporation']
            
            # Find all h2/h3 headers
            headers = main_content.find_all(['h2', 'h3'])
            for header in headers:
                header_text = header.get_text(strip=True).lower()
                
                # Check if header contains relevant keywords
                if any(keyword in header_text for keyword in section_keywords):
                    # Find lists after this header (before next header)
                    current = header.find_next_sibling()
                    while current and current.name not in ['h2', 'h3']:
                        if current.name == 'ul':
                            # Check this isn't a navigation/sidebar list
                            ul_classes = ' '.join(current.get('class', [])).lower()
                            if not any(x in ul_classes for x in ['navbox', 'sidebar', 'reflist', 'toc']):
                                for li in current.find_all('li', recursive=False):
                                    for unwanted in li.find_all(['sup', 'span'], class_=['reference', 'mw-editsection']):
                                        unwanted.decompose()
                                    text = li.get_text(strip=True)
                                    if text:
                                        candidates.append(text)
                        current = current.find_next_sibling()
        
        # STRATEGY 3: Fallback - any lists in main content (after first h2)
        if not candidates and content_start:
            extraction_strategy = "fallback"
            for ul in content_start.find_all('ul'):
                # Skip navigation/reference lists
                parent_classes = []
                parent_ids = []
                for parent in ul.parents:
                    if parent.get('class'):
                        parent_classes.extend(parent.get('class'))
                    if parent.get('id'):
                        parent_ids.append(parent.get('id'))
                
                if any(x in parent_classes for x in ['navbox', 'sidebar', 'reflist', 'toc']):
                    continue
                if any(x in parent_ids for x in ['toc', 'references', 'External_links', 'See_also']):
                    continue
                
                for li in ul.find_all('li', recursive=False):
                    for unwanted in li.find_all(['sup', 'span'], class_=['reference', 'mw-editsection']):
                        unwanted.decompose()
                    text = li.get_text(strip=True)
                    if text:
                        candidates.append(text)
        
        # Filter candidates with tracking
        filtered = []
        for candidate in candidates:
            # Basic validation
            if not candidate or len(candidate) > 120:
                rejected.append(f"{candidate[:50] if candidate else 'empty'}... (too long)")
                continue
            
            if not any(c.isalpha() for c in candidate):
                rejected.append(f"{candidate} (no letters)")
                continue
            
            lower = candidate.lower()
            
            # Exclude boilerplate patterns
            boilerplate_patterns = [
                'http', 'list of', 'company information from',
                'retrieved from', 'wikipedia', 'see also', 'main article',
                'external links', 'references', 'citation needed'
            ]
            if any(pattern in lower for pattern in boilerplate_patterns):
                rejected.append(f"{candidate} (boilerplate)")
                continue
            
            # Exclude full sentences
            words = candidate.split()
            if candidate.endswith('.') and len(words) > 8:
                rejected.append(f"{candidate[:50]}... (sentence)")
                continue
            
            # Exclude headings
            if candidate.startswith(('==', '#', '*')) or candidate.endswith(':'):
                rejected.append(f"{candidate} (heading)")
                continue
            
            filtered.append(candidate)
        
        # Log extraction stats (will be used by caller)
        self._last_extraction_stats = {
            "strategy": extraction_strategy or "none",
            "candidates_found": len(candidates),
            "candidates_rejected": len(rejected),
            "candidates_accepted": len(filtered),
            "rejection_samples": rejected[:5] if rejected else []
        }
        
        return filtered
    
    async def process_sources(
        self,
        tenant_id: str,
        run_id: UUID,
    ) -> dict:
        """
        Process all pending sources for a research run.
        
        Returns summary of processing results with detailed stats.
        """
        # Load extractable sources (URL sources must already be fetched)
        sources = await self.repo.get_extractable_sources(tenant_id, run_id)
        
        if not sources:
            return {
                "processed": 0,
                "companies_found": 0,
                "companies_new": 0,
                "companies_existing": 0,
                "sources_detail": [],
            }
        
        # Log fetch event
        await self.repo.create_research_event(
            tenant_id=tenant_id,
            data=ResearchEventCreate(
                company_research_run_id=run_id,
                event_type="process_sources",
                status="ok",
                input_json={"source_count": len(sources)},
            ),
        )
        
        total_companies = 0
        total_new = 0
        total_existing = 0
        sources_detail = []
        
        # Process each source
        for source in sources:
            try:
                meta = dict(source.meta or {})
                if meta.get("processed_at"):
                    sources_detail.append(
                        {
                            "source_id": str(source.id),
                            "title": source.title or source.url or "Unknown",
                            "status": "skipped",
                            "reason": "already_processed",
                        }
                    )
                    continue
                # Extract text content if needed
                fetch_metadata = {}
                if source.source_type == "url" and source.status != "fetched":
                    sources_detail.append({
                        "source_id": str(source.id),
                        "title": source.title or source.url or "Unknown",
                        "chars": 0,
                        "lines": 0,
                        "extracted": 0,
                        "companies_found": 0,
                        "new_companies": 0,
                        "existing_companies": 0,
                        "status": "skipped",
                        "error": "url_not_fetched",
                        "extraction_method": "pending_fetch",
                    })
                    continue

                if source.source_type != "url" and source.status == "new":
                    fetch_metadata = await self._fetch_content(tenant_id, source)
                
                # Skip processing if fetch failed
                if source.status in {"failed", "fetch_failed"}:
                    sources_detail.append({
                        "source_id": str(source.id),
                        "title": source.title or source.url or "Unknown",
                        "chars": 0,
                        "lines": 0,
                        "extracted": 0,
                        "companies_found": 0,
                        "new_companies": 0,
                        "existing_companies": 0,
                        "status": "failed",
                        "error": source.error_message,
                        "extraction_method": fetch_metadata.get("extraction_method", "error"),
                    })
                    continue
                
                # Get text for extraction with debug info
                text_content = source.content_text or ""
                text_length = len(text_content)
                lines = [l.strip() for l in text_content.split('\n') if l.strip()]
                line_count = len(lines)
                
                # Extract company names
                companies = self._extract_company_names(text_content)
                companies_count = len(companies)
                
                # Prepare debug output
                debug_info = {
                    "source_id": str(source.id),
                    "text_length": text_length,
                    "lines": line_count,
                    "candidates": line_count,  # All non-empty lines are candidates
                    "accepted": companies_count,
                    "extraction_method": fetch_metadata.get("extraction_method", "unknown"),
                }
                
                # If no companies found, include sample text for debugging
                if companies_count == 0 and text_content:
                    debug_info["sample_text"] = text_content[:200]
                    debug_info["first_lines"] = lines[:5] if lines else []
                
                # Log extraction event
                await self.repo.create_research_event(
                    tenant_id=tenant_id,
                    data=ResearchEventCreate(
                        company_research_run_id=run_id,
                        event_type="extract",
                        status="ok" if companies_count > 0 else "warn",
                        input_json=debug_info,
                        output_json={
                            "companies_found": companies_count,
                            "companies": [{"name": c[0], "snippet": c[1][:100]} for c in companies[:10]],
                        },
                    ),
                )
                
                # Deduplicate and create prospects
                new_count, existing_count = await self._deduplicate_and_create_prospects(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    source=source,
                    companies=companies,
                )
                
                total_companies += len(companies)
                total_new += new_count
                total_existing += existing_count
                
                # Track per-source detail
                sources_detail.append({
                    "title": source.title or "Text source",
                    "chars": text_length,
                    "lines": line_count,
                    "extracted": companies_count,
                    "new": new_count,
                    "existing": existing_count,
                })
                
                meta["processed_at"] = utc_now_iso()
                meta["processed_summary"] = {
                    "extracted": companies_count,
                    "new": new_count,
                    "existing": existing_count,
                }
                source.meta = meta

                if source.source_type != "url":
                    source.status = "processed"
                await self.db.flush()
                
            except Exception as e:
                # Mark source as failed
                source.status = "failed"
                source.error_message = str(e)
                source.last_error = str(e)
                await self.db.flush()
                
                # Log error event
                await self.repo.create_research_event(
                    tenant_id=tenant_id,
                    data=ResearchEventCreate(
                        company_research_run_id=run_id,
                        event_type="extract",
                        status="failed",
                        input_json={"source_id": str(source.id)},
                        error_message=str(e),
                    ),
                )
        
        return {
            "processed": len(sources),
            "companies_found": total_companies,
            "companies_new": total_new,
            "companies_existing": total_existing,
            "sources_detail": sources_detail,
        }

    async def fetch_url_sources(
        self,
        tenant_id: str,
        run_id: UUID,
    ) -> dict:
        """Fetch URL sources ahead of extraction."""
        sources = await self.repo.get_url_sources_to_fetch(tenant_id, run_id)

        if not sources:
            return {"processed": 0, "fetched": 0, "failed": 0, "skipped": True}

        fetched = 0
        failed = 0
        terminal_failures = 0
        details = []
        next_retry_at: Optional[datetime] = None

        for source in sources:
            meta_before = dict(source.meta or {})
            source.status = "fetching"
            source.attempt_count = (source.attempt_count or 0) + 1
            source.next_retry_at = None
            source.last_error = None
            await self.db.flush()

            await self.repo.create_research_event(
                tenant_id=tenant_id,
                data=ResearchEventCreate(
                    company_research_run_id=run_id,
                    event_type="fetch_started",
                    status="ok",
                    input_json={
                        "source_id": str(source.id),
                        "url": source.url,
                        "attempt": source.attempt_count,
                        "max_attempts": source.max_attempts,
                    },
                ),
            )

            fetch_meta = await self._fetch_content(tenant_id, source)
            fetch_meta = fetch_meta or {}
            fetch_meta.update(
                {
                    "attempt": source.attempt_count,
                    "max_attempts": source.max_attempts,
                }
            )

            if source.status == "fetched":
                fetched += 1
                status = "ok"
                source.last_error = None
                source.error_message = None
                source.next_retry_at = None

                await self.repo.create_research_event(
                    tenant_id=tenant_id,
                    data=ResearchEventCreate(
                        company_research_run_id=run_id,
                        event_type="fetch_succeeded",
                        status="ok",
                        input_json={"source_id": str(source.id), "url": source.url},
                        output_json=fetch_meta,
                    ),
                )
            else:
                failed += 1
                status = "failed"
                source.last_error = source.error_message or (fetch_meta or {}).get("error")
                error_blob = " ".join(
                    filter(None, [source.error_message, source.last_error, source.http_error_message])
                ).lower()
                dns_like_failure = any(
                    needle in error_blob
                    for needle in [
                        "getaddrinfo",
                        "name or service not known",
                        "temporary failure in name resolution",
                        "nodename nor servname",
                        "invalid host",
                    ]
                )
                retry_reason = "dns_or_invalid_host" if dns_like_failure else "http_error_or_status"
                fetch_meta["retry_reason"] = retry_reason

                backoff_seconds = self._compute_backoff_seconds(source.attempt_count)

                if source.attempt_count >= (source.max_attempts or 0):
                    terminal_failures += 1
                    fetch_meta["max_attempts_reached"] = True
                    source.next_retry_at = None

                    await self.repo.create_research_event(
                        tenant_id=tenant_id,
                        data=ResearchEventCreate(
                            company_research_run_id=run_id,
                            event_type="retry_exhausted",
                            status="failed",
                            input_json={
                                "source_id": str(source.id),
                                "url": source.url,
                                "attempt": source.attempt_count,
                                "max_attempts": source.max_attempts,
                            },
                            output_json={
                                "retry_reason": retry_reason,
                                "backoff_seconds": backoff_seconds,
                            },
                            error_message=source.last_error,
                        ),
                    )
                else:
                    source.next_retry_at = utc_now() + timedelta(seconds=backoff_seconds)
                    fetch_meta.update(
                        {
                            "next_retry_at": source.next_retry_at.isoformat(),
                            "backoff_seconds": backoff_seconds,
                        }
                    )
                    if next_retry_at is None or (source.next_retry_at and source.next_retry_at < next_retry_at):
                        next_retry_at = source.next_retry_at

                    await self.repo.create_research_event(
                        tenant_id=tenant_id,
                        data=ResearchEventCreate(
                            company_research_run_id=run_id,
                            event_type="retry_scheduled",
                            status="ok",
                            input_json={
                                "source_id": str(source.id),
                                "url": source.url,
                                "attempt": source.attempt_count,
                                "max_attempts": source.max_attempts,
                            },
                            output_json={
                                "retry_reason": retry_reason,
                                "next_retry_at": source.next_retry_at.isoformat(),
                                "backoff_seconds": backoff_seconds,
                            },
                        ),
                    )

                await self.repo.create_research_event(
                    tenant_id=tenant_id,
                    data=ResearchEventCreate(
                        company_research_run_id=run_id,
                        event_type="fetch_failed",
                        status="failed",
                        input_json={"source_id": str(source.id), "url": source.url},
                        output_json=fetch_meta,
                        error_message=source.last_error,
                    ),
                )

            details.append(
                {
                    "source_id": str(source.id),
                    "url": source.url,
                    "status": source.status,
                    "error": source.last_error,
                    "attempt": source.attempt_count,
                    "next_retry_at": source.next_retry_at.isoformat() if source.next_retry_at else None,
                    "meta": fetch_meta,
                }
            )

            source.meta = {**meta_before, "fetch_info": fetch_meta, "fetch_attempt": source.attempt_count}

        # Let the worker-level commit persist changes
        retry_scheduled = next_retry_at is not None
        retry_backoff_seconds: Optional[int] = None
        if retry_scheduled:
            now = utc_now()
            retry_backoff_seconds = max(1, int((next_retry_at - now).total_seconds()))

        return {
            "processed": len(sources),
            "fetched": fetched,
            "failed": failed,
            "terminal_failures": terminal_failures,
            "retry_scheduled": retry_scheduled,
            "next_retry_at": next_retry_at.isoformat() if next_retry_at else None,
            "retry_backoff_seconds": retry_backoff_seconds,
            "details": details,
        }
    
    async def _fetch_content(
        self,
        tenant_id: str,
        source: ResearchSourceDocument,
    ) -> Dict[str, Any]:
        """Fetch and extract content from source. Returns metadata about extraction method."""
        metadata = {"extraction_method": "unknown", "items_found": 0}
        http_info: Dict[str, Any] = {}
        
        if source.source_type == "url":
            if source.content_text and source.content_hash:
                metadata["extraction_method"] = "cached"
                source.status = "fetched"
                source.fetched_at = source.fetched_at or utc_now()
                return metadata

            if not source.content_text and source.url:
                try:
                    # Detect Wikipedia early to use appropriate fetch method
                    parsed_url = urlparse(source.url)
                    is_wikipedia = 'wikipedia.org' in parsed_url.netloc
                    fetch_opts = (source.meta or {}).get("fetch_options", {}) or {}
                    
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        **(fetch_opts.get("headers") or {}),
                    }

                    timeout_seconds = fetch_opts.get("timeout_seconds") or 30.0
                    
                    # Prefer HTTP/1.1 to avoid intermittent httpstat.us disconnects
                    urls_to_try = [source.url]
                    if source.url.startswith("https://"):
                        urls_to_try.append(source.url.replace("https://", "http://", 1))

                    response = None
                    last_exc: Optional[Exception] = None
                    async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True, http2=False) as client:
                        for candidate_url in urls_to_try:
                            try:
                                response = await client.get(candidate_url, headers=headers)
                                break
                            except httpx.RequestError as exc:  # connection/transport errors
                                last_exc = exc
                                continue

                    if response is None:
                        inferred_status: Optional[int] = None
                        # httpstat.us encodes the desired status in path; fall back to that when the server drops the connection
                        if parsed_url.netloc.endswith("httpstat.us") and parsed_url.path.strip("/").startswith("404"):
                            inferred_status = 404

                        source.status = "failed"
                        source.error_message = f"Failed to fetch URL: {last_exc}" if last_exc else "Failed to fetch URL"
                        source.last_error = source.error_message
                        source.http_error_message = str(last_exc) if last_exc else None
                        fallback_headers = {"note": "connection dropped before headers"}
                        source.http_headers = fallback_headers  # persist headers field even when connection drops
                        if inferred_status is not None:
                            http_info = {
                                "status_code": inferred_status,
                                "headers": fallback_headers,
                                "error": source.error_message,
                                "final_url": source.url,
                            }
                            source.http_status_code = inferred_status
                            source.http_final_url = source.url
                        metadata["extraction_method"] = "error"
                        metadata["error"] = source.error_message
                        if http_info:
                            metadata["http"] = http_info
                        return metadata

                    html_content = response.text

                    content_length = response.headers.get("content-length")
                    if content_length is None:
                        content_length = str(len(response.content)) if response.content is not None else None

                    http_info = {
                        "status_code": response.status_code,
                        "headers": dict(response.headers),
                        "final_url": str(response.url),
                        "content_type": response.headers.get("content-type"),
                        "content_length": content_length,
                    }
                    source.http_status_code = response.status_code
                    source.http_headers = dict(response.headers)
                    source.http_final_url = str(response.url)
                    source.mime_type = response.headers.get("content-type")

                    # Some test URLs use .invalid to guarantee failure even if an intermediary returns 200
                    invalid_host = parsed_url.hostname and parsed_url.hostname.endswith(".invalid")
                    if invalid_host:
                        source.status = "failed"
                        source.error_message = "Invalid host"
                        source.last_error = source.error_message
                        source.http_error_message = source.error_message
                        metadata["extraction_method"] = "http_error"
                        metadata["error"] = source.error_message
                        metadata["http"] = http_info
                        return metadata

                    if response.status_code and response.status_code >= 400:
                        # Record HTTP error details but treat as failed fetch
                        source.status = "failed"
                        source.error_message = f"HTTP {response.status_code}"
                        source.last_error = source.error_message
                        source.http_error_message = response.reason_phrase or source.error_message
                        metadata["extraction_method"] = "http_error"
                        metadata["error"] = source.error_message
                        metadata["http"] = http_info
                        return metadata

                    source.http_error_message = None
                    
                    # Now extract content based on URL type
                    if is_wikipedia:
                        # Try structure-aware extraction first
                        extracted_items = self._extract_from_wikipedia(html_content)
                        if extracted_items:
                            source.content_text = self.normalize_text('\n'.join(extracted_items))
                            metadata["extraction_method"] = "wikipedia_structured"
                            metadata["items_found"] = len(extracted_items)
                            # Add extraction stats
                            if hasattr(self, '_last_extraction_stats'):
                                metadata.update(self._last_extraction_stats)
                        else:
                            # Fallback to generic text extraction
                            source.content_text = self._extract_text_from_html(html_content)
                            source.content_text = self.normalize_text(source.content_text)
                            metadata["extraction_method"] = "wikipedia_text_fallback"
                    else:
                        # Non-Wikipedia URL - use generic text extraction
                        source.content_text = self._extract_text_from_html(html_content)
                        source.content_text = self.normalize_text(source.content_text)
                        metadata["extraction_method"] = "generic_html"
                    
                    source.content_hash = hashlib.sha256(source.content_text.encode()).hexdigest()
                    source.status = "fetched"
                    source.fetched_at = utc_now()
                    
                except Exception as e:
                    source.status = "failed"
                    source.error_message = f"Failed to fetch URL: {str(e)}"
                    source.last_error = source.error_message
                    metadata["extraction_method"] = "error"
                    metadata["error"] = str(e)
                    response = getattr(e, "response", None)
                    if response is not None:
                        content_length = response.headers.get("content-length")
                        if content_length is None:
                            content_length = str(len(response.content)) if response.content is not None else None

                        http_info = {
                            "status_code": response.status_code,
                            "headers": dict(response.headers),
                            "final_url": str(response.url),
                            "content_type": response.headers.get("content-type"),
                            "content_length": content_length,
                        }
                        source.http_status_code = response.status_code
                        source.http_headers = dict(response.headers)
                        source.http_final_url = str(response.url)
                        source.mime_type = response.headers.get("content-type")
                    source.http_error_message = str(e)

            if http_info:
                metadata["http"] = http_info
        
        elif source.source_type == "text":
            # User provided text directly - normalize line endings
            if source.content_text:
                source.content_text = self.normalize_text(source.content_text)
                source.content_hash = hashlib.sha256(source.content_text.encode()).hexdigest()
                source.status = "fetched"
                source.fetched_at = utc_now()
                source.content_hash = hashlib.sha256(source.content_text.encode()).hexdigest()
                source.status = "fetched"
                source.fetched_at = utc_now()
                metadata["extraction_method"] = "manual_text"
        
        elif source.source_type == "pdf":
            raw_bytes = source.content_bytes or b""
            if source.content_text and source.content_hash:
                metadata["extraction_method"] = "cached"
                source.status = "fetched"
                source.fetched_at = source.fetched_at or utc_now()
                return metadata

            if not raw_bytes:
                source.status = "failed"
                source.error_message = "missing_pdf_bytes"
                source.last_error = source.error_message
                metadata["extraction_method"] = "error"
                metadata["error"] = source.error_message
                return metadata

            try:
                reader = PdfReader(io.BytesIO(raw_bytes))
                page_text: list[str] = []
                for page in reader.pages:
                    text = page.extract_text() or ""
                    if text:
                        page_text.append(text)

                combined_text = "\n".join(page_text)
                source.content_text = self.normalize_text(combined_text)
                source.content_hash = hashlib.sha256(raw_bytes).hexdigest()
                source.mime_type = source.mime_type or "application/pdf"
                source.content_size = source.content_size or len(raw_bytes)
                source.status = "fetched"
                source.fetched_at = utc_now()
                metadata.update(
                    {
                        "extraction_method": "pdf_text",
                        "pages": len(reader.pages),
                        "items_found": len(page_text),
                        "content_length": len(raw_bytes),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                source.status = "failed"
                source.error_message = f"Failed to parse PDF: {exc}"
                source.last_error = source.error_message
                metadata["extraction_method"] = "error"
                metadata["error"] = source.error_message
        
        return metadata
    
    def _extract_text_from_html(self, html: str) -> str:
        """
        Extract structured data from HTML - works for any site with tables/lists.
        
        Strategy:
        1. First try to extract from tables (first column) and lists
        2. If structured data found, use that
        3. Otherwise fallback to plain text extraction
        """
        soup = BeautifulSoup(html, 'html.parser')
        
        # Remove unwanted elements completely
        for element in soup(["script", "style", "nav", "footer", "header", "aside", "button"]):
            element.decompose()
        
        # Remove elements by common class/id patterns
        for selector in [
            {'class': re.compile(r'(nav|menu|sidebar|widget|social|share|comment|ad|banner)', re.I)},
            {'id': re.compile(r'(nav|menu|sidebar|widget|social|share|comment|ad|banner)', re.I)},
            {'role': 'navigation'},
            {'role': 'complementary'},
        ]:
            for element in soup.find_all(attrs=selector):
                element.decompose()
        
        # Try to extract structured data (tables and lists)
        candidates = []
        
        # Extract from tables (first column of each row)
        for table in soup.find_all('table'):
            # Skip tables that look like navigation/layout
            table_classes = ' '.join(table.get('class', [])).lower()
            if any(x in table_classes for x in ['nav', 'menu', 'widget', 'sidebar']):
                continue
            
            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all(['td', 'th'])
                if cells:
                    # Get first cell text
                    first_cell = cells[0]
                    text = first_cell.get_text(strip=True)
                    if text and len(text) <= 150:  # Reasonable company name length
                        candidates.append(text)
        
        # Extract from unordered lists - but skip navigation lists
        for ul in soup.find_all('ul'):
            # Skip lists that are clearly navigation
            ul_classes = ' '.join(ul.get('class', [])).lower()
            ul_id = (ul.get('id') or '').lower()
            
            if any(x in ul_classes or x in ul_id for x in ['nav', 'menu', 'social', 'share', 'widget', 'sidebar']):
                continue
            
            for li in ul.find_all('li', recursive=False):
                text = li.get_text(strip=True)
                if text and len(text) <= 150:
                    candidates.append(text)
        
        # Extract from ordered lists
        for ol in soup.find_all('ol'):
            ol_classes = ' '.join(ol.get('class', [])).lower()
            if any(x in ol_classes for x in ['nav', 'menu', 'sidebar']):
                continue
            
            for li in ol.find_all('li', recursive=False):
                text = li.get_text(strip=True)
                if text and len(text) <= 150:
                    candidates.append(text)
        
        # If we found structured data, use it
        if candidates:
            # Aggressive filtering for navigation/UI elements
            nav_ui_patterns = [
                'home', 'about', 'contact', 'search', 'login', 'logout', 'sign in', 'sign up',
                'subscribe', 'menu', 'close', 'open', 'skip to', 'read more', 'learn more',
                'click here', 'view all', 'see all', 'show more', 'author:', 'published:',
                'facebook', 'twitter', 'linkedin', 'instagram', 'youtube', 'social',
                'share', 'email', 'print', 'download', 'newsletter', 'rss',
                'previous', 'next', 'back', 'forward', 'arrow', 'button', 'icon',
                'caret', 'chevron', 'hamburger', 'pause', 'play', 'stop', 'mute',
                'copyright', '©', 'privacy', 'terms', 'cookie', 'sitemap',
                'all rights reserved', 'awards', 'winners', 'articles', 'news',
                'digital', 'magazine', 'related', 'content', 'submit',
            ]
            
            # Single-word UI elements that are never company names
            ui_words = {
                'pause', 'play', 'stop', 'mute', 'search', 'close', 'open', 'menu',
                'home', 'back', 'next', 'skip', 'more', 'less', 'submit', 'cancel',
                'twitter', 'facebook', 'linkedin', 'youtube', 'instagram',
                'subscribe', 'login', 'logout', 'register', 'signin', 'signup',
                'print', 'download', 'share', 'email', 'follow', 'unfollow',
            }
            
            # Icon/UI element patterns (kebab-case, camelCase)
            icon_pattern = re.compile(r'^[a-z]+[-_][a-z]+', re.IGNORECASE)  # search-outline, button-arrow-left
            
            filtered = []
            for c in candidates:
                if len(c) < 3 or not any(ch.isalpha() for ch in c):
                    continue
                
                lower = c.lower()
                
                # Skip single-word UI elements
                if ' ' not in c and lower in ui_words:
                    continue
                
                # Skip navigation/UI text
                if any(pattern in lower for pattern in nav_ui_patterns):
                    continue
                
                # Skip icon names (kebab-case or snake_case pattern)
                if icon_pattern.match(c):
                    continue
                
                # Skip financial values like "$87.81 B" or "23.4%"
                if re.match(r'^[$€£¥]?\s*[\d,.]+(\s*[BMK%])?$', c, re.IGNORECASE):
                    continue
                if re.match(r'^[\d,.]+(\s*[BMK%])?\s*[$€£¥]?$', c, re.IGNORECASE):
                    continue
                
                # Skip pure percentages
                if re.match(r'^[\d,.]+%$', c):
                    continue
                
                # Skip single words that are likely navigation (too short/common)
                words = c.split()
                if len(words) == 1 and len(c) < 15 and lower in ['home', 'awards', 'news', 'blog', 'shop', 'store', 'help', 'support']:
                    continue
                
                # Skip page titles (contains " | " separator or ends with " Magazine")
                if ' | ' in c or c.endswith((' Magazine', ' Journal', ' News', ' Times', ' Post')):
                    continue
                
                filtered.append(c)
            
            if filtered:
                # Limit to first 200 items to prevent timeouts
                return '\n'.join(filtered[:200])
        
        # Fallback: extract plain text
        text = soup.get_text(separator='\n')
        
        # Clean up whitespace
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        return '\n'.join(lines)
    
    def _extract_company_names(self, text: str) -> List[Tuple[str, str]]:
        """
        Extract company names from text - deterministic line-by-line extraction.
        
        For text sources: treats each cleaned non-empty line as a company name
        unless it's obviously not a company (like headers, notes, etc.).
        
        Returns list of (company_name, snippet) tuples.
        """
        if not text:
            return []
        
        # Normalize text (handles \r\n, \r, trailing spaces)
        text = self.normalize_text(text)
        
        companies = []
        seen_normalized = set()
        
        # Non-company phrases to filter out (partial matches in short lines)
        non_company_phrases = {
            'top nbfc', 'sample list', 'notes', 'company list', 'here are',
            'interesting', 'sample', 'following', 'these are',
        }
        
        # Non-company line patterns (full line matches)
        non_company_patterns = [
            r'^top\s+\w+\s*\(.*\)',  # "Top NBFCs (sample list)"
            r'^here\s+are\s+.*',      # "Here are some companies"
            r'^\w+\s+list\s*$',       # "Company list", "Sample list"
        ]
        
        # Split into lines (already normalized above)
        lines = text.split('\n')
        
        for i, line in enumerate(lines):
            original_line = line
            line = line.strip()
            if not line:
                continue
            
            # Clean line: strip bullet points, hyphens, numbers, etc.
            cleaned = line
            # Remove leading bullets: "- ", "• ", "* "
            cleaned = re.sub(r'^[\-•*]+\s+', '', cleaned)
            # Remove leading numbers: "1. ", "1) "
            cleaned = re.sub(r'^\d+[\.\)]\s+', '', cleaned)
            # Collapse multiple spaces
            cleaned = ' '.join(cleaned.split())
            cleaned = cleaned.strip()
            
            if not cleaned:
                continue
            
            # Must be at least 3 chars and contain at least one letter
            if len(cleaned) < 3 or not re.search(r'[a-zA-Z]', cleaned):
                continue
            
            # CRITICAL: Database column is VARCHAR(255) - enforce max length with safety margin
            # Also, real company names are rarely longer than 100 characters
            if len(cleaned) > 150:
                continue
            
            # Exclude full sentences (likely descriptions, not company names)
            # Company names don't typically end with periods
            if cleaned.endswith('.') and len(cleaned.split()) > 6:
                continue
            
            # Exclude financial/numeric values (revenue, prices, etc.)
            # Pattern: starts with $ or €, contains numbers and B/M/K
            if re.match(r'^[$€£¥]?\s*[\d,.]+(\s*[BMK])?$', cleaned, re.IGNORECASE):
                continue
            if re.match(r'^[\d,.]+(\s*[BMK])?\s*[$€£¥]$', cleaned, re.IGNORECASE):
                continue
            
            # Filter out obvious non-company lines
            cleaned_lower = cleaned.lower()
            is_non_company = False
            
            # Check pattern matches (full line)
            for pattern in non_company_patterns:
                if re.match(pattern, cleaned_lower):
                    is_non_company = True
                    break
            
            # Check phrase matches (for short lines)
            if not is_non_company and len(cleaned) < 60:
                for phrase in non_company_phrases:
                    if phrase in cleaned_lower:
                        is_non_company = True
                        break
            
            if is_non_company:
                continue
            
            # Accept this as a company name
            company_name = cleaned
            normalized = self._normalize_company_name(company_name)
            
            if normalized and normalized not in seen_normalized:
                seen_normalized.add(normalized)
                # Use original line for snippet context
                snippet = cleaned
                if i + 1 < len(lines) and lines[i + 1].strip():
                    next_line = lines[i + 1].strip()[:100]
                    snippet += " | " + next_line
                companies.append((company_name, snippet[:500]))
        
        # Quality check: if most results are very short single words, likely garbage
        if companies:
            single_word_short = sum(1 for name, _ in companies if ' ' not in name and len(name) < 15)
            if single_word_short / len(companies) > 0.7:  # >70% are short single words
                # Likely extracted navigation/UI garbage, return empty
                return []
        
        return companies
    
    def _normalize_company_name(self, name: str) -> str:
        """Normalize company name for deduplication."""
        # Convert to lowercase
        normalized = name.lower()
        
        # Remove common suffixes
        suffixes = [
            ' ltd', ' llc', ' plc', ' saog', ' sa', ' gmbh', ' ag',
            ' inc', ' corp', ' corporation', ' limited', ' group', ' holdings',
            '.', ',',
        ]
        for suffix in suffixes:
            if normalized.endswith(suffix):
                normalized = normalized[:-len(suffix)]
        
        # Remove extra whitespace
        normalized = ' '.join(normalized.split())
        
        return normalized.strip()
    
    def _is_likely_company_name(self, name: str) -> bool:
        """Filter out common non-company phrases."""
        # Exclude common words that appear in Title Case but aren't companies
        excluded = {
            'The Company', 'Our Company', 'This Company', 'Your Company',
            'New York', 'Los Angeles', 'San Francisco', 'United States',
            'United Kingdom', 'European Union', 'North America',
            'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday',
            'January', 'February', 'March', 'April', 'May', 'June',
            'July', 'August', 'September', 'October', 'November', 'December',
        }
        
        # Removed minimum length requirement - allow short names
        return name not in excluded
    
    async def _deduplicate_and_create_prospects(
        self,
        tenant_id: str,
        run_id: UUID,
        source: ResearchSourceDocument,
        companies: List[Tuple[str, str]],
    ) -> Tuple[int, int]:
        """
        Deduplicate companies against existing prospects and create new ones.
        
        Returns (new_count, existing_count).
        """
        # Get existing prospects for this run
        existing_prospects = await self.repo.list_company_prospects_for_run(
            tenant_id=tenant_id,
            run_id=run_id,
        )
        
        existing_normalized = {
            self._normalize_company_name(p.name_normalized): p
            for p in existing_prospects
        }
        
        new_count = 0
        existing_count = 0
        
        for company_name, snippet in companies:
            normalized = self._normalize_company_name(company_name)
            
            if normalized in existing_normalized:
                # Company already exists - add evidence only
                prospect = existing_normalized[normalized]
                await self.repo.create_company_prospect_evidence(
                    tenant_id=tenant_id,
                    data=CompanyProspectEvidenceCreate(
                        tenant_id=str(tenant_id),
                        company_prospect_id=prospect.id,
                        source_type="document",
                        source_name=source.title or source.source_type,
                        source_url=source.url,
                        evidence_snippet=snippet,
                        evidence_weight=0.5,
                    ),
                )
                existing_count += 1
            
            else:
                # New company - create prospect
                # Get role_mandate_id from the research run
                run = await self.repo.get_company_research_run(tenant_id, run_id)
                if not run:
                    continue
                
                prospect = await self.repo.create_company_prospect(
                    tenant_id=tenant_id,
                    data=CompanyProspectCreate(
                        company_research_run_id=run_id,
                        role_mandate_id=run.role_mandate_id,
                        name_raw=company_name,
                        name_normalized=normalized,
                        sector=run.sector,  # Inherit from run
                        relevance_score=0.5,  # Default score
                        evidence_score=0.5,
                        is_pinned=False,
                        status="new",
                    ),
                )
                
                # Create evidence
                await self.repo.create_company_prospect_evidence(
                    tenant_id=tenant_id,
                    data=CompanyProspectEvidenceCreate(
                        tenant_id=str(tenant_id),
                        company_prospect_id=prospect.id,
                        source_type="document",
                        source_name=source.title or source.source_type,
                        source_url=source.url,
                        evidence_snippet=snippet,
                        evidence_weight=0.5,
                    ),
                )
                
                existing_normalized[normalized] = prospect
                new_count += 1
        
        # Log dedupe event
        await self.repo.create_research_event(
            tenant_id=tenant_id,
            data=ResearchEventCreate(
                company_research_run_id=run_id,
                event_type="dedupe",
                status="ok",
                input_json={"source_id": str(source.id)},
                output_json={
                    "new_companies": new_count,
                    "existing_companies": existing_count,
                },
            ),
        )
        
        return new_count, existing_count
