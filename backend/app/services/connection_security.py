"""Shared database-backed invitations, admission limits and single-use socket tickets."""
import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models.operations import ParticipantInvitation, SecurityRateWindow, SocketTicket


def aware(value):
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def normalize_code(code):
    return code.strip().replace("-", "").replace(" ", "").upper()


def invitation_for(session, drill_id, code):
    normalized = normalize_code(code)
    if len(normalized) != 32:
        raise HTTPException(404, "参演邀请已失效，请向导演获取新的链接。")
    invite = session.scalar(select(ParticipantInvitation).where(
        ParticipantInvitation.code_hash == digest(normalized),
        ParticipantInvitation.drill_session_id == drill_id,
        ParticipantInvitation.revoked_at.is_(None),
        ParticipantInvitation.expires_at > datetime.now(UTC),
    ))
    if not invite:
        raise HTTPException(404, "参演邀请已失效，请向导演获取新的链接。")
    return invite


def rate_limit(session, scope, subject, limit=60, seconds=60):
    """Atomic counter shared by all workers. Caller owns the transaction."""
    now = datetime.now(UTC)
    window = int(now.timestamp()) // seconds
    key = digest(f"{scope}:{subject}:{window}")
    session.execute(delete(SecurityRateWindow).where(SecurityRateWindow.expires_at < now - timedelta(minutes=5)))
    values = {"key": key, "count": 0, "expires_at": datetime.fromtimestamp((window + 1) * seconds, UTC)}
    dialect = session.get_bind().dialect.name
    # A savepoint around ``session.add`` is not enough for two requests sharing
    # the same time window: SQLite may defer the unique-key error until the
    # enclosing request transaction is flushed.  Let the database arbitrate
    # window creation, then conditionally increment the single durable row.
    if dialect == "sqlite":
        session.execute(sqlite_insert(SecurityRateWindow).values(**values).on_conflict_do_nothing(
            index_elements=[SecurityRateWindow.key]))
    elif dialect == "postgresql":
        session.execute(postgresql_insert(SecurityRateWindow).values(**values).on_conflict_do_nothing(
            index_elements=[SecurityRateWindow.key]))
    else:
        # Current supported deployments use SQLite or PostgreSQL. Keep a
        # portable path for development dialects without weakening the limit.
        existing = session.get(SecurityRateWindow, key)
        if existing is None:
            session.add(SecurityRateWindow(**values))
            session.flush()
    result = session.execute(update(SecurityRateWindow).where(
        SecurityRateWindow.key == key, SecurityRateWindow.count < limit,
    ).values(count=SecurityRateWindow.count + 1))
    if not result.rowcount:
        raise HTTPException(429, "请求过于频繁，请一分钟后重试。", headers={"Retry-After": str(seconds)})


def issue_ticket(session, drill_id, *, username=None, auth_session_id=None, invitation_id=None):
    now = datetime.now(UTC)
    session.execute(delete(SocketTicket).where(SocketTicket.expires_at < now))
    token = secrets.token_urlsafe(32)
    session.add(SocketTicket(token_hash=digest(token), drill_session_id=drill_id, username=username,
        auth_session_id=auth_session_id, invitation_id=invitation_id, expires_at=now + timedelta(seconds=30)))
    session.commit()
    return {"ticket": token, "expires_in": 30}


def consume_ticket(session, token, drill_id):
    ticket = session.get(SocketTicket, digest(token))
    if not ticket or ticket.drill_session_id != drill_id or aware(ticket.expires_at) <= datetime.now(UTC):
        raise HTTPException(401, "实时连接凭据已过期。")
    # The conditional delete is the atomic claim; two workers cannot reuse a ticket.
    claimed = session.execute(delete(SocketTicket).where(SocketTicket.token_hash == ticket.token_hash))
    session.commit()
    if not claimed.rowcount:
        raise HTTPException(401, "实时连接凭据已使用。")
    return ticket


def validate_ticket_owner(session, ticket):
    from app.api.routes.auth import _management_identity, _roles
    from app.models.auth import AuthSession
    from app.models.domain import User
    if ticket.username:
        user = session.scalar(select(User).where(User.username == ticket.username))
        if not user or not user.is_active:
            raise HTTPException(401, "账户已停用。")
        _management_identity(user, _roles(session, user), ticket.auth_session_id)
        if ticket.auth_session_id:
            record = session.get(AuthSession, ticket.auth_session_id)
            if not record or record.user_id != user.id or record.revoked_at or aware(record.expires_at) <= datetime.now(UTC):
                raise HTTPException(401, "登录会话已结束。")
    else:
        invite = session.get(ParticipantInvitation, ticket.invitation_id)
        if not invite or invite.revoked_at or aware(invite.expires_at) <= datetime.now(UTC):
            raise HTTPException(401, "参演邀请已撤销或到期。")
