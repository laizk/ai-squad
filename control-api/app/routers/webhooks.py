"""Webhook ingestion — receives inbound GitHub webhook events.

Every accepted event is stored append-only in webhook_events.
HMAC-SHA256 signature verification is performed when GITHUB_WEBHOOK_SECRET
is set. If the secret is not configured, the check is skipped so local dev
works without a relay secret.

Relay setup (local dev):
  npm install --global smee-client
  smee --url https://smee.io/<your-channel> --target http://localhost:8000/webhooks/github

Then set that smee.io channel URL as the webhook URL in your GitHub App settings.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.db import open_ready_connection

logger = logging.getLogger(__name__)

GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "").strip()

router = APIRouter(prefix="/api/v1", tags=["webhooks"])


@router.post("/webhooks/github", status_code=status.HTTP_202_ACCEPTED)
async def ingest_github_webhook(
    request: Request,
    x_github_event: str | None = Header(default=None),
    x_github_delivery: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
) -> dict:
    body = await request.body()

    _verify_signature(body, x_hub_signature_256)

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook payload is not valid JSON.",
        )

    event_type = x_github_event or "unknown"
    raw_headers = {
        "x-github-event": x_github_event,
        "x-github-delivery": x_github_delivery,
        "x-hub-signature-256": x_hub_signature_256,
    }

    conn = await open_ready_connection()
    try:
        row = await conn.fetchrow(
            """
            INSERT INTO webhook_events
                   (source, event_type, delivery_id, payload, raw_headers)
            VALUES ('github', $1, $2, $3::jsonb, $4::jsonb)
            RETURNING id, received_at
            """,
            event_type,
            x_github_delivery,
            json.dumps(payload),
            json.dumps(raw_headers),
        )
    finally:
        await conn.close()

    logger.info(
        "Stored webhook event id=%s event_type=%s delivery_id=%s",
        row["id"],
        event_type,
        x_github_delivery,
    )
    return {"id": str(row["id"]), "event_type": event_type, "received_at": row["received_at"].isoformat()}


def _verify_signature(body: bytes, signature_header: str | None) -> None:
    if not GITHUB_WEBHOOK_SECRET:
        return
    if not signature_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Hub-Signature-256 header.",
        )
    expected = "sha256=" + hmac.new(
        GITHUB_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature_header):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Webhook signature mismatch.",
        )
