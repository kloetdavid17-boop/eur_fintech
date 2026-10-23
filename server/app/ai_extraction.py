from openai import OpenAI
from app.config import settings

client = OpenAI(api_key=settings.openai_api_key)

EXTRACTION_PROMPT = """You are extracting data from a Canadian business receipt image.
Return ONLY valid JSON matching this schema. Use null for anything not visible or unreadable.
Never invent values that aren't actually on the receipt.

{
  "merchant": string | null,
  "date": "YYYY-MM-DD" | null,
  "currency": string | null,
  "receipt_number": string | null,
  "line_items": [{"description": string, "quantity": number | null, "unit_price": number | null, "amount": number | null}],
  "subtotal": number | null,
  "taxes": [{"label": string, "amount": number}],
  "total": number | null,
  "suggested_category": string | null,
  "confidence": "high" | "medium" | "low"
}

Allowed categories: Tools and equipment, Building materials and supplies, Vehicle expenses and fuel,
Repairs and maintenance, Office supplies, Software and subscriptions, Telecommunications,
Travel and accommodation, Meals and entertainment, Professional services, Other business expenses.
"""

async def extract_receipt(image_bytes: bytes, mime_type: str) -> dict:
    import base64
    b64 = base64.b64encode(image_bytes).decode()
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": EXTRACTION_PROMPT},
                {"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}}
                ]},
            ],
            timeout=20,
        )
        import json
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        # surface as a clear processing-failed status, never fake success
        raise AIExtractionError(str(e))
