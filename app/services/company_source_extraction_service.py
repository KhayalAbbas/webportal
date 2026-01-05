"""
Deterministic extraction for ResearchSourceDocument rows (HTML/PDF).
"""

from __future__ import annotations

import hashlib
import io
import re
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.company_research_repo import CompanyResearchRepository
from app.schemas.company_research import ResearchEventCreate
from app.utils.time import utc_now


class CompanySourceExtractionService:
    """Extracts text and quality signals from research source documents."""

    EXTRACTION_VERSION = "5.2.0"
    MIN_WORDS_HTML = 150
    MIN_WORDS_PDF = 50
    EXTREME_MIN_WORDS = 5
    PAYWALL_KEYWORDS = ["subscribe", "sign in", "log in", "access denied", "registration", "paywall"]
    ERROR_KEYWORDS = ["page not found", "404", "service unavailable", "temporarily unavailable"]
    TEMPLATE_SIGNATURE_BYTES = 2000
    SIGNATURE_TOKEN_COUNT = 500
    UNIQUE_TOKEN_RATIO_MIN = 0.12
    ALPHA_RATIO_MIN = 0.55

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = CompanyResearchRepository(db)

    async def extract_sources(self, tenant_id: str, run_id) -> dict:
        sources = await self.repo.get_extractable_sources(tenant_id, run_id)
        summary = {
            "count": len(sources),
            "processed": 0,
            "skipped": 0,
            "accepted": 0,
            "flagged": 0,
            "rejected": 0,
            "sources": [],
        }

        for source in sources:
            meta = dict(source.meta or {}) if isinstance(source.meta, dict) else {}
            extraction_meta: Dict[str, Any] = meta.get("extraction") or {}

            raw_bytes = source.content_bytes or b""
            mime = (source.mime_type or "").lower()
            material_bytes = raw_bytes if raw_bytes else (source.content_text or "").encode("utf-8")
            material_hash = hashlib.sha256(material_bytes).hexdigest()

            prev_version = extraction_meta.get("version")
            prev_material_hash = extraction_meta.get("source_material_hash")
            prev_text_hash = extraction_meta.get("text_hash")
            if prev_version == self.EXTRACTION_VERSION and prev_material_hash == material_hash and prev_text_hash:
                summary["skipped"] += 1
                summary["sources"].append({"id": str(source.id), "status": "skipped", "reason": "already_extracted"})
                await self.repo.create_research_event(
                    tenant_id=tenant_id,
                    data=ResearchEventCreate(
                        company_research_run_id=run_id,
                        event_type="extract_source_content",
                        status="ok",
                        input_json={"source_id": str(source.id), "skipped": True},
                        output_json={"reason": "already_extracted"},
                    ),
                )
                continue

            text: str = ""
            title: Optional[str] = None
            page_count: Optional[int] = None
            pdf_unextractable = False
            pdf_bytes_missing = False
            is_pdf_type = "pdf" in mime or (source.source_type and source.source_type.lower() == "pdf")
            is_html_like = not is_pdf_type and ("html" in mime or "text" in mime or not mime)
            unsupported_type = not is_pdf_type and not is_html_like

            if is_pdf_type:
                if raw_bytes:
                    text, page_count, pdf_unextractable = self._extract_pdf(raw_bytes)
                else:
                    text = source.content_text or ""
                    page_count = None
                    pdf_unextractable = not bool(text)
                    pdf_bytes_missing = True
                min_words = self.MIN_WORDS_PDF
            elif unsupported_type:
                text = source.content_text or ""
                min_words = self.MIN_WORDS_HTML
            else:
                if raw_bytes:
                    text, title = self._extract_html(raw_bytes)
                else:
                    text = source.content_text or ""
                min_words = self.MIN_WORDS_HTML

            normalized_text = self._normalize_text(text)
            tokens = self._tokenize(normalized_text)
            word_count = len(tokens)
            char_count = len(normalized_text)
            line_count = len([ln for ln in normalized_text.split("\n") if ln.strip()])
            unique_tokens = len(set(tokens))
            unique_token_ratio = unique_tokens / max(len(tokens), 1)
            alpha_chars = sum(1 for ch in normalized_text if ch.isalpha())
            alpha_ratio = alpha_chars / max(len(normalized_text), 1)

            reason_codes: List[str] = []
            quality_flags = {
                "is_thin": False,
                "is_paywall_or_login": False,
                "is_error_page": False,
                "is_duplicate_template": False,
                "is_unextractable_pdf": False,
                "is_pdf_bytes_missing": False,
                "is_unsupported_type": False,
                "is_boilerplate_dominant": False,
                "duplicate_group_key": None,
                "duplicate_primary_source_id": None,
            }

            if unsupported_type:
                quality_flags["is_unsupported_type"] = True
                reason_codes.append("FLAG_UNSUPPORTED_TYPE")

            if pdf_bytes_missing:
                quality_flags["is_pdf_bytes_missing"] = True
                reason_codes.append("FLAG_PDF_BYTES_MISSING")

            if word_count == 0:
                reason_codes.append("REJECT_EMPTY_TEXT")
            else:
                if word_count < self.EXTREME_MIN_WORDS:
                    quality_flags["is_thin"] = True
                    reason_codes.append("REJECT_EXTREME_THIN")
                elif word_count < min_words:
                    quality_flags["is_thin"] = True
                    reason_codes.append("FLAG_THIN_CONTENT")

                probe_text = ((title or "") + " " + normalized_text[:2000]).lower()
                if any(keyword in probe_text for keyword in self.PAYWALL_KEYWORDS):
                    quality_flags["is_paywall_or_login"] = True
                    reason_codes.append("FLAG_PAYWALL_OR_LOGIN")
                if any(keyword in probe_text for keyword in self.ERROR_KEYWORDS):
                    quality_flags["is_error_page"] = True
                    reason_codes.append("FLAG_ERROR_PAGE")
                if pdf_unextractable:
                    quality_flags["is_unextractable_pdf"] = True
                    reason_codes.append("FLAG_UNEXTRACTABLE_PDF")

                boilerplate_suspected = (
                    (unique_token_ratio < self.UNIQUE_TOKEN_RATIO_MIN)
                    or (alpha_ratio < self.ALPHA_RATIO_MIN)
                ) and word_count >= self.MIN_WORDS_HTML
                if boilerplate_suspected:
                    quality_flags["is_boilerplate_dominant"] = True
                    reason_codes.append("FLAG_BOILERPLATE_DOMINANT")

            decision = "accept"
            if "REJECT_EMPTY_TEXT" in reason_codes or "REJECT_EXTREME_THIN" in reason_codes:
                decision = "reject"
            elif quality_flags.get("is_paywall_or_login") or quality_flags.get("is_error_page"):
                decision = "flag"
            elif quality_flags.get("is_thin"):
                decision = "flag"
            elif quality_flags.get("is_boilerplate_dominant"):
                decision = "flag"
            elif any(code.startswith("FLAG_") for code in reason_codes):
                decision = "flag"

            extraction_timestamp = utc_now()
            text_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
            signature_exact = text_hash
            normalized_for_sig = normalized_text[: self.TEMPLATE_SIGNATURE_BYTES]
            signature_prefix_2k = hashlib.sha256(normalized_for_sig.encode("utf-8")).hexdigest()
            token_prefix = " ".join(tokens[: self.SIGNATURE_TOKEN_COUNT])
            signature_tokens = hashlib.sha256(token_prefix.encode("utf-8")).hexdigest()
            template_signature = signature_prefix_2k

            extraction_meta = {
                "version": self.EXTRACTION_VERSION,
                "extractor_version": self.EXTRACTION_VERSION,
                "source_material_hash": material_hash,
                "text_hash": text_hash,
                "signature_exact": signature_exact,
                "signature_prefix_2k": signature_prefix_2k,
                "signature_tokens": signature_tokens,
                "token_count": len(tokens),
                "unique_token_ratio": unique_token_ratio,
                "alpha_ratio": alpha_ratio,
                "word_count": word_count,
                "char_count": char_count,
                "line_count": line_count,
                "decision": decision,
                "reason_codes": sorted(reason_codes),
                "mime_type_used": mime or (source.mime_type or "unknown"),
                "template_signature": template_signature,
                "thresholds": {
                    "min_words": min_words,
                    "min_words_html": self.MIN_WORDS_HTML,
                    "min_words_pdf": self.MIN_WORDS_PDF,
                    "signature_prefix_bytes": self.TEMPLATE_SIGNATURE_BYTES,
                    "signature_tokens_n": self.SIGNATURE_TOKEN_COUNT,
                    "unique_token_ratio_min": self.UNIQUE_TOKEN_RATIO_MIN,
                    "alpha_ratio_min": self.ALPHA_RATIO_MIN,
                    "extreme_min_words": self.EXTREME_MIN_WORDS,
                },
                "extracted_at": extraction_timestamp.isoformat(),
            }
            if title:
                extraction_meta["title"] = title
            if page_count is not None:
                extraction_meta["page_count"] = page_count
            extraction_meta["pdf_bytes_present"] = bool(raw_bytes)

            meta["extraction"] = extraction_meta
            meta["quality_flags"] = quality_flags

            source.content_text = normalized_text
            source.content_hash = text_hash if normalized_text else None
            source.meta = meta
            await self.db.flush()

            event_status = "ok" if decision == "accept" else "warn" if decision == "flag" else "failed"
            await self.repo.create_research_event(
                tenant_id=tenant_id,
                data=ResearchEventCreate(
                    company_research_run_id=run_id,
                    event_type="extract_source_content",
                    status=event_status,
                    input_json={
                        "source_id": str(source.id),
                        "mime_type": source.mime_type,
                        "word_count": word_count,
                        "decision": decision,
                    },
                    output_json={"reason_codes": extraction_meta["reason_codes"], "quality_flags": quality_flags},
                ),
            )

            summary["processed"] += 1
            summary["accepted"] += 1 if decision == "accept" else 0
            summary["flagged"] += 1 if decision == "flag" else 0
            summary["rejected"] += 1 if decision == "reject" else 0
            summary["sources"].append({
                "id": str(source.id),
                "decision": decision,
                "reason_codes": extraction_meta["reason_codes"],
                "word_count": word_count,
            })

        await self.db.commit()
        return summary

    async def classify_sources(self, tenant_id: str, run_id) -> dict:
        sources = await self.repo.list_source_documents_for_run(tenant_id, run_id)
        summary = {
            "count": len(sources),
            "processed": 0,
            "skipped": 0,
            "duplicates": 0,
            "updated": 0,
            "sources": [],
        }

        groups: dict[str, list[dict[str, Any]]] = {}
        for source in sources:
            meta = dict(source.meta or {}) if isinstance(source.meta, dict) else {}
            extraction_meta: Dict[str, Any] = meta.get("extraction") or {}
            if extraction_meta.get("version") != self.EXTRACTION_VERSION:
                summary["skipped"] += 1
                continue
            if (extraction_meta.get("word_count") or 0) == 0:
                summary["skipped"] += 1
                continue
            sig = extraction_meta.get("signature_prefix_2k") or extraction_meta.get("signature_exact") or extraction_meta.get("text_hash")
            if not sig:
                summary["skipped"] += 1
                continue
            groups.setdefault(sig, []).append({
                "source": source,
                "meta": meta,
                "extraction": extraction_meta,
                "word_count": extraction_meta.get("word_count") or 0,
                "id_str": str(source.id),
            })

        for group_sig, candidates in groups.items():
            if len(candidates) < 2:
                continue

            candidates_sorted = sorted(candidates, key=lambda c: (-c["word_count"], c["id_str"]))
            primary = candidates_sorted[0]
            primary_id = primary["id_str"]

            for idx, candidate in enumerate(candidates_sorted):
                src = candidate["source"]
                meta = candidate["meta"]
                extraction_meta = candidate["extraction"]
                quality_flags = dict(meta.get("quality_flags") or {})
                reason_codes = set(extraction_meta.get("reason_codes") or [])

                if idx == 0:
                    quality_flags.setdefault("duplicate_group_key", group_sig)
                    quality_flags.setdefault("duplicate_primary_source_id", primary_id)
                else:
                    quality_flags["is_duplicate_template"] = True
                    quality_flags["duplicate_group_key"] = group_sig
                    quality_flags["duplicate_primary_source_id"] = primary_id
                    reason_codes.add("FLAG_DUPLICATE_TEMPLATE")
                    summary["duplicates"] += 1

                decision = self._recompute_decision(quality_flags, reason_codes)
                extraction_meta["decision"] = decision
                extraction_meta["reason_codes"] = sorted(reason_codes)
                meta["extraction"] = extraction_meta
                meta["quality_flags"] = quality_flags
                src.meta = meta
                summary["processed"] += 1
                summary["updated"] += 1
                summary["sources"].append({
                    "id": str(src.id),
                    "decision": decision,
                    "duplicate": idx != 0,
                    "group": group_sig,
                    "primary": primary_id,
                })

        await self.db.commit()
        return summary

    def _tokenize(self, text: str) -> List[str]:
        return re.findall(r"\b\w+\b", (text or "").lower())

    def _recompute_decision(self, quality_flags: Dict[str, Any], reason_codes: set[str]) -> str:
        if any(code.startswith("REJECT_") for code in reason_codes):
            return "reject"
        if quality_flags.get("is_paywall_or_login") or quality_flags.get("is_error_page"):
            return "flag"
        if quality_flags.get("is_thin"):
            return "flag"
        if quality_flags.get("is_boilerplate_dominant"):
            return "flag"
        if quality_flags.get("is_duplicate_template"):
            return "flag"
        if any(code.startswith("FLAG_") for code in reason_codes):
            return "flag"
        return "accept"

    def _normalize_text(self, text: str) -> str:
        text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[\t ]+", " ", text)
        text = re.sub(r"\n{2,}", "\n", text)
        return text.strip()

    def _count_words(self, text: str) -> int:
        return len(re.findall(r"\b\w+\b", text or ""))

    def _extract_html(self, raw_bytes: bytes) -> tuple[str, Optional[str]]:
        if not raw_bytes:
            return "", None
        try:
            html = raw_bytes.decode("utf-8", errors="replace")
        except Exception:
            html = raw_bytes.decode("latin-1", errors="replace")

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all(["script", "style", "noscript"]):
            tag.decompose()

        title: Optional[str] = None
        og_title = soup.find("meta", attrs={"property": "og:title"}) or soup.find("meta", attrs={"name": "og:title"})
        if og_title and og_title.get("content"):
            title = og_title.get("content")
        elif soup.title and soup.title.string:
            title = soup.title.string
        else:
            h1 = soup.find("h1")
            if h1 and h1.get_text(strip=True):
                title = h1.get_text(strip=True)

        text = soup.get_text(" ", strip=True)
        return text, title

    def _extract_pdf(self, raw_bytes: bytes) -> tuple[str, Optional[int], bool]:
        if not raw_bytes:
            return "", None, True
        try:
            reader = PdfReader(io.BytesIO(raw_bytes))
        except Exception:
            return "", None, True

        page_texts: List[str] = []
        for idx, page in enumerate(reader.pages, start=1):
            try:
                extracted = page.extract_text() or ""
            except Exception:
                extracted = ""
            page_texts.append(extracted.strip())

        page_count = len(page_texts)
        if not page_texts:
            return "", page_count, True

        # Insert page separators deterministically
        joined_parts: List[str] = []
        for i, txt in enumerate(page_texts, start=1):
            if i > 1:
                joined_parts.append(f"--- page {i} ---")
            joined_parts.append(txt)
        text = "\n\n".join(joined_parts)
        return text, page_count, False
