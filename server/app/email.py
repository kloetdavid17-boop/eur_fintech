"""Outgoing email: the accountant export, the welcome email and the Premium order confirmation.

Two ways to deliver, chosen by configuration:

* ``ZZPAY_BREVO_API_KEY`` set -> Brevo's HTTPS API (port 443). Use this on hosts that block SMTP
  ports, such as Render's free web services. ``ZZPAY_SMTP_FROM`` must be a sender verified in Brevo.
* ``ZZPAY_SMTP_HOST`` set -> plain SMTP.

If neither is configured nothing is sent and ``EmailNotConfigured`` is raised. There is deliberately
no "log instead of sending" path that could be mistaken for a real delivery. The welcome and order
emails are best effort: ``send_welcome`` / ``send_upgrade_confirmation`` return ``"sent"``,
``"failed"`` or ``"not_configured"`` and never raise, so an email problem can never block signing
up or paying.
"""

import base64
import logging
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

import aiosmtplib
import httpx

from app import plans
from app.config import settings
from app.models import User

logger = logging.getLogger("tradetrack.email")

BREVO_URL = "https://api.brevo.com/v3/smtp/email"


class EmailNotConfigured(Exception):
    pass


class EmailSendFailed(Exception):
    pass


def _clean(value: str) -> str:
    return " ".join((value or "").split())  # no newlines in headers


def _sender() -> tuple[str, str]:
    name, address = parseaddr(settings.smtp_from)
    return (name or "TradeTrack"), (address or settings.smtp_from)


async def _post_json(url: str, headers: dict, payload: dict, timeout: float) -> int:
    """POST JSON and return the status code. A separate function so tests can replace it."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        return (await client.post(url, headers=headers, json=payload)).status_code


async def _send_brevo(msg: EmailMessage, timeout: float) -> None:
    from_name, from_address = _sender()
    body = msg.get_body(("plain",))
    payload: dict = {
        "sender": {"name": from_name, "email": from_address},
        "to": [{"email": msg["To"]}],
        "subject": str(msg["Subject"]),
        "textContent": body.get_content() if body is not None else "",
    }
    reply_name, reply_address = parseaddr(msg.get("Reply-To", ""))
    if reply_address:
        payload["replyTo"] = {"email": reply_address, **({"name": reply_name} if reply_name else {})}
    attachments = [
        {"name": part.get_filename(), "content": base64.b64encode(part.get_payload(decode=True)).decode("ascii")}
        for part in msg.iter_attachments()
    ]
    if attachments:
        payload["attachment"] = attachments
    headers = {"api-key": settings.brevo_api_key.strip(), "accept": "application/json"}
    try:
        status = await _post_json(BREVO_URL, headers, payload, timeout)
    except Exception as exc:
        logger.error("Brevo request failed (%s)", type(exc).__name__)
        raise EmailSendFailed() from exc
    if status not in (200, 201, 202):
        logger.error("Brevo rejected the email (HTTP %s)", status)  # never log the key or the body
        raise EmailSendFailed()


async def _send_smtp(msg: EmailMessage, timeout: float) -> None:
    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user or None,
            password=settings.smtp_password or None,
            start_tls=settings.smtp_tls,
            timeout=timeout,
        )
    except Exception as exc:
        logger.error("SMTP send failed (%s)", type(exc).__name__)
        raise EmailSendFailed() from exc


async def _deliver(msg: EmailMessage, timeout: float = 30) -> None:
    if settings.brevo_api_key.strip():
        await _send_brevo(msg, timeout)
    elif settings.smtp_host.strip():
        await _send_smtp(msg, timeout)
    else:
        raise EmailNotConfigured()


def _message(to: str, subject: str, text: str) -> EmailMessage:
    from_name, from_address = _sender()
    msg = EmailMessage()
    msg["From"] = formataddr((from_name, from_address))
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    return msg


async def _best_effort(msg: EmailMessage, what: str) -> str:
    if not settings.smtp_configured:
        return "not_configured"
    try:
        await _deliver(msg, timeout=10)
    except (EmailNotConfigured, EmailSendFailed):
        logger.warning("%s email was not delivered", what)
        return "failed"
    return "sent"


# --------------------------------------------------------------------------- #
# Accountant export
# --------------------------------------------------------------------------- #
async def send_month_to_accountant(
    to: str, user: User, month: str, csv_bytes: bytes, pdf_bytes: bytes
) -> None:
    """``month`` is the period label: ``YYYY-MM`` or ``start to end``."""
    if not settings.smtp_configured:
        raise EmailNotConfigured()

    sender_name = _clean(f"{user.first_name} {user.last_name}") or "A TradeTrack user"
    from_address = _sender()[1]
    file_label = month.replace(" to ", "_to_")
    msg = EmailMessage()
    msg["From"] = formataddr((f"{sender_name} via TradeTrack", from_address))
    msg["Reply-To"] = formataddr((sender_name, user.email))
    msg["To"] = to
    msg["Subject"] = f"Expense records for {month} from {sender_name}"
    business = _clean(user.business_name or "")
    msg.set_content(
        f"Hello,\n\n{sender_name}{f' ({business})' if business else ''} shared their saved expense records for "
        f"{month} with you through TradeTrack.\n\n"
        "Attached: a CSV of the receipts and a PDF summary of the period. Amounts and tax are as shown on the receipts; "
        "categories may be suggestions. TradeTrack does not provide tax advice.\n\n"
        f"You can reply to this email to reach {sender_name} directly.\n\nTradeTrack"
    )
    msg.add_attachment(csv_bytes, maintype="text", subtype="csv", filename=f"tradetrack-receipts-{file_label}.csv")
    msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=f"tradetrack-summary-{file_label}.pdf")
    await _deliver(msg)


# --------------------------------------------------------------------------- #
# Welcome and order confirmation (best effort)
# --------------------------------------------------------------------------- #
async def send_welcome(user: User) -> str:
    """Account-created email. Returns "sent", "failed" or "not_configured". Never raises."""
    name = _clean(user.first_name) or "there"
    limit = settings.free_monthly_limit
    text = (
        f"Hi {name},\n\n"
        f"Your TradeTrack account for {user.email} has been created. You are on the Free plan, which lets you "
        f"save up to {limit} receipts per month.\n\n"
        "To get started, upload a photo or PDF of a receipt. TradeTrack reads it, suggests an expense category "
        "and shows you every field to check and correct before anything is saved.\n\n"
        f"Open TradeTrack: {settings.frontend_origin}\n\n"
        "A note on suggestions: categories and tax details are suggestions, not tax advice. Please check with "
        "your accountant before claiming anything.\n\n"
        "If you did not create this account, you can ignore this email or reply to let us know.\n\n"
        "TradeTrack. Less paperwork. More business."
    )
    return await _best_effort(_message(user.email, "Welcome to TradeTrack", text), "Welcome")


def _payment_note(mode: str) -> str:
    if mode == "demo":
        return "This was the demo upgrade. No payment was taken and you were not charged."
    if settings.stripe_secret_key.strip().startswith("sk_test_"):
        return "TEST MODE: this site uses Stripe's test mode, so no real money was charged."
    return "Your payment was processed by Stripe."


async def send_upgrade_confirmation(user: User, mode: str) -> str:
    """Premium order confirmation. ``mode`` is "stripe" or "demo". Never raises."""
    price = plans.get_plans()["PREMIUM"].price_cad
    name = _clean(user.first_name) or "there"
    lines = [
        f"Hi {name},",
        "",
        "Your TradeTrack account is now on the Premium plan.",
        "",
        "Order summary",
        "  Plan:    TradeTrack Premium",
        f"  Price:   CAD {price} per month",
        f"  Account: {user.email}",
    ]
    if user.current_period_end:
        lines.append(f"  Current period ends: {user.current_period_end.date().isoformat()}")
    lines += [
        "",
        _payment_note(mode),
        "",
        "Premium includes unlimited saved receipts, summaries by month, quarter or year, the accountant "
        "package and exports.",
        f"Open TradeTrack: {settings.frontend_origin}",
        "",
        "TradeTrack. Less paperwork. More business.",
    ]
    msg = _message(user.email, "Your TradeTrack Premium confirmation", "\n".join(lines))
    return await _best_effort(msg, "Order confirmation")
