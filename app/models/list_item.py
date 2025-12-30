"""
ListItem model.

Represents an item in a custom list.
"""

import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import String, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base_model import TenantScopedModel

if TYPE_CHECKING:
    from app.models.list import List


class ListItem(TenantScopedModel):
    """
    ListItem table - represents items in custom lists.
    """
    
    __tablename__ = "list_item"
    
    list_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("list.id"),
        nullable=False,
    )
    
    entity_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()",
    )
    
    # Relationships
    list: Mapped["List"] = relationship(
        "List",
        back_populates="items",
    )
