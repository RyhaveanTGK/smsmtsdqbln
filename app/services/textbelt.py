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
                response={
                    "success": False,
                    "error": "TEXTBELT_API_KEY konfiqurasiya edilməyib.",
                },
                error="TEXTBELT_API_KEY konfiqurasiya edilməyib.",
            )
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.textbelt_timeout
            ) as client:
                response = await client.post(
                    self.endpoint,
                    data={
                        "phone": phone,
                        "message": message,
                        "key": self.settings.textbelt_api_key,
                    },
                )
            # Textbelt-in HTTP statusunu logla
            print(
                f"[TEXTBELT] HTTP STATUS: {response.status_code}",
                flush=True,
            )
            # JSON cavabı oxu
            try:
                payload = response.json()
            except ValueError:
                payload = {
                    "success": False,
                    "error": "Textbelt JSON olmayan cavab qaytardı.",
                    "raw_response": response.text[:1000],
                }
            # Cavab dict deyilsə
            if not isinstance(payload, dict):
                payload = {
                    "success": False,
                    "error": "Textbelt gözlənilməyən cavab qaytardı.",
                    "raw_response": str(payload)[:1000],
                }
            # VACİB:
            # API key heç vaxt loga çıxarılmır.
            print(
                f"[TEXTBELT] RESPONSE: {payload}",
                flush=True,
            )
            # Uğurlu Textbelt cavabı
            if response.is_success and payload.get("success") is True:
                text_id = payload.get("textId")
                if text_id:
                    print(
                        f"[TEXTBELT] SMS QƏBUL EDİLDİ | textId={text_id}",
                        flush=True,
                    )
                else:
                    print(
                        "[TEXTBELT] success=true gəldi, lakin textId yoxdur.",
                        flush=True,
                    )
                return TextbeltResult(
                    success=True,
                    response=payload,
                )
            # Textbelt error
            error = str(
                payload.get("error")
                or f"Textbelt HTTP {response.status_code}"
            )
            print(
                f"[TEXTBELT] SMS XƏTASI: {error}",
                flush=True,
            )
            return TextbeltResult(
                success=False,
                response=payload,
                error=error,
            )
        except httpx.TimeoutException:
            print(
                "[TEXTBELT] TIMEOUT: Textbelt sorğusunun vaxtı keçdi.",
                flush=True,
            )
            return TextbeltResult(
                success=False,
                response={
                    "success": False,
                    "error": "Textbelt sorğusu vaxtı keçdi.",
                },
                error="Textbelt sorğusu vaxtı keçdi.",
            )
        except httpx.HTTPError as exc:
            print(
                f"[TEXTBELT] HTTP NETWORK ERROR: {type(exc).__name__}",
                flush=True,
            )
            return TextbeltResult(
                success=False,
                response={
                    "success": False,
                    "error": "Textbelt şəbəkə xətası.",
                },
                error=f"Textbelt şəbəkə xətası: {type(exc).__name__}",
            )
        except Exception as exc:
            # Provider/network problemləri worker-i crash etdirməsin.
            print(
                f"[TEXTBELT] GÖZLƏNİLMƏYƏN XƏTA: {type(exc).__name__}",
                flush=True,
            )
            return TextbeltResult(
                success=False,
                response={
                    "success": False,
                    "error": "SMS provider ilə əlaqə qurulmadı.",
                },
                error="SMS provider ilə əlaqə qurulmadı.",
            )
