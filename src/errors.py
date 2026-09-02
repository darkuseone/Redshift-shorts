"""Коды ошибок и исключения REDSHIFT.

Каждая ошибка обязана иметь код: §10.5.4 запрещает молчаливую деградацию
качества, а §8.2 требует отклонять сценарий «с внятной ошибкой».
"""

from __future__ import annotations

from typing import Any


class RedshiftError(Exception):
    """Базовое исключение пайплайна. Всегда несёт машиночитаемый код."""

    code = "REDSHIFT_ERROR"

    def __init__(self, message: str, *, code: str | None = None, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.details: dict[str, Any] = details

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}

    def __str__(self) -> str:  # pragma: no cover - тривиально
        if self.details:
            return f"[{self.code}] {self.message} | {self.details}"
        return f"[{self.code}] {self.message}"


# --- P0: валидация сценария (§8.2) -------------------------------------------

class ValidationError(RedshiftError):
    code = "VALIDATION_ERROR"


class DurationOutOfRange(ValidationError):
    code = "DURATION_OUT_OF_RANGE"


class MissingHook(ValidationError):
    code = "MISSING_HOOK"


class MissingCta(ValidationError):
    code = "MISSING_CTA"


class HookUnanswered(ValidationError):
    code = "HOOK_UNANSWERED"


class QuoteTooLong(ValidationError):
    code = "QUOTE_TOO_LONG"


class NoSource(ValidationError):
    code = "NO_SOURCE"


class FillerWords(ValidationError):
    code = "FILLER_WORDS"


class FontMissingCyrillic(ValidationError):
    code = "FONT_MISSING_CYRILLIC"


class FontLicenseError(ValidationError):
    code = "FONT_LICENSE_FORBIDS_EMBEDDING"


class BudgetExceeded(RedshiftError):
    code = "BUDGET_EXCEEDED"


# --- P3: речь ----------------------------------------------------------------

class ScriptTooShort(RedshiftError):
    """§4.2.4 — после оптимизации речи ролик короче 35 сек."""

    code = "SCRIPT_TOO_SHORT"


# --- Внешние сервисы ---------------------------------------------------------

class ProviderError(RedshiftError):
    code = "PROVIDER_ERROR"


class ProviderUnavailable(ProviderError):
    code = "PROVIDER_UNAVAILABLE"


class MissingCredentials(ProviderError):
    code = "MISSING_CREDENTIALS"


class LimitReached(RedshiftError):
    """Лимит библиотеки/подписки достигнут (§14, §7.2.4)."""

    code = "LIMIT_REACHED"


class LibraryFrozen(LimitReached):
    code = "LIBRARY_FROZEN"


# --- QC ----------------------------------------------------------------------

class QCFailed(RedshiftError):
    """§11.1 — провал блокирующего QC. Ролик не выдаётся."""

    code = "QC_FAILED"


class RenderError(RedshiftError):
    code = "RENDER_ERROR"


class AssetError(RedshiftError):
    code = "ASSET_ERROR"


class LicenseError(AssetError):
    code = "LICENSE_UNCONFIRMED"


ALL_ERROR_CODES = sorted(
    {
        cls.code
        for cls in (
            RedshiftError, ValidationError, DurationOutOfRange, MissingHook, MissingCta,
            HookUnanswered, QuoteTooLong, NoSource, FontMissingCyrillic, FontLicenseError,
            BudgetExceeded, ScriptTooShort, ProviderError, ProviderUnavailable,
            MissingCredentials, LimitReached, LibraryFrozen, QCFailed, RenderError,
            AssetError, LicenseError,
        )
    }
    | {"MEME_IN_MEDICINE"}  # warning-код, не исключение (§8.2)
)
