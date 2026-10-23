"""Outgoing email (SMTP). Used to send a month's records to the owner's accountant.

If SMTP is not configured nothing is sent and ``EmailNotConfigured`` is raised: the route turns
that into ``503 email_not_configured``. There is deliberately no "log instead of sending" path
that could be mistaken for a real delivery.
"""

import logging
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

import aiosmtplib

from app.config import settings
from app.models import User

logger = logging.getLogger("tradetrack.email")


class EmailNotConfigured(Exception):
    pass


class EmailSendFailed(Exception):
    pass


def _clean(value: str) -> str:
    return " ".join((value or "").split())  # no newlines in headers


async def send_month_to_accountant(
    to: str, user: User, month: str, csv_bytes: bytes, pdf_bytes: bytes
) -> None:
    if not settings.smtp_configured:
        raise EmailNotConfigured()

    sender_name = _clean(f"{user.first_name} {user.last_name}") or "A TradeTrack user"
    from_address = parseaddr(settings.smtp_from)[1] or settings.smtp_from
    msg = EmailMessage()
    msg["From"] = formataddr((f"{sender_name} via TradeTrack", from_address))
    msg["Reply-To"] = formataddr((sender_name, user.email))
    msg["To"] = to
    msg["Subject"] = f"Expense records for {month} from {sender_name}"
    business = _clean(user.business_name or "")
    msg.set_content(
        f"Hello,\n\n{sender_name}{f' ({business})' if business else ''} shared their saved expense records for "
        f"{month} with you through TradeTrack.\n\n"
        "Attached: a CSV of the receipts and a PDF monthly summary. Amounts and tax are as shown on the receipts; "
        "categories may be suggestions. TradeTrack does not provide tax advice.\n\n"
        f"You can reply to this email to reach {sender_name} directly.\n\nTradeTrack"
    )
    msg.add_attachment(csv_bytes, maintype="text", subtype="csv", filename=f"tradetrack-receipts-{month}.csv")
    msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=f"tradetrack-summary-{month}.pdf")

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user or None,
            password=settings.smtp_password or None,
            start_tls=settings.smtp_tls,
            timeout=30,
        )
    except Exception as exc:
        logger.error("SMTP send failed (%s)", type(exc).__name__)
        raise EmailSendFailed() from exc
