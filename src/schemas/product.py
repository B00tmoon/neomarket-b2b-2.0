from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductStatusEnum(str, Enum):
    CREATED = "CREATED"
    ON_MODERATION = "ON_MODERATION"
    MODERATED = "MODERATED"
    BLOCKED = "BLOCKED"
    HARD_BLOCKED = "HARD_BLOCKED"


class ProductImageBase(BaseModel):
    url: str = Field(..., min_length=1, max_length=500)
    ordering: int = Field(0, ge=0)


class ProductImageCreate(ProductImageBase):
    pass


class ProductImageResponse(ProductImageBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID


class ProductCharacteristicBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    value: str = Field(..., min_length=1, max_length=500)


class ProductCharacteristicCreate(ProductCharacteristicBase):
    pass


class ProductCharacteristicResponse(ProductCharacteristicBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID


class SKUBase(BaseModel):
    sku_code: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=200)
    price: int = Field(..., ge=0, description="Цена в копейках")
    active_quantity: int = Field(0, ge=0)
    characteristics: List[ProductCharacteristicBase] = []


class SKUCreate(SKUBase):
    pass


class SKUResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    sku_code: str
    name: str
    price: int
    active_quantity: int = 0
    blocked_quantity: int = 0
    active: bool = True
    characteristics: List[ProductCharacteristicResponse] = []


class ProductCreate(BaseModel):
    """Request body for POST /api/v1/products.

    Spec-required fields: title, description, category_id, images (≥1).
    seller_id is NEVER accepted from body (taken from JWT / X-Seller-Id).
    """

    title: str = Field(..., min_length=1, max_length=500)
    description: str = Field(
        ...,
        min_length=1,
        description="Product description is required by specification",
    )
    category_id: UUID = Field(..., description="Category ID (UUID) is required")
    images: List[ProductImageCreate] = Field(
        ...,
        min_length=1,
        description="At least one image is required",
    )
    characteristics: List[ProductCharacteristicCreate] = Field(default_factory=list)
    skus: List[SKUCreate] = Field(default_factory=list)

    @field_validator("title", "description")
    @classmethod
    def strip_non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty or whitespace-only")
        return v


class ProductUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    description: Optional[str] = Field(None, min_length=1)
    category_id: Optional[UUID] = None


class ProductResponse(BaseModel):
    """Full product response — required fields always present after create.

    Spec-required non-null fields: id, seller_id, title, description,
    category_id, status, slug, images, created_at.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    seller_id: UUID
    title: str
    description: str
    category_id: UUID
    status: str
    slug: str
    images: List[ProductImageResponse]
    characteristics: List[ProductCharacteristicResponse] = []
    skus: List[SKUResponse] = []
    created_at: datetime
    updated_at: Optional[datetime] = None
    deleted: bool = False
    blocking_comment: Optional[str] = None
    blocking_reason_id: Optional[UUID] = None
    moderator_comment: Optional[str] = None
    blocking_reason: Optional[dict] = None
    field_reports: Optional[list] = None
