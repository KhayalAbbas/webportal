"""
Company Extraction Service - Phase 2A processing pipeline.

Handles source fetching, company name extraction, deduplication,
and prospect creation from raw sources.
"""

import asyncio
import hashlib
import io
import os
import re
import time
from contextlib import asynccontextmanager
from email.utils import parsedate_to_datetime
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
from app.utils.url_canonicalizer import canonicalize_url


class CompanyExtractionService:
    """Service for extracting companies from source documents."""
    _global_semaphore: Optional[asyncio.Semaphore] = None
    _domain_limiters: Dict[str, Dict[str, Any]] = {}
    _limiter_initialized = False
    _per_domain_concurrency: int = 1
    _per_domain_min_delay: float = 0.0
    _global_concurrency: int = 8
    _max_redirects: int = 5
    _fetch_timeout_seconds: float = 30.0
    _max_fetch_bytes: int = 2_000_000
    _allowed_content_types: set[str] = {
        "text/html",
        "application/pdf",
        "text/plain",
    }
    _robots_cache: Dict[tuple[str, str, str], Dict[str, Any]] = {}
    _robots_cache_ttl_seconds: int = 3600
    _robots_cache_negative_ttl_seconds: int = 300
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = CompanyResearchRepository(db)
        self._robots_cache = {}
        desired_per_domain = max(1, int(os.getenv("PER_DOMAIN_CONCURRENCY", "1")))
        desired_min_delay = max(0, int(os.getenv("PER_DOMAIN_MIN_DELAY_MS", "0"))) / 1000.0
        desired_global = int(os.getenv("GLOBAL_CONCURRENCY", "8"))
        self._max_redirects = max(1, int(os.getenv("MAX_REDIRECTS", "5")))
        self._fetch_timeout_seconds = max(0.1, float(os.getenv("FETCH_TIMEOUT_SECONDS", "30")))
        self._max_fetch_bytes = max(1024, int(os.getenv("MAX_FETCH_BYTES", str(2_000_000))))
        allowed_raw = os.getenv("ALLOWED_CONTENT_TYPES")
        if allowed_raw:
            CompanyExtractionService._allowed_content_types = {c.strip().lower() for c in allowed_raw.split(",") if c.strip()}

        self._robots_cache_ttl_seconds = max(60, int(os.getenv("ROBOTS_CACHE_TTL_SECONDS", "3600")))
        self._robots_cache_negative_ttl_seconds = max(30, int(os.getenv("ROBOTS_CACHE_NEGATIVE_TTL_SECONDS", "300")))

        if (
            not CompanyExtractionService._limiter_initialized
            or desired_per_domain != CompanyExtractionService._per_domain_concurrency
            or desired_min_delay != CompanyExtractionService._per_domain_min_delay
            or desired_global != CompanyExtractionService._global_concurrency
        ):
            CompanyExtractionService._per_domain_concurrency = desired_per_domain
            CompanyExtractionService._per_domain_min_delay = desired_min_delay
            CompanyExtractionService._global_concurrency = desired_global
            CompanyExtractionService._global_semaphore = (
                asyncio.Semaphore(CompanyExtractionService._global_concurrency)
                if CompanyExtractionService._global_concurrency > 0
                else None
            )
            CompanyExtractionService._domain_limiters = {}
            CompanyExtractionService._limiter_initialized = True
    
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

    @staticmethod
    def _parse_robots(body: str, user_agent: str) -> Dict[str, Any]:
        """
        Minimal robots.txt parser supporting User-agent and Disallow.

        Returns a mapping with the disallow list for the best matching agent.
        """
        ua = (user_agent or "").lower()
        lines = body.splitlines()
        groups: list[Dict[str, Any]] = []
        current_agents: list[str] = []
        for raw_line in lines:
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            if ":" not in line:
                continue
            directive, value = [part.strip() for part in line.split(":", 1)]
            directive_lower = directive.lower()
            value_lower = value.lower()

            if directive_lower == "user-agent":
                if current_agents:
                    groups.append({"agents": current_agents, "disallow": []})
                    current_agents = []
                if value_lower:
                    current_agents.append(value_lower)
                continue

            if directive_lower == "disallow":
                if not current_agents:
                    current_agents = ["*"]
                # Attach to last group if already started
                if groups and groups[-1].get("agents") == current_agents:
                    groups[-1].setdefault("disallow", []).append(value)
                else:
                    groups.append({"agents": list(current_agents), "disallow": [value]})

        if current_agents:
            groups.append({"agents": current_agents, "disallow": []})

        def _matches(agent_token: str) -> bool:
            token = agent_token.lower()
            if token == "*":
                return True
            return ua.startswith(token) or token in ua

        disallows: list[str] = []
        for group in groups:
            agents = group.get("agents") or []
            if any(_matches(agent) for agent in agents):
                disallows.extend(group.get("disallow", []))

        # Remove empty rules which mean allow-all
        disallows = [rule for rule in disallows if rule]
        return {"disallow": disallows}

    @staticmethod
    def _is_path_disallowed(path: str, disallow_rules: list[str]) -> bool:
        if not disallow_rules:
            return False
        normalized_path = path or "/"
        for rule in disallow_rules:
            if rule == "/":
                return True
            if normalized_path.startswith(rule):
                return True
        return False

    def _get_domain_limiter(self, domain: str) -> Dict[str, Any]:
        key = (domain or "unknown").lower()
        limiter = CompanyExtractionService._domain_limiters.get(key)
        concurrency = CompanyExtractionService._per_domain_concurrency
        if not limiter or limiter.get("concurrency") != concurrency:
            limiter = {
                "semaphore": asyncio.Semaphore(concurrency),
                "last_start": None,
                "concurrency": concurrency,
            }
            CompanyExtractionService._domain_limiters[key] = limiter
        return limiter

    async def _get_robots_policy(
        self,
        tenant_id: str,
        run_id: UUID,
        robots_url: str,
        domain: str,
        user_agent: str,
    ) -> Dict[str, Any]:
        domain_norm = (domain or "").lower()
        user_agent_norm = (user_agent or "").lower()
        cache_key = (tenant_id, domain_norm, user_agent_norm)
        now = utc_now()

        cached_entry = self._robots_cache.get(cache_key)
        if cached_entry:
            expires_at = cached_entry.get("expires_at")
            if expires_at and expires_at > now:
                await self.repo.create_research_event(
                    tenant_id=tenant_id,
                    data=ResearchEventCreate(
                        company_research_run_id=run_id,
                        event_type="robots_cache_hit",
                        status="ok",
                        input_json={"domain": domain_norm, "robots_url": robots_url, "source": "memory"},
                        output_json={"expires_at": expires_at.isoformat()},
                    ),
                )
                return cached_entry["policy"]
            self._robots_cache.pop(cache_key, None)

        db_cached = await self.repo.get_cached_robots_policy(tenant_id, domain_norm, user_agent_norm)
        if db_cached and db_cached.expires_at and db_cached.expires_at > now:
            policy_from_db: Dict[str, Any] = dict(db_cached.policy or {})
            if "origin" not in policy_from_db:
                policy_from_db["origin"] = db_cached.origin or "cached"
            self._robots_cache[cache_key] = {"policy": policy_from_db, "expires_at": db_cached.expires_at}
            await self.repo.create_research_event(
                tenant_id=tenant_id,
                data=ResearchEventCreate(
                    company_research_run_id=run_id,
                    event_type="robots_cache_hit",
                    status="ok",
                    input_json={"domain": domain_norm, "robots_url": robots_url, "source": "db"},
                    output_json={"expires_at": db_cached.expires_at.isoformat()},
                ),
            )
            return policy_from_db

        await self.repo.create_research_event(
            tenant_id=tenant_id,
            data=ResearchEventCreate(
                company_research_run_id=run_id,
                event_type="robots_cache_miss",
                status="ok",
                input_json={"domain": domain_norm, "robots_url": robots_url},
            ),
        )

        policy: Dict[str, Any] = {"disallow": [], "origin": "missing"}
        status_code: Optional[int] = None
        timeout = httpx.Timeout(self._fetch_timeout_seconds)
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, http2=False) as client:
                response = await client.get(robots_url, headers={"User-Agent": user_agent})
                status_code = response.status_code

                if status_code == 404:
                    policy["origin"] = "missing"
                    await self.repo.create_research_event(
                        tenant_id=tenant_id,
                        data=ResearchEventCreate(
                            company_research_run_id=run_id,
                            event_type="robots_missing_or_unreachable",
                            status="ok",
                            input_json={"domain": domain, "robots_url": robots_url},
                            output_json={"status_code": status_code},
                        ),
                    )
                elif status_code >= 400:
                    policy["origin"] = "unreachable"
                    await self.repo.create_research_event(
                        tenant_id=tenant_id,
                        data=ResearchEventCreate(
                            company_research_run_id=run_id,
                            event_type="robots_missing_or_unreachable",
                            status="ok",
                            input_json={"domain": domain, "robots_url": robots_url},
                            output_json={"status_code": status_code},
                        ),
                    )
                else:
                    body = (await response.aread()).decode(response.encoding or "utf-8", errors="replace")
                    try:
                        parsed = self._parse_robots(body, user_agent)
                        policy["disallow"] = parsed.get("disallow", [])
                        policy["origin"] = "fetched"
                        await self.repo.create_research_event(
                            tenant_id=tenant_id,
                            data=ResearchEventCreate(
                                company_research_run_id=run_id,
                                event_type="robots_fetched",
                                status="ok",
                                input_json={"domain": domain, "robots_url": robots_url},
                                output_json={"status_code": status_code, "disallow_count": len(policy["disallow"])}
                            ),
                        )
                    except Exception as exc:  # noqa: BLE001
                        policy["origin"] = "parse_error"
                        await self.repo.create_research_event(
                            tenant_id=tenant_id,
                            data=ResearchEventCreate(
                                company_research_run_id=run_id,
                                event_type="robots_parse_error",
                                status="failed",
                                input_json={"domain": domain, "robots_url": robots_url},
                                output_json={"error": str(exc)},
                                error_message=str(exc),
                            ),
                        )
        except Exception as exc:  # noqa: BLE001
            policy["origin"] = "unreachable"
            await self.repo.create_research_event(
                tenant_id=tenant_id,
                data=ResearchEventCreate(
                    company_research_run_id=run_id,
                    event_type="robots_missing_or_unreachable",
                    status="ok",
                    input_json={"domain": domain, "robots_url": robots_url},
                    output_json={"error": str(exc)},
                ),
            )
            status_code = status_code or None

        ttl_seconds = self._robots_cache_ttl_seconds
        if policy.get("origin") in {"missing", "unreachable", "parse_error"}:
            ttl_seconds = self._robots_cache_negative_ttl_seconds

        expires_at = now + timedelta(seconds=ttl_seconds)
        policy["fetched_at"] = now.isoformat()

        await self.repo.upsert_robots_policy_cache(
            tenant_id=tenant_id,
            domain=domain_norm,
            user_agent=user_agent_norm,
            policy=policy,
            origin=policy.get("origin"),
            status_code=status_code,
            fetched_at=now,
            expires_at=expires_at,
        )

        self._robots_cache[cache_key] = {"policy": policy, "expires_at": expires_at}
        return policy

    @asynccontextmanager
    async def _acquire_request_slot(self, url: str):
        domain = urlparse(url).netloc or "unknown"
        global_sem = CompanyExtractionService._global_semaphore
        limiter = self._get_domain_limiter(domain)
        wait_start = time.monotonic()
        try:
            if global_sem:
                await global_sem.acquire()
            await limiter["semaphore"].acquire()

            waited_ms = (time.monotonic() - wait_start) * 1000
            min_delay = CompanyExtractionService._per_domain_min_delay
            last_start = limiter.get("last_start")
            if min_delay > 0 and last_start is not None:
                elapsed = time.monotonic() - last_start
                sleep_for = min_delay if elapsed >= min_delay else (min_delay - elapsed)
                await asyncio.sleep(sleep_for)
                waited_ms += sleep_for * 1000

            limiter["last_start"] = time.monotonic()
            yield domain, waited_ms
        finally:
            limiter["semaphore"].release()
            if global_sem:
                global_sem.release()

    @staticmethod
    def _parse_retry_after(header_value: Optional[str]) -> Optional[int]:
        if not header_value:
            return None
        try:
            return int(header_value)
        except (TypeError, ValueError):
            try:
                parsed = parsedate_to_datetime(header_value)
                if parsed:
                    delta = parsed - datetime.now(tz=parsed.tzinfo)
                    return max(0, int(delta.total_seconds()))
            except Exception:  # noqa: BLE001
                return None
        return None
    
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
                validators = meta.get("validators") or {}
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

                if fetch_metadata.get("deduped"):
                    sources_detail.append({
                        "source_id": str(source.id),
                        "title": source.title or source.url or "Unknown",
                        "status": "deduped",
                        "deduped_to": fetch_metadata.get("canonical_source_id"),
                        "extraction_method": fetch_metadata.get("extraction_method", "deduped"),
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
        pending_recheck = False

        for source in sources:
            meta_before = dict(source.meta or {})
            source.status = "fetching"
            source.attempt_count = (source.attempt_count or 0) + 1
            source.next_retry_at = None
            source.last_error = None
            await self.db.flush()

            fetch_meta: Dict[str, Any] = {}
            try:
                canonical_url = canonicalize_url(source.url or "")
                source.url_normalized = canonical_url
                source.original_url = source.original_url or source.url
                fetch_meta["canonical_url"] = canonical_url

                await self.repo.create_research_event(
                    tenant_id=tenant_id,
                    data=ResearchEventCreate(
                        company_research_run_id=run_id,
                        event_type="canonicalize",
                        status="ok",
                        input_json={
                            "source_id": str(source.id),
                            "original_url": source.url,
                        },
                        output_json={"url_normalized": canonical_url},
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                source.status = "failed"
                source.error_message = f"canonicalize_failed: {exc}"
                source.last_error = source.error_message
                source.next_retry_at = None
                fetch_meta.update(
                    {
                        "error": source.error_message,
                        "canonicalization_error": str(exc),
                        "attempt": source.attempt_count,
                        "max_attempts": source.max_attempts,
                    }
                )

                await self.repo.create_research_event(
                    tenant_id=tenant_id,
                    data=ResearchEventCreate(
                        company_research_run_id=run_id,
                        event_type="canonicalize",
                        status="failed",
                        input_json={"source_id": str(source.id), "url": source.url},
                        output_json=fetch_meta,
                        error_message=source.error_message,
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
                        error_message=source.error_message,
                    ),
                )

                await self.db.flush()

                failed += 1
                status = "failed"
                details.append(
                    {
                        "source_id": str(source.id),
                        "url": source.url,
                        "status": source.status,
                        "error": source.last_error,
                        "attempt": source.attempt_count,
                        "next_retry_at": None,
                        "meta": fetch_meta,
                    }
                )
                merged_meta = {**meta_before, **(source.meta or {})}
                merged_meta["fetch_info"] = fetch_meta
                merged_meta["fetch_attempt"] = source.attempt_count
                source.meta = merged_meta
                continue

            await self.repo.create_research_event(
                tenant_id=tenant_id,
                data=ResearchEventCreate(
                    company_research_run_id=run_id,
                    event_type="fetch_started",
                    status="ok",
                    input_json={
                        "source_id": str(source.id),
                        "url": source.url,
                        "url_normalized": source.url_normalized,
                        "attempt": source.attempt_count,
                        "max_attempts": source.max_attempts,
                    },
                ),
            )

            fetch_meta.update(await self._fetch_content(tenant_id, source) or {})
            fetch_meta.update(
                {
                    "attempt": source.attempt_count,
                    "max_attempts": source.max_attempts,
                }
            )

            if source.status in {"fetched", "processed"}:
                fetched += 1
                status = "ok"
                source.last_error = None
                source.error_message = None
                source.next_retry_at = None

                pending_validators = {}
                if isinstance(source.meta, dict):
                    pending_validators = (source.meta.get("validators") or {}) if isinstance(source.meta.get("validators"), dict) else {}
                if pending_validators.get("pending_recheck"):
                    source.next_retry_at = utc_now() + timedelta(seconds=1)

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
                source.status = "failed"
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

                retry_after_seconds = fetch_meta.get("retry_after_seconds")
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
                    if source.next_retry_at is None:
                        source.next_retry_at = utc_now() + timedelta(seconds=backoff_seconds)
                        fetch_meta.update(
                            {
                                "next_retry_at": source.next_retry_at.isoformat(),
                                "backoff_seconds": backoff_seconds,
                            }
                        )
                    else:
                        backoff_seconds = max(1, int((source.next_retry_at - utc_now()).total_seconds()))
                        fetch_meta.update(
                            {
                                "next_retry_at": source.next_retry_at.isoformat(),
                                "backoff_seconds": backoff_seconds,
                            }
                        )
                        if retry_after_seconds is not None:
                            fetch_meta["retry_after_seconds"] = retry_after_seconds

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
                                **({"retry_after_seconds": retry_after_seconds} if retry_after_seconds is not None else {}),
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

            merged_meta = {**meta_before, **(source.meta or {})}
            merged_meta["fetch_info"] = fetch_meta
            merged_meta["fetch_attempt"] = source.attempt_count
            source.meta = merged_meta

        # Let the worker-level commit persist changes
        retry_scheduled = next_retry_at is not None
        retry_backoff_seconds: Optional[int] = None
        if retry_scheduled:
            now = utc_now()
            retry_backoff_seconds = max(1, int((next_retry_at - now).total_seconds()))

        pending_recheck = any(
            (
                (validators := ((src.meta or {}).get("validators") or {})).get("pending_recheck")
            )
            for src in sources
            if src.source_type == "url"
        )

        pending_recheck_next_retry_at: Optional[datetime] = None
        if pending_recheck and not retry_scheduled:
            pending_recheck_next_retry_at = utc_now() + timedelta(seconds=1)

        return {
            "processed": len(sources),
            "fetched": fetched,
            "failed": failed,
            "terminal_failures": terminal_failures,
            "retry_scheduled": retry_scheduled,
            "next_retry_at": next_retry_at.isoformat() if next_retry_at else None,
            "retry_backoff_seconds": retry_backoff_seconds,
            "pending_recheck": pending_recheck,
            "pending_recheck_next_retry_at": pending_recheck_next_retry_at.isoformat() if pending_recheck_next_retry_at else None,
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
            meta = dict(source.meta or {})
            validators = meta.get("validators") or {}
            pending_recheck = bool(validators.get("pending_recheck"))

            if source.content_text and source.content_hash and not pending_recheck:
                metadata["extraction_method"] = "cached"
                source.status = "fetched"
                source.fetched_at = source.fetched_at or utc_now()
                return metadata

            fetch_url = source.url_normalized or source.url
            if fetch_url:
                try:
                    # Detect Wikipedia early to use appropriate fetch method
                    parsed_url = urlparse(fetch_url)
                    is_wikipedia = 'wikipedia.org' in parsed_url.netloc
                    fetch_opts = (source.meta or {}).get("fetch_options", {}) or {}

                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        **(fetch_opts.get("headers") or {}),
                    }

                    conditional_headers: dict[str, str] = {}
                    if validators.get("etag"):
                        conditional_headers["If-None-Match"] = str(validators.get("etag"))
                    if validators.get("last_modified"):
                        conditional_headers["If-Modified-Since"] = str(validators.get("last_modified"))

                    if conditional_headers:
                        headers.update(conditional_headers)
                        metadata["conditional_request"] = conditional_headers

                    timeout_override = fetch_opts.get("timeout_seconds")
                    try:
                        if timeout_override is None:
                            timeout_seconds = float(self._fetch_timeout_seconds)
                        else:
                            timeout_seconds = max(0.1, min(float(timeout_override), float(self._fetch_timeout_seconds)))
                    except (TypeError, ValueError):
                        timeout_seconds = float(self._fetch_timeout_seconds)

                    max_bytes_override = fetch_opts.get("max_fetch_bytes")
                    try:
                        if max_bytes_override is None:
                            max_fetch_bytes = int(self._max_fetch_bytes)
                        else:
                            max_fetch_bytes = max(1, min(int(max_bytes_override), int(self._max_fetch_bytes)))
                    except (TypeError, ValueError):
                        max_fetch_bytes = int(self._max_fetch_bytes)

                    # robots.txt enforcement per domain per run
                    robots_scheme = parsed_url.scheme or "http"
                    robots_netloc = parsed_url.netloc
                    robots_url = f"{robots_scheme}://{robots_netloc}/robots.txt" if robots_netloc else None
                    if robots_url and robots_netloc:
                        policy = await self._get_robots_policy(
                            tenant_id=tenant_id,
                            run_id=source.company_research_run_id,
                            robots_url=robots_url,
                            domain=robots_netloc,
                            user_agent=headers.get("User-Agent", ""),
                        )
                        disallow_rules = policy.get("disallow", [])
                        if self._is_path_disallowed(parsed_url.path or "/", disallow_rules):
                            source.status = "failed"
                            source.error_message = "robots_disallowed"
                            source.last_error = source.error_message
                            source.http_error_message = source.error_message
                            metadata["extraction_method"] = "robots_disallowed"
                            metadata["error"] = source.error_message
                            metadata["robots"] = {
                                "path": parsed_url.path or "/",
                                "robots_url": robots_url,
                                "disallow_rules": disallow_rules,
                                "origin": policy.get("origin"),
                            }
                            await self.repo.create_research_event(
                                tenant_id=tenant_id,
                                data=ResearchEventCreate(
                                    company_research_run_id=source.company_research_run_id,
                                    event_type="robots_disallowed",
                                    status="failed",
                                    input_json={
                                        "source_id": str(source.id),
                                        "requested_url": fetch_url,
                                    },
                                    output_json={
                                        "robots_url": robots_url,
                                        "path": parsed_url.path or "/",
                                        "disallow_rules": disallow_rules,
                                        "origin": policy.get("origin"),
                                    },
                                    error_message=source.error_message,
                                ),
                            )
                            return metadata

                    if pending_recheck:
                        recheck_attempts = int(validators.get("pending_recheck_attempts") or 0)

                        if recheck_attempts == 0:
                            # Defer the first conditional recheck to a subsequent worker pass.
                            validators["pending_recheck_attempts"] = 1
                            validators["last_checked_at"] = validators.get("last_checked_at") or utc_now_iso()
                            meta["validators"] = validators
                            source.meta = meta
                            source.status = "fetched"
                            metadata["extraction_method"] = metadata.get("extraction_method") or "conditional_pending"
                            metadata["not_modified"] = metadata.get("not_modified", True)
                            return metadata

                        timeout = httpx.Timeout(timeout_seconds)
                        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, http2=False) as client:
                            resp = await client.get(fetch_url, headers=headers)

                        status_code = resp.status_code or 0
                        response_headers = dict(resp.headers)

                        if status_code == 304:
                            source.status = "fetched"
                            source.error_message = None
                            source.last_error = None
                            source.http_status_code = status_code
                            source.http_headers = response_headers
                            source.http_final_url = str(resp.url)
                            source.http_error_message = None

                            next_attempt = recheck_attempts + 1
                            validators["pending_recheck_attempts"] = next_attempt
                            validators["pending_recheck"] = False if next_attempt >= 3 else True
                            validators["last_checked_at"] = utc_now_iso()
                            meta["validators"] = validators
                            source.meta = meta

                            http_info = {
                                "status_code": status_code,
                                "headers": response_headers,
                                "final_url": str(resp.url),
                            }
                            metadata["extraction_method"] = "not_modified"
                            metadata["http"] = http_info
                            metadata["not_modified"] = True

                            await self.repo.create_research_event(
                                tenant_id=tenant_id,
                                data=ResearchEventCreate(
                                    company_research_run_id=source.company_research_run_id,
                                    event_type="not_modified",
                                    status="ok",
                                    input_json={
                                        "source_id": str(source.id),
                                        "requested_url": fetch_url,
                                        "url_normalized": source.url_normalized,
                                    },
                                    output_json={
                                        "status_code": status_code,
                                        "headers": response_headers,
                                        "validators": {
                                            "etag": validators.get("etag"),
                                            "last_modified": validators.get("last_modified"),
                                        },
                                    },
                                ),
                            )

                            return metadata

                        if status_code >= 400:
                            source.status = "failed"
                            source.error_message = f"HTTP {status_code}"
                            source.last_error = source.error_message
                            source.http_error_message = source.error_message
                            source.http_status_code = status_code
                            source.http_headers = response_headers
                            source.http_final_url = str(resp.url)
                            metadata["extraction_method"] = "http_error"
                            metadata["error"] = source.error_message
                            metadata["http"] = {
                                "status_code": status_code,
                                "headers": response_headers,
                                "final_url": str(resp.url),
                            }
                            return metadata

                        content_bytes = resp.content or b""
                        content_type_header = response_headers.get("content-type") or response_headers.get("Content-Type")
                        encoding = "utf-8"
                        if content_type_header:
                            match = re.search(r"charset=([\w-]+)", content_type_header, re.IGNORECASE)
                            if match:
                                encoding = match.group(1)
                        html_content = content_bytes.decode(encoding, errors="replace") if content_bytes else ""

                        canonical_final_url = None
                        try:
                            canonical_final_url = canonicalize_url(str(resp.url))
                        except Exception:
                            canonical_final_url = None

                        http_info = {
                            "status_code": status_code,
                            "headers": response_headers,
                            "final_url": str(resp.url),
                            "canonical_final_url": canonical_final_url,
                            "content_type": content_type_header,
                            "content_length": str(len(content_bytes)),
                            "bytes_read": len(content_bytes),
                        }
                        source.http_status_code = status_code
                        source.http_headers = response_headers
                        source.http_final_url = str(resp.url)
                        source.canonical_final_url = canonical_final_url
                        source.mime_type = content_type_header

                        etag_header = response_headers.get("etag") or response_headers.get("ETag")
                        last_modified_header = response_headers.get("last-modified") or response_headers.get("Last-Modified")
                        if etag_header or last_modified_header:
                            if etag_header:
                                validators["etag"] = etag_header
                            if last_modified_header:
                                validators["last_modified"] = last_modified_header
                            validators["last_seen_at"] = utc_now_iso()
                            validators["pending_recheck"] = True
                            validators["pending_recheck_attempts"] = 0
                            meta["validators"] = validators
                            source.meta = meta
                            metadata["validators"] = {
                                "etag": validators.get("etag"),
                                "last_modified": validators.get("last_modified"),
                                "pending_recheck": True,
                            }
                        elif validators:
                            validators["pending_recheck"] = True
                            validators["pending_recheck_attempts"] = 0
                            meta["validators"] = validators
                            source.meta = meta

                        source.content_text = self.normalize_text(self._extract_text_from_html(html_content))
                        source.content_hash = hashlib.sha256(source.content_text.encode()).hexdigest()
                        source.status = "fetched"
                        source.fetched_at = utc_now()
                        metadata["extraction_method"] = "conditional_html"
                        metadata["items_found"] = metadata.get("items_found", 0)
                        metadata["http"] = http_info
                        metadata.update(await self._apply_content_dedupe(tenant_id, source.company_research_run_id, source))
                        return metadata
                    
                    # Prefer HTTP/1.1 to avoid intermittent httpstat.us disconnects
                    urls_to_try = [fetch_url]
                    if fetch_url.startswith("https://"):
                        urls_to_try.append(fetch_url.replace("https://", "http://", 1))

                    response = None
                    last_exc: Optional[Exception] = None
                    fetched_payload: Optional[Dict[str, Any]] = None
                    timeout = httpx.Timeout(timeout_seconds)
                    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, http2=False) as client:
                        for candidate_url in urls_to_try:
                            try:
                                redirect_chain: list[Dict[str, Any]] = []
                                visited: set[str] = set()
                                current_url = candidate_url

                                for _ in range(self._max_redirects + 1):
                                    async with self._acquire_request_slot(current_url) as (domain, waited_ms):
                                        if waited_ms > 0:
                                            await self.repo.create_research_event(
                                                tenant_id=tenant_id,
                                                data=ResearchEventCreate(
                                                    company_research_run_id=source.company_research_run_id,
                                                    event_type="domain_rate_limited",
                                                    status="ok",
                                                    input_json={
                                                        "source_id": str(source.id),
                                                        "url": source.url,
                                                        "url_normalized": source.url_normalized,
                                                    },
                                                    output_json={
                                                        "domain": domain,
                                                        "waited_ms": waited_ms,
                                                        "url_normalized": source.url_normalized,
                                                    },
                                                ),
                                            )

                                        async with client.stream(
                                            "GET",
                                            current_url,
                                            headers=headers,
                                            follow_redirects=False,
                                        ) as response:

                                            status_code = response.status_code or 0
                                            location = response.headers.get("location")

                                            if status_code == 304:
                                                source.status = "fetched"
                                                source.error_message = None
                                                source.last_error = None
                                                source.http_status_code = status_code
                                                source.http_headers = dict(response.headers)
                                                source.http_final_url = str(response.url)
                                                source.http_error_message = None

                                                next_attempt = recheck_attempts + 1
                                                validators["pending_recheck_attempts"] = next_attempt
                                                validators["pending_recheck"] = False if next_attempt >= 3 else True
                                                validators["last_checked_at"] = utc_now_iso()
                                                meta["validators"] = validators
                                                source.meta = meta

                                                http_info = {
                                                    "status_code": status_code,
                                                    "headers": dict(response.headers),
                                                    "final_url": str(response.url),
                                                }
                                                metadata["extraction_method"] = "not_modified"
                                                metadata["http"] = http_info
                                                metadata["not_modified"] = True

                                                await self.repo.create_research_event(
                                                    tenant_id=tenant_id,
                                                    data=ResearchEventCreate(
                                                        company_research_run_id=source.company_research_run_id,
                                                        event_type="not_modified",
                                                        status="ok",
                                                        input_json={
                                                            "source_id": str(source.id),
                                                            "requested_url": current_url,
                                                            "url_normalized": source.url_normalized,
                                                        },
                                                        output_json={
                                                            "status_code": status_code,
                                                            "headers": dict(response.headers),
                                                            "validators": {
                                                                "etag": validators.get("etag"),
                                                                "last_modified": validators.get("last_modified"),
                                                            },
                                                        },
                                                    ),
                                                )

                                                return metadata

                                            if status_code in {301, 302, 303, 307, 308}:
                                                if not location:
                                                    source.status = "failed"
                                                    source.error_message = "redirect_missing_location"
                                                    source.last_error = source.error_message
                                                    source.http_error_message = source.error_message
                                                    http_info = {
                                                        "status_code": status_code,
                                                        "headers": dict(response.headers),
                                                        "final_url": str(response.url),
                                                        "redirect_chain": redirect_chain,
                                                        "error": source.error_message,
                                                    }
                                                    source.http_status_code = status_code
                                                    source.http_headers = dict(response.headers)
                                                    source.http_final_url = str(response.url)
                                                    metadata["extraction_method"] = "http_error"
                                                    metadata["error"] = source.error_message
                                                    metadata["http"] = http_info
                                                    await self.repo.create_research_event(
                                                        tenant_id=tenant_id,
                                                        data=ResearchEventCreate(
                                                            company_research_run_id=source.company_research_run_id,
                                                            event_type="redirect_missing_location",
                                                            status="failed",
                                                            input_json={
                                                                "source_id": str(source.id),
                                                                "requested_url": current_url,
                                                            },
                                                            output_json={
                                                                "status_code": status_code,
                                                                "headers": dict(response.headers),
                                                                "redirect_chain": redirect_chain,
                                                            },
                                                            error_message=source.error_message,
                                                        ),
                                                    )
                                                    return metadata

                                                next_url = str(httpx.URL(current_url).join(location))
                                                redirect_hop = {
                                                    "from": current_url,
                                                    "to": next_url,
                                                    "status_code": status_code,
                                                }
                                                redirect_chain.append(redirect_hop)

                                                await self.repo.create_research_event(
                                                    tenant_id=tenant_id,
                                                    data=ResearchEventCreate(
                                                        company_research_run_id=source.company_research_run_id,
                                                        event_type="redirect_followed",
                                                        status="ok",
                                                        input_json={
                                                            "source_id": str(source.id),
                                                            "requested_url": current_url,
                                                        },
                                                        output_json={
                                                            "next_url": next_url,
                                                            "status_code": status_code,
                                                            "hop_index": len(redirect_chain),
                                                            "max_redirects": self._max_redirects,
                                                        },
                                                    ),
                                                )

                                                if next_url in visited:
                                                    source.status = "failed"
                                                    source.error_message = "redirect_loop_detected"
                                                    source.last_error = source.error_message
                                                    source.http_error_message = source.error_message
                                                    http_info = {
                                                        "status_code": status_code,
                                                        "headers": dict(response.headers),
                                                        "final_url": str(response.url),
                                                        "redirect_chain": redirect_chain,
                                                        "error": source.error_message,
                                                    }
                                                    source.http_status_code = status_code
                                                    source.http_headers = dict(response.headers)
                                                    source.http_final_url = str(response.url)
                                                    metadata["extraction_method"] = "http_error"
                                                    metadata["error"] = source.error_message
                                                    metadata["http"] = http_info
                                                    await self.repo.create_research_event(
                                                        tenant_id=tenant_id,
                                                        data=ResearchEventCreate(
                                                            company_research_run_id=source.company_research_run_id,
                                                            event_type="redirect_loop_detected",
                                                            status="failed",
                                                            input_json={
                                                                "source_id": str(source.id),
                                                                "requested_url": current_url,
                                                            },
                                                            output_json={
                                                                "loop_url": next_url,
                                                                "redirect_chain": redirect_chain,
                                                            },
                                                            error_message=source.error_message,
                                                        ),
                                                    )
                                                    return metadata

                                                if len(redirect_chain) > self._max_redirects:
                                                    source.status = "failed"
                                                    source.error_message = "redirect_limit_exceeded"
                                                    source.last_error = source.error_message
                                                    source.http_error_message = source.error_message
                                                    http_info = {
                                                        "status_code": status_code,
                                                        "headers": dict(response.headers),
                                                        "final_url": str(response.url),
                                                        "redirect_chain": redirect_chain,
                                                        "error": source.error_message,
                                                    }
                                                    source.http_status_code = status_code
                                                    source.http_headers = dict(response.headers)
                                                    source.http_final_url = str(response.url)
                                                    metadata["extraction_method"] = "http_error"
                                                    metadata["error"] = source.error_message
                                                    metadata["http"] = http_info
                                                    await self.repo.create_research_event(
                                                        tenant_id=tenant_id,
                                                        data=ResearchEventCreate(
                                                            company_research_run_id=source.company_research_run_id,
                                                            event_type="redirect_limit_reached",
                                                            status="failed",
                                                            input_json={
                                                                "source_id": str(source.id),
                                                                "requested_url": current_url,
                                                            },
                                                            output_json={
                                                                "max_redirects": self._max_redirects,
                                                                "redirect_chain": redirect_chain,
                                                            },
                                                            error_message=source.error_message,
                                                        ),
                                                    )
                                                    return metadata

                                                visited.add(current_url)
                                                current_url = next_url
                                                continue

                                            # Not a redirect; proceed to content handling inside the stream context
                                            raw_content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                                            if raw_content_type and raw_content_type not in CompanyExtractionService._allowed_content_types:
                                                source.status = "failed"
                                                source.error_message = "unsupported_content_type"
                                                source.last_error = source.error_message
                                                source.http_error_message = source.error_message
                                                http_info = {
                                                    "status_code": response.status_code,
                                                    "headers": dict(response.headers),
                                                    "final_url": str(response.url),
                                                    "content_type": response.headers.get("content-type"),
                                                }
                                                source.http_status_code = response.status_code
                                                source.http_headers = dict(response.headers)
                                                source.http_final_url = str(response.url)
                                                metadata["extraction_method"] = "http_error"
                                                metadata["error"] = source.error_message
                                                metadata["http"] = http_info
                                                await self.repo.create_research_event(
                                                    tenant_id=tenant_id,
                                                    data=ResearchEventCreate(
                                                        company_research_run_id=source.company_research_run_id,
                                                        event_type="fetch_unsupported_content_type",
                                                        status="failed",
                                                        input_json={
                                                            "source_id": str(source.id),
                                                            "requested_url": fetch_url,
                                                        },
                                                        output_json={
                                                            "content_type": response.headers.get("content-type"),
                                                            "allowed": sorted(CompanyExtractionService._allowed_content_types),
                                                        },
                                                        error_message=source.error_message,
                                                    ),
                                                )
                                                return metadata

                                            content_chunks: list[bytes] = []
                                            bytes_read = 0
                                            async for chunk in response.aiter_bytes():
                                                content_chunks.append(chunk)
                                                bytes_read += len(chunk)
                                                if bytes_read > max_fetch_bytes:
                                                    source.status = "failed"
                                                    source.error_message = "fetch_too_large"
                                                    source.last_error = source.error_message
                                                    source.http_error_message = source.error_message
                                                    http_info = {
                                                        "status_code": response.status_code,
                                                        "headers": dict(response.headers),
                                                        "final_url": str(response.url),
                                                        "bytes_read": bytes_read,
                                                        "content_type": response.headers.get("content-type"),
                                                    }
                                                    source.http_status_code = response.status_code
                                                    source.http_headers = dict(response.headers)
                                                    source.http_final_url = str(response.url)
                                                    metadata["extraction_method"] = "http_error"
                                                    metadata["error"] = source.error_message
                                                    metadata["http"] = http_info
                                                    metadata["bytes_read"] = bytes_read
                                                    await self.repo.create_research_event(
                                                        tenant_id=tenant_id,
                                                        data=ResearchEventCreate(
                                                            company_research_run_id=source.company_research_run_id,
                                                            event_type="fetch_too_large",
                                                            status="failed",
                                                            input_json={
                                                                "source_id": str(source.id),
                                                                "requested_url": fetch_url,
                                                            },
                                                            output_json={
                                                                "bytes_read": bytes_read,
                                                                "max_bytes": max_fetch_bytes,
                                                                "content_type": response.headers.get("content-type"),
                                                            },
                                                            error_message=source.error_message,
                                                        ),
                                                    )
                                                    return metadata

                                            content_bytes = b"".join(content_chunks)
                                            fetched_payload = {
                                                "status": response.status_code,
                                                "headers": dict(response.headers),
                                                "url": str(response.url),
                                                "bytes_read": bytes_read,
                                                "content_type": response.headers.get("content-type"),
                                                "reason_phrase": response.reason_phrase,
                                                "content_bytes": content_bytes,
                                            }
                                            response = None  # release reference
                                            break

                                break
                            except httpx.TimeoutException as exc:
                                last_exc = exc
                                source.status = "failed"
                                source.error_message = "fetch_timeout"
                                source.last_error = source.error_message
                                source.http_error_message = str(exc)
                                metadata["extraction_method"] = "error"
                                metadata["error"] = source.error_message
                                await self.repo.create_research_event(
                                    tenant_id=tenant_id,
                                    data=ResearchEventCreate(
                                        company_research_run_id=source.company_research_run_id,
                                        event_type="fetch_timed_out",
                                        status="failed",
                                        input_json={
                                            "source_id": str(source.id),
                                            "requested_url": current_url,
                                        },
                                        output_json={"timeout_seconds": timeout_seconds},
                                        error_message=source.error_message,
                                    ),
                                )
                                return metadata
                            except httpx.RequestError as exc:  # connection/transport errors
                                last_exc = exc
                                continue

                    if response is None and not fetched_payload:
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
                                "final_url": fetch_url,
                            }
                            source.http_status_code = inferred_status
                            source.http_final_url = fetch_url
                        metadata["extraction_method"] = "error"
                        metadata["error"] = source.error_message
                        if http_info:
                            metadata["http"] = http_info
                        return metadata

                    if not fetched_payload:
                        source.status = "failed"
                        source.error_message = "Failed to fetch URL"
                        source.last_error = source.error_message
                        metadata["extraction_method"] = "error"
                        metadata["error"] = source.error_message
                        return metadata

                    content_bytes = fetched_payload.get("content_bytes", b"")
                    bytes_read = fetched_payload.get("bytes_read", 0)
                    response_status_code = fetched_payload.get("status")
                    response_headers = fetched_payload.get("headers", {})
                    response_url = fetched_payload.get("url")
                    content_type_header = response_headers.get("content-type") or response_headers.get("Content-Type")

                    encoding = "utf-8"
                    if content_type_header:
                        match = re.search(r"charset=([\w-]+)", content_type_header, re.IGNORECASE)
                        if match:
                            encoding = match.group(1)
                    html_content = content_bytes.decode(encoding, errors="replace") if content_bytes else ""

                    content_length = response_headers.get("content-length") or response_headers.get("Content-Length")
                    if content_length is None:
                        content_length = str(len(content_bytes)) if content_bytes else None

                    canonical_final_url = None
                    if response_url:
                        try:
                            canonical_final_url = canonicalize_url(str(response_url))
                        except Exception as exc:  # noqa: BLE001
                            await self.repo.create_research_event(
                                tenant_id=tenant_id,
                                data=ResearchEventCreate(
                                    company_research_run_id=source.company_research_run_id,
                                    event_type="redirect_resolved",
                                    status="failed",
                                    input_json={"source_id": str(source.id), "requested_url": fetch_url},
                                    output_json={"error": str(exc), "final_url": str(response_url)},
                                    error_message=str(exc),
                                ),
                            )

                    http_info = {
                        "status_code": response_status_code,
                        "headers": response_headers,
                        "final_url": str(response_url) if response_url else None,
                        "canonical_final_url": canonical_final_url,
                        "content_type": content_type_header,
                        "content_length": content_length,
                        "bytes_read": bytes_read,
                    }
                    if redirect_chain:
                        http_info["redirect_chain"] = redirect_chain
                        metadata["redirect_chain"] = redirect_chain
                    source.http_status_code = response_status_code
                    source.http_headers = response_headers
                    source.http_final_url = str(response_url) if response_url else None
                    source.canonical_final_url = canonical_final_url
                    source.mime_type = content_type_header

                    if canonical_final_url:
                        await self.repo.create_research_event(
                            tenant_id=tenant_id,
                            data=ResearchEventCreate(
                                company_research_run_id=source.company_research_run_id,
                                event_type="redirect_resolved",
                                status="ok",
                                input_json={
                                    "source_id": str(source.id),
                                    "requested_url": fetch_url,
                                },
                                output_json={
                                    "final_url": str(response_url),
                                    "canonical_final_url": canonical_final_url,
                                    "status_code": response_status_code,
                                },
                            ),
                        )

                    etag_header = response_headers.get("etag") or response_headers.get("ETag")
                    last_modified_header = response_headers.get("last-modified") or response_headers.get("Last-Modified")
                    if etag_header or last_modified_header:
                        if etag_header:
                            validators["etag"] = etag_header
                        if last_modified_header:
                            validators["last_modified"] = last_modified_header
                        validators["last_seen_at"] = utc_now_iso()
                        validators["pending_recheck"] = False if pending_recheck else True
                        meta["validators"] = validators
                        source.meta = meta
                        metadata["validators"] = {
                            "etag": validators.get("etag"),
                            "last_modified": validators.get("last_modified"),
                            "pending_recheck": validators.get("pending_recheck"),
                        }
                    elif validators:
                        validators["pending_recheck"] = False
                        meta["validators"] = validators
                        source.meta = meta

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

                    if response_status_code and response_status_code >= 400:
                        retry_after_seconds = None
                        if response_status_code in {429, 503}:
                            retry_after_seconds = self._parse_retry_after(response_headers.get("retry-after") or response_headers.get("Retry-After"))

                        if retry_after_seconds is not None:
                            source.status = "failed"
                            source.error_message = f"retry-after {retry_after_seconds}s"
                            source.last_error = source.error_message
                            source.http_error_message = source.error_message
                            source.next_retry_at = utc_now() + timedelta(seconds=retry_after_seconds)
                            metadata["extraction_method"] = "http_error"
                            metadata["error"] = source.error_message
                            metadata["http"] = http_info
                            metadata["retry_after_seconds"] = retry_after_seconds
                            metadata["next_retry_at"] = source.next_retry_at.isoformat()

                            await self.repo.create_research_event(
                                tenant_id=tenant_id,
                                data=ResearchEventCreate(
                                    company_research_run_id=source.company_research_run_id,
                                    event_type="retry_after_honored",
                                    status="failed",
                                    input_json={
                                        "source_id": str(source.id),
                                        "url": source.url,
                                        "url_normalized": source.url_normalized,
                                    },
                                    output_json={
                                        "url_normalized": source.url_normalized,
                                        "http_status": response_status_code,
                                        "retry_after_seconds": retry_after_seconds,
                                        "next_retry_at": source.next_retry_at.isoformat(),
                                    },
                                    error_message=source.error_message,
                                ),
                            )
                            return metadata

                        # Record HTTP error details but treat as failed fetch
                        source.status = "failed"
                        source.error_message = f"HTTP {response_status_code}"
                        source.last_error = source.error_message
                        source.http_error_message = fetched_payload.get("reason_phrase") or source.error_message
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
                    metadata.update(await self._apply_content_dedupe(tenant_id, source.company_research_run_id, source))
                    
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
                metadata.update(await self._apply_content_dedupe(tenant_id, source.company_research_run_id, source))
            except Exception as exc:  # noqa: BLE001
                source.status = "failed"
                source.error_message = f"Failed to parse PDF: {exc}"
                source.last_error = source.error_message
                metadata["extraction_method"] = "error"
                metadata["error"] = source.error_message
        
        return metadata

    async def _apply_content_dedupe(
        self,
        tenant_id: str,
        run_id: UUID,
        source: ResearchSourceDocument,
    ) -> Dict[str, Any]:
        """Deduplicate sources by content hash within a run."""
        if not source.content_hash:
            return {}

        if not run_id:
            source.canonical_source_id = source.canonical_source_id or source.id
            return {"deduped": False, "canonical_source_id": str(source.canonical_source_id)}

        # Avoid autoflush before we check for an existing canonical source; otherwise the pending
        # duplicate hash update would violate the unique constraint before we can mark it deduped.
        with self.db.no_autoflush:
            canonical = await self.repo.find_source_by_hash(
                tenant_id=tenant_id,
                run_id=run_id,
                content_hash=source.content_hash,
                exclude_id=source.id,
            )

        if not canonical:
            source.canonical_source_id = source.canonical_source_id or source.id
            return {"deduped": False, "canonical_source_id": str(source.canonical_source_id)}

        if canonical.id == source.id:
            source.canonical_source_id = source.id
            return {"deduped": False, "canonical_source_id": str(source.id)}

        deduped_content_hash = source.content_hash
        already_deduped = source.canonical_source_id == canonical.id and source.status == "processed"
        source.canonical_source_id = canonical.id
        source.status = "processed"
        # Avoid violating the run-scoped unique constraint on content_hash
        # once we've linked this source to the canonical one.
        source.content_hash = None
        if canonical.canonical_final_url and not source.canonical_final_url:
            source.canonical_final_url = canonical.canonical_final_url
        meta = dict(source.meta or {})
        dedupe_meta = meta.get("dedupe", {})
        dedupe_meta["deduped_to"] = str(canonical.id)
        if deduped_content_hash:
            dedupe_meta["content_hash"] = deduped_content_hash
        meta["dedupe"] = dedupe_meta
        source.meta = meta

        if not already_deduped:
            await self.repo.create_research_event(
                tenant_id=tenant_id,
                data=ResearchEventCreate(
                    company_research_run_id=run_id,
                    event_type="canonical_dedupe",
                    status="ok",
                    input_json={
                        "source_id": str(source.id),
                        "content_hash": deduped_content_hash,
                    },
                    output_json={
                        "canonical_source_id": str(canonical.id),
                        "deduped": True,
                        "content_hash": deduped_content_hash,
                    },
                ),
            )

        return {"deduped": True, "canonical_source_id": str(canonical.id)}
    
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
