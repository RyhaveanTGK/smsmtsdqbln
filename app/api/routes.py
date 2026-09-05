import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..auth import (
    clear_failed_logins,
    login_allowed,
    new_csrf_token,
    record_failed_login,
    require_admin,
    require_csrf,
    verify_admin,
)
from ..database import get_db
from ..models import AuditLog, Campaign, SMS, utcnow
from ..schemas import (
    CampaignCreateRequest,
    CampaignDetail,
    CampaignSummary,
    LoginRequest,
    ProgressResponse,
    SMSResult,
    ValidateContactsRequest,
)
from ..services.contacts import validate_numbers

router = APIRouter(prefix="/api")


def audit(db: Session, action: str, request: Request, campaign_id: str | None = None, details: dict | None = None) -> None:
    db.add(
        AuditLog(
            action=action,
            campaign_id=campaign_id,
            ip_address=request.client.host if request.client else None,
            details=json.dumps(details, ensure_ascii=False) if details else None,
        )
    )


def campaign_summary(campaign: Campaign) -> CampaignSummary:
    return CampaignSummary(
        id=campaign.id,
        created_at=campaign.created_at,
        message=campaign.message,
        total_numbers=campaign.total_numbers,
        sent_count=campaign.sent_count,
        failed_count=campaign.failed_count,
        pending_count=campaign.pending_count,
        status=campaign.status,
    )


def refresh_counts(db: Session, campaign: Campaign) -> None:
    rows = db.execute(
        select(SMS.status, func.count(SMS.id))
        .where(SMS.campaign_id == campaign.id)
        .group_by(SMS.status)
    ).all()
    counts = {str(status_name): int(count) for status_name, count in rows}
    campaign.total_numbers = sum(counts.values())
    campaign.sent_count = counts.get("sent", 0)
    campaign.failed_count = counts.get("failed", 0)
    campaign.pending_count = counts.get("pending", 0)
    if campaign.status == "running" and campaign.pending_count == 0 and counts.get("sending", 0) == 0:
        campaign.status = "completed"


@router.post("/auth/login")
async def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    key = f"{request.client.host if request.client else 'unknown'}:{payload.username[:100]}"
    if not login_allowed(key):
        raise HTTPException(status_code=429, detail="Çox sayda uğursuz cəhd. 15 dəqiqə sonra yenidən yoxlayın.")
    if not verify_admin(payload.username, payload.password):
        record_failed_login(key)
        raise HTTPException(status_code=401, detail="İstifadəçi adı və ya parol yanlışdır.")

    clear_failed_logins(key)
    request.session.clear()
    request.session["admin_authenticated"] = True
    request.session["csrf_token"] = new_csrf_token()
    audit(db, "LOGIN", request)
    db.commit()
    return {"authenticated": True}


@router.get("/auth/session")
async def session_status(_: None = Depends(require_admin)):
    return {"authenticated": True}


@router.get("/auth/csrf")
async def csrf_token(request: Request, _: None = Depends(require_admin)):
    token = request.session.get("csrf_token")
    if not token:
        token = new_csrf_token()
        request.session["csrf_token"] = token
    return {"csrf_token": token}


@router.post("/auth/logout")
async def logout(request: Request, db: Session = Depends(get_db), _: None = Depends(require_csrf)):
    audit(db, "LOGOUT", request)
    db.commit()
    request.session.clear()
    return {"authenticated": False}


@router.get("/dashboard/stats")
async def dashboard_stats(_: None = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.execute(select(Campaign)).scalars().all()
    return {
        "total_numbers": sum(row.total_numbers for row in rows),
        "sent": sum(row.sent_count for row in rows),
        "failed": sum(row.failed_count for row in rows),
        "pending": sum(row.pending_count for row in rows),
        "campaigns": len(rows),
    }


@router.post("/contacts/validate")
async def validate_contacts(
    payload: ValidateContactsRequest,
    _: None = Depends(require_csrf),
):
    result = validate_numbers(payload.numbers)
    return {
        "valid": result.valid,
        "invalid": result.invalid,
        "duplicates_removed": result.duplicates_removed,
        "input_count": result.input_count,
        "valid_count": len(result.valid),
        "invalid_count": len(result.invalid),
    }


@router.post("/campaigns", response_model=CampaignSummary)
async def create_campaign(
    payload: CampaignCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(require_csrf),
):
    result = validate_numbers(payload.phone_numbers)
    if result.invalid:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Siyahıda düzgün olmayan nömrələr var.",
                "invalid": result.invalid,
                "valid_count": len(result.valid),
                "duplicates_removed": result.duplicates_removed,
            },
        )
    if not result.valid:
        raise HTTPException(status_code=422, detail="Ən azı bir düzgün telefon nömrəsi daxil edin.")

    campaign = Campaign(
        message=payload.message,
        total_numbers=len(result.valid),
        pending_count=len(result.valid),
        status="pending",
    )
    db.add(campaign)
    db.flush()
    db.add_all(
        [
            SMS(campaign_id=campaign.id, phone_number=number, message=payload.message, status="pending")
            for number in result.valid
        ]
    )
    audit(
        db,
        "CAMPAIGN_CREATED",
        request,
        campaign.id,
        {"total_numbers": len(result.valid), "duplicates_removed": result.duplicates_removed},
    )
    db.commit()
    db.refresh(campaign)
    return campaign_summary(campaign)


@router.get("/campaigns", response_model=list[CampaignSummary])
async def list_campaigns(
    search: str | None = Query(default=None, max_length=32),
    status_filter: str | None = Query(default=None, alias="status", pattern="^(pending|running|paused|stopped|completed)$"),
    date_from: str | None = Query(default=None, max_length=10),
    date_to: str | None = Query(default=None, max_length=10),
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
):
    stmt = select(Campaign).order_by(Campaign.created_at.desc()).limit(200)
    if status_filter:
        stmt = stmt.where(Campaign.status == status_filter)
    if search:
        stmt = stmt.join(SMS, SMS.campaign_id == Campaign.id).where(SMS.phone_number.contains(search)).distinct()
    try:
        if date_from:
            start = datetime.strptime(date_from, "%Y-%m-%d")
            stmt = stmt.where(Campaign.created_at >= start)
        if date_to:
            end = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            stmt = stmt.where(Campaign.created_at < end)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Tarix YYYY-MM-DD formatında olmalıdır.") from exc
    campaigns = db.execute(stmt).scalars().unique().all()
    return [campaign_summary(campaign) for campaign in campaigns]


@router.get("/campaigns/{campaign_id}", response_model=CampaignDetail)
async def get_campaign(campaign_id: str, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    campaign = db.execute(
        select(Campaign).options(selectinload(Campaign.sms_messages)).where(Campaign.id == campaign_id)
    ).scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Kampaniya tapılmadı.")
    return CampaignDetail(
        **campaign_summary(campaign).model_dump(),
        sms_messages=[
            SMSResult(
                id=sms.id,
                phone_number=sms.phone_number,
                status=sms.status,
                error_message=sms.error_message,
                provider_response=json.loads(sms.provider_response) if sms.provider_response else None,
                created_at=sms.created_at,
                sent_at=sms.sent_at,
            )
            for sms in campaign.sms_messages
        ],
    )


async def change_campaign_status(
    campaign_id: str,
    target: str,
    action: str,
    request: Request,
    db: Session,
) -> CampaignSummary:
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Kampaniya tapılmadı.")
    allowed = {
        "start": {"pending", "paused"},
        "pause": {"running"},
        "resume": {"paused"},
        "stop": {"pending", "running", "paused"},
    }
    if campaign.status not in allowed[action]:
        raise HTTPException(status_code=409, detail=f"Bu əməliyyat üçün kampaniya statusu uyğun deyil: {campaign.status}.")
    campaign.status = target
    refresh_counts(db, campaign)
    audit_action = {
        "start": "CAMPAIGN_STARTED",
        "pause": "CAMPAIGN_PAUSED",
        "resume": "CAMPAIGN_RESUMED",
        "stop": "CAMPAIGN_STOPPED",
    }[action]
    audit(db, audit_action, request, campaign.id)
    db.commit()
    db.refresh(campaign)
    sms_worker = getattr(request.app.state, "sms_worker", None)
    if sms_worker:
        sms_worker.wake()
    return campaign_summary(campaign)


@router.post("/campaigns/{campaign_id}/start", response_model=CampaignSummary)
async def start_campaign(campaign_id: str, request: Request, db: Session = Depends(get_db), _: None = Depends(require_csrf)):
    return await change_campaign_status(campaign_id, "running", "start", request, db)


@router.post("/campaigns/{campaign_id}/pause", response_model=CampaignSummary)
async def pause_campaign(campaign_id: str, request: Request, db: Session = Depends(get_db), _: None = Depends(require_csrf)):
    return await change_campaign_status(campaign_id, "paused", "pause", request, db)


@router.post("/campaigns/{campaign_id}/resume", response_model=CampaignSummary)
async def resume_campaign(campaign_id: str, request: Request, db: Session = Depends(get_db), _: None = Depends(require_csrf)):
    return await change_campaign_status(campaign_id, "running", "resume", request, db)


@router.post("/campaigns/{campaign_id}/stop", response_model=CampaignSummary)
async def stop_campaign(campaign_id: str, request: Request, db: Session = Depends(get_db), _: None = Depends(require_csrf)):
    return await change_campaign_status(campaign_id, "stopped", "stop", request, db)


@router.get("/campaigns/{campaign_id}/progress", response_model=ProgressResponse)
async def campaign_progress(campaign_id: str, _: None = Depends(require_admin), db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Kampaniya tapılmadı.")
    refresh_counts(db, campaign)
    sending = db.scalar(
        select(func.count(SMS.id)).where(SMS.campaign_id == campaign.id, SMS.status == "sending")
    ) or 0
    db.commit()
    completed = campaign.sent_count + campaign.failed_count
    percentage = round((completed / campaign.total_numbers) * 100) if campaign.total_numbers else 0
    return ProgressResponse(
        campaign_id=campaign.id,
        total=campaign.total_numbers,
        sent=campaign.sent_count,
        failed=campaign.failed_count,
        pending=campaign.pending_count,
        sending=int(sending),
        percentage=percentage,
        status=campaign.status,
    )
