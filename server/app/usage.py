"""Free-plan usage accounting. All of it is computed on the server from ``tt_usage_events``."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from app import plans
from app.models import UsageEvent, User


async def saved_in_period(session: AsyncSession, user_id: UUID, period: str) -> int:
    n = await session.scalar(
        select(func.count()).select_from(UsageEvent).where(UsageEvent.user_id == user_id, UsageEvent.period == period)
    )
    return int(n or 0)


async def usage_summary(session: AsyncSession, user: User) -> dict:
    plan = plans.plan_for(user.plan)
    now = plans.now_utc()
    start, end = plans.period_bounds(now)
    used = await saved_in_period(session, user.id, plans.period_key(now))
    limit = plan.monthly_receipt_limit
    return {
        "plan": plan.id,
        "saved_this_period": used,
        "limit": limit,
        "remaining": None if limit is None else max(limit - used, 0),
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "period_label": plans.period_label(now),
        "resets_on": plans.resets_on(now).isoformat(),
    }
