"""Shapes the LLM must return. Validated with pydantic; invalid output is retried on another model."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Skill(BaseModel):
    name: str
    importance: Literal["must", "nice"] = "must"
    aliases: list[str] = Field(default_factory=list)


class JDProfile(BaseModel):
    title: str
    company: str | None = None
    location: str | None = None
    work_mode: Literal["onsite", "hybrid", "remote", "unknown"] = "unknown"
    employment_type: str | None = None          # internship, full-time ...
    seniority: str | None = None                # intern, junior, mid ...
    duration: str | None = None
    stipend_or_salary: str | None = None
    eligibility: list[str] = Field(default_factory=list)   # batch, degree, CGPA ...
    responsibilities: list[str] = Field(default_factory=list)
    hard_skills: list[Skill] = Field(default_factory=list)
    soft_skills: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)       # other ATS phrases worth mirroring
    deadline: str | None = None
    apply_email: str | None = None
    red_flags: list[str] = Field(default_factory=list)
    interview_focus: list[str] = Field(default_factory=list)


class Revision(BaseModel):
    id: str
    new_text: str
    reason: str
    keywords_added: list[str] = Field(default_factory=list)


class RevisionSet(BaseModel):
    revisions: list[Revision]
    missing_skills: list[str] = Field(default_factory=list)   # in JD, absent from resume; never auto-added
    general_advice: list[str] = Field(default_factory=list)


class EmailDraft(BaseModel):
    subject: str
    body: str
    projects_used: list[str] = Field(default_factory=list)
