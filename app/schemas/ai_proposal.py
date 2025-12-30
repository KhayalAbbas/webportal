"""
AI Proposal schemas for Phase 2 ingestion.

Defines strict JSON contract for AI-generated company research proposals.
"""

from typing import List, Optional, Union, Literal, Any
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator, model_validator
from uuid import UUID


class AIProposalSource(BaseModel):
    """Source document referenced in the proposal."""
    temp_id: str = Field(..., description="Temporary ID for referencing within proposal (e.g., 'source_1')")
    title: str = Field(..., min_length=1, max_length=500)
    url: Optional[str] = Field(None, max_length=1000)
    provider: Optional[str] = Field(None, max_length=100, description="AI provider or data source name")
    fetched_at: Optional[datetime] = None
    
    @field_validator('url')
    @classmethod
    def validate_url(cls, v):
        if v and not (v.startswith('http://') or v.startswith('https://')):
            raise ValueError('URL must start with http:// or https://')
        return v


class AIProposalMetric(BaseModel):
    """Metric value for a company - supports typed values (number, text, bool, json)."""
    key: str = Field(..., min_length=1, max_length=200, description="Metric key (e.g., 'total_assets', 'fleet_size')")
    type: Literal["number", "text", "bool", "json"] = Field(..., description="Value type")
    value: Union[int, float, Decimal, str, bool, List[Any], dict] = Field(..., description="Typed value matching the type field")
    
    # Optional metadata (primarily for number types)
    currency: Optional[str] = Field(None, min_length=3, max_length=10, description="ISO currency code (for number types)")
    unit: Optional[str] = Field(None, max_length=50, description="Unit of measurement (e.g., 'aircraft', 'employees', 'kg')")
    as_of_date: Optional[date] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    source_temp_id: Optional[str] = Field(None, description="References temp_id from sources[]")
    evidence_snippet: Optional[str] = Field(None, max_length=2000, description="Text snippet supporting this metric")
    
    @field_validator('currency')
    @classmethod
    def validate_currency(cls, v):
        if v:
            # Basic validation - could be expanded
            if len(v) != 3 or not v.isupper():
                raise ValueError('Currency must be 3-letter uppercase ISO code (e.g., USD, EUR)')
        return v
    
    @field_validator('key')
    @classmethod
    def validate_key(cls, v):
        # Normalize/slugify instead of rejecting (see invariants).
        if v is None:
            raise ValueError('Metric key is required')

        raw = str(v).strip().lower()
        if not raw:
            raise ValueError('Metric key must not be empty')

        # Keep alnum; map common separators to '_' and drop everything else.
        out = []
        prev_sep = False
        for ch in raw:
            if ch.isalnum() or ch == '_':
                out.append(ch)
                prev_sep = False
                continue

            if ch in ('-', ' ', '/', '.', ':'):
                if not prev_sep:
                    out.append('_')
                    prev_sep = True
                continue

            # drop other characters

        normalized = ''.join(out).strip('-')
        if not normalized:
            raise ValueError('Metric key normalizes to empty; provide a more descriptive key')

        # Collapse repeated underscores
        while '__' in normalized:
            normalized = normalized.replace('__', '_')

        return normalized
    
    @model_validator(mode='after')
    def validate_value_matches_type(self):
        """Ensure value type matches declared type."""
        value = self.value
        value_type = self.type
        
        if value_type == "number":
            if not isinstance(value, (int, float, Decimal)):
                raise ValueError(f"Value must be numeric for type 'number', got {type(value).__name__}")
        elif value_type == "text":
            if not isinstance(value, str):
                raise ValueError(f"Value must be string for type 'text', got {type(value).__name__}")
        elif value_type == "bool":
            if not isinstance(value, bool):
                raise ValueError(f"Value must be boolean for type 'bool', got {type(value).__name__}")
        elif value_type == "json":
            if not isinstance(value, (list, dict)):
                raise ValueError(f"Value must be list or dict for type 'json', got {type(value).__name__}")
        
        return self


class AIProposalAlias(BaseModel):
    """Alternative name for a company."""
    name: str = Field(..., min_length=1, max_length=500)
    type: str = Field(..., description="'legal', 'trade', 'former', 'local', 'abbreviation'")
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    
    @field_validator('type')
    @classmethod
    def validate_type(cls, v):
        allowed_types = {'legal', 'trade', 'former', 'local', 'abbreviation'}
        if v.lower() not in allowed_types:
            raise ValueError(f'Alias type must be one of: {", ".join(allowed_types)}')
        return v.lower()


class AIProposalCompany(BaseModel):
    """Company entry in the proposal."""
    name: str = Field(..., min_length=1, max_length=500, description="Primary company name")
    aliases: Optional[List[AIProposalAlias]] = Field(default_factory=list)
    metrics: List[AIProposalMetric] = Field(default_factory=list)
    website_url: Optional[str] = Field(None, max_length=500)
    hq_country: Optional[str] = Field(None, min_length=2, max_length=2, description="ISO 2-letter country code")
    hq_city: Optional[str] = Field(None, max_length=200)
    sector: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = Field(None, max_length=5000)
    ai_rank: Optional[int] = Field(None, ge=1, description="AI-assigned ranking position")
    ai_score: Optional[float] = Field(None, ge=0.0, le=1.0, description="AI relevance score")
    # Company-level evidence requirements
    evidence_snippets: List[str] = Field(default_factory=list, min_length=1, description="Evidence snippets supporting this company")
    source_sha256s: List[str] = Field(default_factory=list, min_length=1, description="SHA256s of sources supporting this company")
    
    @field_validator('hq_country')
    @classmethod
    def validate_country(cls, v):
        if v and (len(v) != 2 or not v.isupper()):
            raise ValueError('Country must be 2-letter uppercase ISO code (e.g., US, GB, AE)')
        return v
    
    @field_validator('website_url')
    @classmethod
    def validate_url(cls, v):
        if v and not (v.startswith('http://') or v.startswith('https://')):
            raise ValueError('URL must start with http:// or https://')
        return v


class AIProposal(BaseModel):
    """
    Complete AI-generated proposal for a company research run.
    
    Top-level structure defining the search query, sources, and companies.
    """
    query: str = Field(..., min_length=1, max_length=2000, description="Original search query or mandate description")
    sources: List[AIProposalSource] = Field(default_factory=list, description="Referenced source documents")
    companies: List[AIProposalCompany] = Field(..., min_items=1, description="List of discovered companies")
    generated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    model: Optional[str] = Field(None, max_length=100, description="AI model used (e.g., 'gpt-4', 'claude-3')")
    
    @field_validator('sources')
    @classmethod
    def validate_source_temp_ids_unique(cls, v):
        temp_ids = [s.temp_id for s in v]
        if len(temp_ids) != len(set(temp_ids)):
            raise ValueError('Source temp_ids must be unique')
        return v
    
    @field_validator('companies')
    @classmethod
    def validate_companies_not_empty(cls, v):
        if not v:
            raise ValueError('Proposal must contain at least one company')
        return v
    
    def get_source_by_temp_id(self, temp_id: str) -> Optional[AIProposalSource]:
        """Helper to find source by temp_id."""
        for source in self.sources:
            if source.temp_id == temp_id:
                return source
        return None


class AIProposalValidationError(BaseModel):
    """Validation error detail."""
    field: str
    message: str
    value: Optional[str] = None


class AIProposalValidationResult(BaseModel):
    """Result of proposal validation."""
    valid: bool
    errors: List[AIProposalValidationError] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    company_count: int = 0
    source_count: int = 0
    metric_count: int = 0
    
    def add_error(self, field: str, message: str, value: Optional[str] = None):
        """Add validation error."""
        self.valid = False
        self.errors.append(AIProposalValidationError(field=field, message=message, value=value))
    
    def add_warning(self, message: str):
        """Add validation warning."""
        self.warnings.append(message)


class AIProposalIngestionResult(BaseModel):
    """Result of proposal ingestion."""
    success: bool
    companies_ingested: int = 0
    companies_new: int = 0
    companies_existing: int = 0
    companies_duplicated: int = 0
    metrics_ingested: int = 0
    aliases_ingested: int = 0
    sources_created: int = 0
    evidence_created: int = 0
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    
    def add_error(self, message: str):
        """Add ingestion error."""
        self.success = False
        self.errors.append(message)
    
    def add_warning(self, message: str):
        """Add ingestion warning."""
        self.warnings.append(message)
