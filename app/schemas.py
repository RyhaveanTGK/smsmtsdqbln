from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class ValidateContactsRequest(BaseModel):
    numbers: list[str] = Field(min_length=1, max_length=10_000)


class CampaignCreateRequest(BaseModel):
    message: str = Field(min_length=1, max_length=140)
    phone_numbers: list[str] = Field(min_length=1, max_length=10_000)

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Mesaj boş ola bilməz.")
        return value


class CampaignSummary(BaseModel):
    id: str
    created_at: datetime
    message: str
    total_numbers: int
    sent_count: int
    failed_count: int
    pending_count: int
    status: str


class SMSResult(BaseModel):
    id: int
    phone_number: str
    status: str
    error_message: str | None = None
    provider_response: Any = None
    created_at: datetime
    sent_at: datetime | None = None


class CampaignDetail(CampaignSummary):
    sms_messages: list[SMSResult]


class ProgressResponse(BaseModel):
    campaign_id: str
    total: int
    sent: int
    failed: int
    pending: int
    sending: int
    percentage: int
    status: str
