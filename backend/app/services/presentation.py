"""Read-only labels and workspace filtering; recorded evidence is never rewritten."""
from sqlalchemy import or_

FIXTURE_MARKERS = ('实跑验收', 'UI 自动验收', '流程验收', '图册交互验收', '完整任务与智能体实跑', '完整决策验收')


def fixture_name(column):
    return or_(*(column.icontains(marker, autoescape=True) for marker in FIXTURE_MARKERS))


def drill_label(name, world):
    if world and world.get('parameters', {}).get('fire_source_type') == 'kitchen' and name == '安巷社区夜间充电棚火灾演练':
        return '安巷社区住宅厨房火灾演练'
    return name
