import asyncio
from datetime import timedelta
import logging

from sqlalchemy import func, select, update

from ..config import get_settings
from ..database import SessionLocal
from ..models import Campaign, SMS, serialize_provider_response, utcnow
from ..services.textbelt import TextbeltService

logger = logging.getLogger(__name__)


class SMSWorker:
    """A single durable worker that sends at most one SMS per configured interval."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.provider = TextbeltService()
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()

    async def start(self) -> None:
        self._recover_interrupted_messages()
        while not self._stop_event.is_set():
            try:
                claimed = self._claim_next()
                if claimed is None:
                    try:
                        await asyncio.wait_for(self._wake_event.wait(), timeout=self.settings.send_worker_poll)
                    except asyncio.TimeoutError:
                        pass
                    self._wake_event.clear()
                    continue
                sms_id, phone, message = claimed
                result = await self.provider.send_sms(phone, message)
                self._finish(sms_id, result)
                # A delay after every provider call enforces the configured ceiling.
                await asyncio.sleep(self.settings.sms_delay)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("SMS worker iteration failed; retrying safely")
                await asyncio.sleep(self.settings.send_worker_poll)

    async def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()

    def wake(self) -> None:
        self._wake_event.set()

    def _recover_interrupted_messages(self) -> None:
        # A process can die after claiming a message. Returning stale claims to
        # pending makes a restart recover the queue instead of losing work.
        # The provider has no idempotency key; this small crash window is
        # documented in README as an unavoidable external-API limitation.
        with SessionLocal() as db:
            cutoff = utcnow() - timedelta(minutes=10)
            db.execute(
                update(SMS)
                .where(SMS.status == "sending", SMS.sending_started_at < cutoff)
                .values(status="pending", sending_started_at=None, error_message=None)
            )
            db.commit()

    def _claim_next(self) -> tuple[int, str, str] | None:
        with SessionLocal() as db:
            campaign = db.execute(
                select(Campaign)
                .where(Campaign.status == "running")
                .order_by(Campaign.created_at.asc())
                .with_for_update(skip_locked=True)
            ).scalars().first()
            if not campaign:
                return None
            sms = db.execute(
                select(SMS)
                .where(SMS.campaign_id == campaign.id, SMS.status == "pending")
                .order_by(SMS.id.asc())
                .with_for_update(skip_locked=True)
            ).scalars().first()
            if not sms:
                return None
            sms.status = "sending"
            sms.sending_started_at = utcnow()
            db.commit()
            return sms.id, sms.phone_number, sms.message

    def _finish(self, sms_id: int, result) -> None:
        with SessionLocal() as db:
            sms = db.get(SMS, sms_id)
            if not sms:
                return
            sms.status = "sent" if result.success else "failed"
            sms.provider_response = serialize_provider_response(result.response)
            sms.error_message = result.error
            sms.sent_at = utcnow() if result.success else None
            sms.sending_started_at = None
            campaign = db.get(Campaign, sms.campaign_id)
            if campaign:
                counts = dict(
                    db.execute(
                        select(SMS.status, func.count(SMS.id))
                        .where(SMS.campaign_id == campaign.id)
                        .group_by(SMS.status)
                    ).all()
                )
                campaign.sent_count = int(counts.get("sent", 0))
                campaign.failed_count = int(counts.get("failed", 0))
                campaign.pending_count = int(counts.get("pending", 0))
                if campaign.pending_count == 0 and counts.get("sending", 0) == 0 and campaign.status == "running":
                    campaign.status = "completed"
            db.commit()
