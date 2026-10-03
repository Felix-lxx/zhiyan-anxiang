from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import Role, RoleCode, User, UserRole


ROLE_CATALOG: dict[RoleCode, tuple[str, str]] = {
    RoleCode.SYSTEM_ADMIN: ("系统管理员", "维护账号、权限、模板和设备配置。"),
    RoleCode.EXERCISE_DESIGNER: ("演练设计员", "配置社区、场景、决策点和评分规则。"),
    RoleCode.DRILL_DIRECTOR: ("演练总控", "组织演练、监控态势并注入突发事件。"),
    RoleCode.COMMANDER: ("应急指挥人员", "判断火情、启动响应并调度资源。"),
    RoleCode.PROPERTY_STAFF: ("物业/网格员", "执行巡查、报警、断电和疏散引导任务。"),
    RoleCode.RESIDENT_REPRESENTATIVE: ("居民代表", "接收告警、执行疏散并完成集合签到。"),
    RoleCode.ASSESSOR: ("评估员", "查看评分证据、回放和复盘报告。"),
}


def ensure_role_catalog(session: Session) -> list[Role]:
    roles = list(session.scalars(select(Role).order_by(Role.code)))
    existing_codes = {role.code for role in roles}

    for code, (name, description) in ROLE_CATALOG.items():
        if code not in existing_codes:
            role = Role(code=code, name=name, description=description)
            session.add(role)
            roles.append(role)

    session.flush()
    return sorted(roles, key=lambda role: role.code.value)


def ensure_development_user(session: Session, username: str) -> User:
    user = session.scalar(select(User).where(User.username == username))
    roles = ensure_role_catalog(session)
    admin_role = next(role for role in roles if role.code == RoleCode.SYSTEM_ADMIN)
    if user is not None:
        existing = session.scalar(select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == admin_role.id))
        if existing is None:
            session.add(UserRole(user_id=user.id, role_id=admin_role.id))
            session.flush()
        return user

    user = User(username=username, display_name=username)
    session.add(user)
    session.flush()
    session.add(UserRole(user_id=user.id, role_id=admin_role.id))
    session.flush()
    return user
