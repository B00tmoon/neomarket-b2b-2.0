from __future__ import annotations

import uuid
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.base import get_db
from src.models.product import Product, ProductStatus
from src.models.sku import SKU, SKUCharacteristic
from src.schemas.product import SKUCreate, SKUResponse

router = APIRouter()


@router.post("/products/{product_id}/skus", response_model=SKUResponse, status_code=201)
async def create_sku(
    product_id: UUID,
    sku: SKUCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Create SKU. For first SKU on product: transition to ON_MODERATION, emit event to Moderation.
    """
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if product.status == ProductStatus.HARD_BLOCKED:
        raise HTTPException(status_code=403, detail={"code": "PRODUCT_HARD_BLOCKED"})

    skus_result = await db.execute(select(SKU).where(SKU.product_id == product_id))
    is_first_sku = len(skus_result.scalars().all()) == 0

    existing = await db.execute(select(SKU).where(SKU.sku_code == sku.sku_code))
    if existing.scalar():
        raise HTTPException(status_code=400, detail="SKU code already exists")

    db_sku = SKU(
        id=uuid.uuid4(),
        product_id=product_id,
        sku_code=sku.sku_code,
        name=sku.name,
        price=sku.price,
        active_quantity=sku.active_quantity,
    )
    db.add(db_sku)
    await db.flush()

    for char_data in sku.characteristics:
        db.add(
            SKUCharacteristic(
                id=uuid.uuid4(),
                sku_id=db_sku.id,
                name=char_data.name,
                value=char_data.value,
            )
        )

    if is_first_sku and product.status == ProductStatus.CREATED:
        product.status = ProductStatus.ON_MODERATION
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                await client.post(
                    "http://localhost:8002/api/v1/moderation/events",
                    json={
                        "product_id": str(product.id),
                        "event_type": "CREATED",
                        "idempotency_key": str(uuid.uuid4()),
                        "occurred_at": datetime.now(timezone.utc).isoformat(),
                    },
                    headers={"X-Service-Key": "b2b-moderation-key"},
                )
        except Exception:
            pass

    await db.commit()
    await db.refresh(db_sku)
    return db_sku


@router.put("/skus/{sku_id}", response_model=SKUResponse)
async def update_sku(
    sku_id: UUID, sku_update: SKUCreate, db: AsyncSession = Depends(get_db)
):
    """Обновить SKU."""
    db_sku = await db.get(SKU, sku_id)
    if not db_sku:
        raise HTTPException(status_code=404, detail="SKU not found")

    db_sku.sku_code = sku_update.sku_code
    db_sku.name = sku_update.name
    db_sku.price = sku_update.price
    db_sku.active_quantity = sku_update.active_quantity

    from sqlalchemy import delete

    await db.execute(
        delete(SKUCharacteristic).where(SKUCharacteristic.sku_id == sku_id)
    )

    for char_data in sku_update.characteristics:
        db.add(
            SKUCharacteristic(
                id=uuid.uuid4(),
                sku_id=sku_id,
                name=char_data.name,
                value=char_data.value,
            )
        )

    await db.commit()
    await db.refresh(db_sku)
    return db_sku


@router.get("/skus/{sku_id}", response_model=SKUResponse)
async def get_sku(sku_id: UUID, db: AsyncSession = Depends(get_db)):
    """Получить SKU по UUID."""
    sku = await db.get(SKU, sku_id)
    if not sku:
        raise HTTPException(status_code=404, detail="SKU not found")
    return sku


@router.post("/skus/{sku_id}/reserve")
async def reserve_sku(
    sku_id: UUID, quantity: int, db: AsyncSession = Depends(get_db)
):
    """Резервировать товар (уменьшить activeQuantity)."""
    sku = await db.get(SKU, sku_id)
    if not sku:
        raise HTTPException(status_code=404, detail="SKU not found")

    if sku.active_quantity < quantity:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Insufficient quantity. Available: {sku.active_quantity}, "
                f"requested: {quantity}"
            ),
        )

    sku.active_quantity -= quantity
    sku.blocked_quantity += quantity
    await db.commit()
    await db.refresh(sku)

    return {
        "sku_id": str(sku_id),
        "reserved": quantity,
        "remaining": sku.active_quantity,
    }


@router.post("/skus/{sku_id}/release")
async def release_sku(
    sku_id: UUID, quantity: int, db: AsyncSession = Depends(get_db)
):
    """Освободить резерв (вернуть товар в activeQuantity)."""
    sku = await db.get(SKU, sku_id)
    if not sku:
        raise HTTPException(status_code=404, detail="SKU not found")

    if sku.blocked_quantity < quantity:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot release more than reserved. "
                f"Reserved: {sku.blocked_quantity}"
            ),
        )

    sku.blocked_quantity -= quantity
    sku.active_quantity += quantity
    await db.commit()
    await db.refresh(sku)

    return {
        "sku_id": str(sku_id),
        "released": quantity,
        "active": sku.active_quantity,
    }


@router.post("/skus/batch")
async def get_skus_batch(sku_ids: list[UUID], db: AsyncSession = Depends(get_db)):
    """Получить несколько SKU по списку UUID."""
    skus = await db.execute(select(SKU).where(SKU.id.in_(sku_ids)))
    sku_list = skus.scalars().all()

    result = {}
    for sku in sku_list:
        result[str(sku.id)] = {
            "id": str(sku.id),
            "product_id": str(sku.product_id),
            "sku_code": sku.sku_code,
            "name": sku.name,
            "price": sku.price,
            "active_quantity": sku.active_quantity,
            "blocked_quantity": sku.blocked_quantity,
            "active": sku.active,
            "characteristics": [
                {"name": c.name, "value": c.value} for c in sku.characteristics
            ],
        }
    return result


@router.post("/inventory/reserve")
async def reserve_stock(
    reservations: list[dict],
    x_service_key: str = Header(..., alias="X-Service-Key"),
    db: AsyncSession = Depends(get_db),
):
    """All-or-nothing reserve for multiple SKUs (US-B2B-08)."""
    if not x_service_key or x_service_key != "b2c-service-key":
        raise HTTPException(
            status_code=401,
            detail={
                "code": "INVALID_SERVICE_KEY",
                "message": "X-Service-Key is required",
            },
        )

    try:
        results = []
        for res in reservations:
            raw_id = res.get("sku_id")
            quantity = res.get("quantity", 1)
            try:
                sku_id = UUID(str(raw_id))
            except (ValueError, TypeError):
                raise HTTPException(
                    status_code=400, detail=f"Invalid sku_id UUID: {raw_id}"
                )

            sku = await db.get(SKU, sku_id, with_for_update=True)
            if not sku:
                raise HTTPException(status_code=404, detail=f"SKU {sku_id} not found")

            if sku.active_quantity < quantity:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "INSUFFICIENT_STOCK",
                        "message": "Partial insufficient - rollback",
                    },
                )

            sku.active_quantity -= quantity
            sku.blocked_quantity += quantity
            results.append(
                {
                    "sku_id": str(sku_id),
                    "reserved": quantity,
                    "remaining": sku.active_quantity,
                }
            )

        await db.commit()
        return {"success": results, "total_reserved": len(results)}
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/inventory/unreserve")
async def unreserve_stock(
    unreservations: list[dict],
    x_service_key: str = Header(..., alias="X-Service-Key"),
    db: AsyncSession = Depends(get_db),
):
    """Unreserve for multiple SKUs."""
    if not x_service_key or x_service_key != "b2c-service-key":
        raise HTTPException(
            status_code=401,
            detail={
                "code": "INVALID_SERVICE_KEY",
                "message": "X-Service-Key is required",
            },
        )

    try:
        for unres in unreservations:
            raw_id = unres.get("sku_id")
            quantity = unres.get("quantity", 1)
            try:
                sku_id = UUID(str(raw_id))
            except (ValueError, TypeError):
                raise HTTPException(
                    status_code=400, detail=f"Invalid sku_id UUID: {raw_id}"
                )

            sku = await db.get(SKU, sku_id, with_for_update=True)
            if not sku:
                raise HTTPException(status_code=404, detail=f"SKU {sku_id} not found")
            if sku.blocked_quantity < quantity:
                raise HTTPException(
                    status_code=409, detail="Insufficient reserved quantity"
                )
            sku.blocked_quantity -= quantity
            sku.active_quantity += quantity
        await db.commit()
        return {"status": "UNRESERVED", "unreserved_count": len(unreservations)}
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
