"""Standard case tasks and publication requirements share one contract."""
from sqlalchemy import select
from app.models.domain import DecisionPoint
from app.models.tasks import DecisionTask

STANDARD = {
    'night_charging_shed_fire': [('power_off', '切断充电棚电源', 90), ('broadcast', '机器人执行入口广播', 120),
                                ('escort', '疏散重点人员护送清点', 180)],
    'kitchen_fire': [('gas_off', '切断厨房燃气', 180), ('containment', '核验起火房门关闭', 180),
                     ('broadcast', '楼门广播与疏散', 180), ('escort', '重点人员护送清点', 180)],
}


def task_kind(title, kitchen=False):
    return ('gas_off' if kitchen and '燃气' in title else 'containment' if kitchen and '房门' in title
            else 'power_off' if '断电' in title or '切断' in title else 'broadcast' if '广播' in title
            else 'escort' if '重点' in title else 'manual')


def missing_tasks(session, version, code):
    kinds = {task_kind(t, code == 'kitchen_fire') for t in session.scalars(
        select(DecisionTask.title).where(DecisionTask.scene_version_id == version.id))}
    return [item for item in STANDARD.get(code, []) if item[0] not in kinds]


def ensure_standard_tasks(session, version, code):
    missing = missing_tasks(session, version, code)
    if not missing:
        return 0
    point = session.scalar(select(DecisionPoint).where(DecisionPoint.scene_version_id == version.id,
                                                    DecisionPoint.name == '案例标准处置'))
    if not point:
        point = DecisionPoint(scene_version_id=version.id, name='案例标准处置', trigger_condition='火情确认',
                              responsible_role='物业/网格员', time_limit_seconds=180)
        session.add(point); session.flush()
    for _, title, deadline in missing:
        session.add(DecisionTask(scene_version_id=version.id, decision_point_id=point.id, title=title,
                                target='按冻结火源、楼门及人员定位', deadline_seconds=deadline, status='pending'))
    session.flush()
    return len(missing)
