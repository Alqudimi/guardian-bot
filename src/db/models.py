"""
SQLAlchemy ORM models for persistent storage.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class ActionType(str, enum.Enum):
    ALLOW = "allow"
    SILENT_LOG = "silent_log"
    DELETE = "delete"
    WARN = "warn"
    MUTE_TEMP = "mute_temp"
    BAN_TEMP = "ban_temp"
    BAN_PERM = "ban_perm"
    ESCALATE = "escalate"
    RAID_LOCKDOWN = "raid_lockdown"
    SLOW_MODE = "slow_mode"
    MEDIA_RESTRICT = "media_restrict"
    LINK_RESTRICT = "link_restrict"


class ViolationCategory(str, enum.Enum):
    SPAM = "spam"
    FLOOD = "flood"
    TOXICITY = "toxicity"
    NSFW = "nsfw"
    PHISHING = "phishing"
    RAID = "raid"
    DUPLICATE = "duplicate"
    INVITE_ABUSE = "invite_abuse"
    MENTION_SPAM = "mention_spam"
    MEDIA_SPAM = "media_spam"
    OTHER = "other"


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str | None] = mapped_column(String(255))
    username: Mapped[str | None] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    raid_lockdown: Mapped[bool] = mapped_column(Boolean, default=False)
    slow_mode_active: Mapped[bool] = mapped_column(Boolean, default=False)
    settings: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    members: Mapped[list[GroupMember]] = relationship(back_populates="group")
    events: Mapped[list[ModerationEvent]] = relationship(back_populates="group")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(128))
    first_name: Mapped[str | None] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255))
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    account_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    memberships: Mapped[list[GroupMember]] = relationship(back_populates="user")


class GroupMember(Base):
    __tablename__ = "group_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("groups.id"), index=True)
    trust_score: Mapped[float] = mapped_column(Float, default=50.0)
    risk_index: Mapped[float] = mapped_column(Float, default=0.0)
    violation_count: Mapped[int] = mapped_column(Integer, default=0)
    warn_count: Mapped[int] = mapped_column(Integer, default=0)
    is_whitelisted: Mapped[bool] = mapped_column(Boolean, default=False)
    is_blacklisted: Mapped[bool] = mapped_column(Boolean, default=False)
    is_muted: Mapped[bool] = mapped_column(Boolean, default=False)
    mute_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="memberships")
    group: Mapped[Group] = relationship(back_populates="members")

    __table_args__ = (
        Index("ix_group_member_unique", "user_id", "group_id", unique=True),
    )


class ModerationEvent(Base):
    __tablename__ = "moderation_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("groups.id"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    message_text: Mapped[str | None] = mapped_column(Text)
    message_fingerprint: Mapped[str | None] = mapped_column(String(64))
    violation_category: Mapped[str] = mapped_column(
        Enum(ViolationCategory), default=ViolationCategory.OTHER
    )
    action_taken: Mapped[str] = mapped_column(Enum(ActionType))
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    toxicity_score: Mapped[float | None] = mapped_column(Float)
    nsfw_score: Mapped[float | None] = mapped_column(Float)
    spam_score: Mapped[float | None] = mapped_column(Float)
    link_risk_score: Mapped[float | None] = mapped_column(Float)
    behavioral_risk: Mapped[float | None] = mapped_column(Float)
    explanation: Mapped[str | None] = mapped_column(Text)
    signals: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    group: Mapped[Group] = relationship(back_populates="events")

    __table_args__ = (
        Index("ix_events_group_created", "group_id", "created_at"),
        Index("ix_events_user_created", "user_id", "created_at"),
    )


class DomainReputation(Base):
    __tablename__ = "domain_reputation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    domain: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    is_phishing: Mapped[bool] = mapped_column(Boolean, default=False)
    is_known_spam: Mapped[bool] = mapped_column(Boolean, default=False)
    labels: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    source: Mapped[str | None] = mapped_column(String(128))
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BlacklistedPattern(Base):
    __tablename__ = "blacklisted_patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pattern: Mapped[str] = mapped_column(Text)
    pattern_type: Mapped[str] = mapped_column(String(64))  # regex | literal | glob
    category: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
