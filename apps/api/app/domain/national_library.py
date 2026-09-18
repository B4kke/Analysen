from typing import Any

from pydantic import BaseModel, Field


class NationalLibraryAccess(BaseModel):
    access_allowed_from: str | None = None
    is_digital: bool | None = None
    is_public_domain: bool | None = None
    legal_deposit_login_text: str | None = None
    license: str | None = None
    viewability: str | None = None

    def allows_content_capture(self) -> bool:
        """Return whether the adapter may persist OCR/image-derived content.

        The default is deliberately conservative: digitized + public-domain
        material only, with no legal-deposit login marker or geographic/library
        restriction in accessAllowedFrom.
        """
        if self.is_digital is not True or self.is_public_domain is not True:
            return False
        if self.legal_deposit_login_text:
            return False

        allowed_from = (self.access_allowed_from or "").strip().upper()
        if allowed_from and allowed_from not in {"EVERYWHERE", "ALL", "PUBLIC"}:
            return False

        viewability = (self.viewability or "").strip().upper()
        if viewability in {"NONE", "NO", "NOT_VIEWABLE", "RESTRICTED"}:
            return False
        return True


class NationalLibraryItem(BaseModel):
    identifier: str
    urn: str | None = None
    title: str | None = None
    creators: list[str] = Field(default_factory=list)
    media_types: list[str] = Field(default_factory=list)
    access: NationalLibraryAccess = Field(default_factory=NationalLibraryAccess)
    source_url: str
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class NationalLibraryContentFragment(BaseModel):
    page_id: str | None = None
    text: str
