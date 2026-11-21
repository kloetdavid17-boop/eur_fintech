"""Public routes: health and the configuration the UI needs to be honest about what works."""

from fastapi import APIRouter

from app import inbox, plans
from app.config import settings
from app.extraction import ALLOWED_MIME_TYPES
from app.models import EXPENSE_CATEGORIES
from app.tax import province_list

router = APIRouter(prefix="/api", tags=["public"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "app": settings.app_name}


@router.get("/config")
async def get_config() -> dict:
    return {
        "app_name": settings.app_name,
        "currency": "CAD",
        "plans": [
            {"id": p.id, "name": p.name, "price_cad": p.price_cad,
             "monthly_receipt_limit": p.monthly_receipt_limit, "features": p.features}
            for p in plans.get_plans().values()
        ],
        "feature_matrix": [{"feature": f, "free": a, "premium": b} for f, a, b in plans.feature_matrix()],
        "categories": EXPENSE_CATEGORIES,
        "provinces": province_list(),
        "upload": {"max_mb": settings.max_upload_mb, "allowed_types": ALLOWED_MIME_TYPES},
        "services": {
            "ai_configured": settings.ai_configured,
            "inbound_email_configured": settings.inbound_email_configured,
            "inbound_domain": settings.inbound_address_domain,
            "inbound_mode": settings.inbound_mode,
            # Gmail mode only: did the last mailbox check work? None = not checked yet / not applicable.
            "inbound_ok": inbox.state.ok if settings.inbound_mode == "gmail" else None,
            "billing_mode": settings.billing_mode,
            "billing_test_mode": settings.billing_test_mode,
            "smtp_configured": settings.smtp_configured,
            "file_storage": settings.file_storage,
        },
    }
