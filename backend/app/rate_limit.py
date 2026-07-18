"""
rate_limit.py — Compteurs de tentatives persistants (SQLite / PostgreSQL).

Remplace les dicts Python en mémoire : survivent aux redémarrages et restent
cohérents si plusieurs workers Uvicorn sont un jour activés.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, Integer, String, delete, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .database import Base, SessionLocal

logger = logging.getLogger(__name__)


class RateLimitHit(Base):
    __tablename__ = "rate_limit_hit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bucket: Mapped[str] = mapped_column(String(200), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )


class SchedulerLock(Base):
    __tablename__ = "scheduler_lock"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    holder: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime)


def _purge_old(session: Session, bucket: str, window_seconds: int) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
    session.execute(
        delete(RateLimitHit).where(
            RateLimitHit.bucket == bucket,
            RateLimitHit.created_at < cutoff,
        )
    )


def is_rate_limited(bucket: str, *, max_count: int, window_seconds: int) -> bool:
    with SessionLocal() as session:
        _purge_old(session, bucket, window_seconds)
        n = session.scalar(
            select(func.count()).select_from(RateLimitHit).where(RateLimitHit.bucket == bucket)
        ) or 0
        session.commit()
        return int(n) >= max_count


def record_hit(bucket: str, *, window_seconds: int = 3600) -> None:
    with SessionLocal() as session:
        session.add(RateLimitHit(bucket=bucket))
        _purge_old(session, bucket, window_seconds)
        session.commit()


def clear_bucket(bucket: str) -> None:
    with SessionLocal() as session:
        session.execute(delete(RateLimitHit).where(RateLimitHit.bucket == bucket))
        session.commit()


def try_acquire_scheduler_lock(name: str, holder: str, ttl_seconds: int = 300) -> bool:
    """Verrou soft en base : empêche deux workers de lancer le même cron."""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=ttl_seconds)
    with SessionLocal() as session:
        row = session.get(SchedulerLock, name)
        if row is None:
            session.add(SchedulerLock(name=name, holder=holder, expires_at=expires))
            session.commit()
            return True
        exp = row.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp > now and row.holder != holder:
            return False
        row.holder = holder
        row.expires_at = expires
        session.commit()
        return True


def release_scheduler_lock(name: str, holder: str) -> None:
    with SessionLocal() as session:
        row = session.get(SchedulerLock, name)
        if row and row.holder == holder:
            session.delete(row)
            session.commit()
