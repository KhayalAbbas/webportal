"""
List model.

Represents a custom list for organizing entities.
"""

from typing import Optional, List as ListType, TYPE_CHECKING

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base_model import TenantScopedModel

if TYPE_CHECKING:
    from app.models.list_item import ListItem


class List(TenantScopedModel):
    """
    List table - represents custom lists for organizing entities.
    """
    
    __tablename__ = "list"
    
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    
    type: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )
    
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    # Relationships
    items: Mapped[ListType["ListItem"]] = relationship(
        "ListItem",
        back_populates="list",
        lazy="selectin",
    )
