"""CRUD operations for products."""

from __future__ import annotations

import re
import uuid
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.product import (
    Category,
    Product,
    ProductCharacteristic,
    ProductImage,
    ProductStatus,
)
from src.models.sku import SKU, SKUCharacteristic
from src.schemas.errors import ErrorCode
from src.schemas.product import ProductCreate


def _make_slug(title: str) -> str:
    """Build a non-empty unique slug from title (required by response contract)."""
    raw = title.lower().strip()
    # keep unicode letters/digits, collapse separators
    raw = re.sub(r"[^\w\s-]", "", raw, flags=re.UNICODE)
    raw = re.sub(r"[-\s]+", "-", raw).strip("-")
    base = (raw[:150] if raw else "product")
    return f"{base}-{uuid.uuid4().hex[:8]}"


async def create_product(
    product_create: ProductCreate,
    seller_id: UUID,
    db: AsyncSession,
) -> Product:
    """
    Create a product card with images and optional characteristics/SKUs.

    - seller_id is provided by the caller (from JWT / X-Seller-Id), never from body.
    - status is always CREATED on creation (moderation is US-B2B-02).
    - category_id must exist.
    - at least one image is required (enforced by schema + here).
    - slug is always generated (required non-empty in ProductResponse).
    - All entity ids are UUID.
    """
    if not product_create.images:
        raise HTTPException(
            status_code=400,
            detail={
                "code": ErrorCode.VALIDATION_ERROR,
                "message": "At least one image is required",
                "details": {"field": "images"},
            },
        )

    category = await db.get(Category, product_create.category_id)
    if category is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": ErrorCode.INVALID_CATEGORY,
                "message": (
                    f"Category with id={product_create.category_id} does not exist"
                ),
                "details": {"field": "category_id"},
            },
        )

    db_product = Product(
        id=uuid.uuid4(),
        title=product_create.title,
        description=product_create.description,
        category_id=product_create.category_id,
        seller_id=seller_id,
        status=ProductStatus.CREATED,
        slug=_make_slug(product_create.title),
        deleted=False,
    )
    db.add(db_product)
    await db.flush()

    for img_data in product_create.images:
        db.add(
            ProductImage(
                id=uuid.uuid4(),
                product_id=db_product.id,
                url=img_data.url,
                ordering=img_data.ordering,
            )
        )

    for char_data in product_create.characteristics:
        db.add(
            ProductCharacteristic(
                id=uuid.uuid4(),
                product_id=db_product.id,
                name=char_data.name,
                value=char_data.value,
            )
        )

    for sku_data in product_create.skus:
        sku = SKU(
            id=uuid.uuid4(),
            product_id=db_product.id,
            sku_code=sku_data.sku_code,
            name=sku_data.name,
            price=sku_data.price,
            active_quantity=sku_data.active_quantity,
            blocked_quantity=0,
            active=True,
        )
        db.add(sku)
        await db.flush()
        for sku_char in sku_data.characteristics:
            db.add(
                SKUCharacteristic(
                    id=uuid.uuid4(),
                    sku_id=sku.id,
                    name=sku_char.name,
                    value=sku_char.value,
                )
            )

    await db.commit()

    result = await db.execute(
        select(Product)
        .where(Product.id == db_product.id)
        .options(
            selectinload(Product.images),
            selectinload(Product.characteristics),
            selectinload(Product.skus).selectinload(SKU.characteristics),
        )
    )
    return result.scalar_one()
