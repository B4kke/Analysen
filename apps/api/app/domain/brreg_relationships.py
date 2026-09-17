from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class BrregLegalRole(BaseModel):
    role_code: str
    role_description: str | None = None
    deregistered: bool = False
    sequence: int | None = None


class BrregLegalRoleOrganization(BaseModel):
    organization_number: str
    name: str | None = None
    roles: list[BrregLegalRole] = Field(default_factory=list)


class BrregLegalRoleLookup(BaseModel):
    subject_organization_number: str
    deleted: bool = False
    organizations: list[BrregLegalRoleOrganization] = Field(default_factory=list)
    next_search_after: str | None = None


class BrregOrganizationForm(BaseModel):
    code: str | None = None
    description: str | None = None


class BrregGroupRelationship(BaseModel):
    code: str | None = None
    description: str | None = None


class BrregGroupNode(BaseModel):
    level: int | None = None
    relationship: BrregGroupRelationship | None = None
    name: str | None = None
    organization_number: str
    parent_name: str | None = None
    parent_organization_number: str | None = None
    basis: str | None = None
    relationship_date: date | None = None
    organization_form: BrregOrganizationForm | None = None
    children: list[BrregGroupNode] = Field(default_factory=list)


class BrregGroupStructure(BaseModel):
    organization_number: str
    name: str | None = None
    organization_form: BrregOrganizationForm | None = None
    children: list[BrregGroupNode] = Field(default_factory=list)
