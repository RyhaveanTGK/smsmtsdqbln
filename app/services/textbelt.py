from dataclasses import dataclass
from typing import Any

import httpx

from ..config import get_settings


@dataclass
class TextbeltResult:
    success: bool
    response: dict[str, Any]
    error: str | None = None


class TextbeltService:
    endpoint = "https://textbelt.com/text"

    def __init__(self) -> None:
        self.settings = get_settings()

    async def send_sms(self, phone: str, message: str) -> TextbeltResult:
        if not self.settings.textbelt_api_key:
            return TextbeltResult(
                success=False,
                response={"success": False, "error": "TEXTBELT_API_KEY konfiqurasiya edilməyib."},
                error="TEXTBELT_API_KEY konfiqurasiya edilməyib.",
            )

        try:
            async with httpx.AsyncClient(timeout=self.settings.textbelt_timeout) as client:
                response = await client.post(
                    self.endpoint,
                    data={
                        "phone": phone,
                        "message": message,
                        "key": self.settings.textbelt_api_key,
                    },
                )
            try:
                payload = response.json()
            except ValueError:
                payload = {"success": False, "error": "Textbelt gözlənilməyən cavab qaytardı."}

            if not isinstance(payload, dict):
                payload = {"success": False, "error": "Textbelt gözlənilməyən cavab qaytardı."}

            if response.is_success and payload.get("success") is True:
                # Never return or persist the configured API key.
                return TextbeltResult(success=True, response=payload)

            error = str(payload.get("error") or f"Textbelt HTTP {response.status_code}")
            return TextbeltResult(success=False, response=payload, error=error)
        except httpx.TimeoutException:
            return TextbeltResult(
                success=False,
                response={"success": False, "error": "Textbelt sorğusu vaxtı keçdi."},
                error="Textbelt sorğusu vaxtı keçdi.",
            )
        except httpx.HTTPError as exc:
            return TextbeltResult(
                success=False,
                response={"success": False, "error": "Textbelt şəbəkə xətası."},
                error=f"Textbelt şəbəkə xətası: {type(exc).__name__}",
            )
        except Exception:
            # Provider/network faults must never crash the worker.
            return TextbeltResult(
                success=False,
                response={"success": False, "error": "SMS provider ilə əlaqə qurulmadı."},
                error="SMS provider ilə əlaqə qurulmadı.",
            )
