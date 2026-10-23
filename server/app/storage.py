"""Original-file storage. Files are private: they are only ever served through the
authenticated ``GET /api/receipts/{id}/file`` route, never via a public URL.

Backends
* ``database`` (default): bytes in ``tt_receipt_files``.
* ``s3``: any S3-compatible bucket, used only when ZZPAY_S3_ENDPOINT/BUCKET/ACCESS_KEY/SECRET_KEY
  are all set. The backend each receipt was stored with is recorded on the receipt, so changing
  configuration later never orphans existing files. If an S3 upload fails the file is kept in the
  database instead (the receipt records where it went).
"""

import asyncio
import logging
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Receipt, ReceiptFile

logger = logging.getLogger("tradetrack.storage")


def _s3_client():
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region or None,
    )


async def put_file(session: AsyncSession, receipt: Receipt, data: bytes) -> None:
    """Store ``data`` and record where it went on the receipt."""
    if settings.s3_configured:
        key = f"receipts/{receipt.user_id}/{receipt.id}"
        try:
            await asyncio.to_thread(
                lambda: _s3_client().put_object(
                    Bucket=settings.s3_bucket, Key=key, Body=data, ContentType=receipt.file_mime_type or "application/octet-stream"
                )
            )
            receipt.file_storage, receipt.file_key = "s3", key
            return
        except Exception as exc:
            logger.error("S3 upload failed (%s); storing in the database instead", type(exc).__name__)
    session.add(ReceiptFile(receipt_id=receipt.id, user_id=receipt.user_id, data=data))
    receipt.file_storage, receipt.file_key = "database", None


async def get_file(session: AsyncSession, receipt: Receipt) -> bytes | None:
    if receipt.file_storage == "database":
        row = await session.get(ReceiptFile, receipt.id)
        return row.data if row else None
    if receipt.file_storage == "s3" and receipt.file_key and settings.s3_configured:
        try:
            obj = await asyncio.to_thread(
                lambda: _s3_client().get_object(Bucket=settings.s3_bucket, Key=receipt.file_key)
            )
            return await asyncio.to_thread(obj["Body"].read)
        except Exception as exc:
            logger.error("S3 download failed (%s)", type(exc).__name__)
    return None


async def delete_file(session: AsyncSession, receipt: Receipt) -> None:
    if receipt.file_storage == "s3" and receipt.file_key and settings.s3_configured:
        try:
            await asyncio.to_thread(
                lambda: _s3_client().delete_object(Bucket=settings.s3_bucket, Key=receipt.file_key)
            )
        except Exception as exc:
            logger.error("S3 delete failed (%s)", type(exc).__name__)
    await session.execute(delete(ReceiptFile).where(ReceiptFile.receipt_id == receipt.id))


async def delete_user_files(session: AsyncSession, user_id: UUID, receipts: list[Receipt]) -> None:
    for r in receipts:
        if r.file_storage == "s3":
            await delete_file(session, r)
    await session.execute(delete(ReceiptFile).where(ReceiptFile.user_id == user_id))
