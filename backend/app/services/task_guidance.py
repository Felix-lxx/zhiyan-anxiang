"""Explain a task from its authoritative projection, separately from references."""
from copy import deepcopy

TASK_QUERIES = {
    'power_off': '充电棚 切断电源 责任任务 到位 核验',
    'gas_off': '厨房 燃气 阀门 处置 核验 泄漏',
    'containment': '厨房 房门 撤空 控烟 通行 核验',
    'broadcast': '机器人 到位 广播 责任任务 核验',
    'escort': '重点人员 护送 会合 集合点 清点',
}


def guidance_view(data, task):
    """A query never assigns, advances, completes or scores an action."""
    status = task['status']
    completed = status == 'completed'
    can_submit = bool(task.get('can_submit')) and data['status'] == 'running' and not completed
    if completed:
        next_action = ('completed', '已核验，查看结果证据')
    elif data['status'] == 'ended':
        next_action = ('review', '本场已结束，核对冻结记录；新开训练后再处置')
    elif data['status'] == 'ready':
        next_action = ('wait', '等待组织者开始训练与确认火情')
    elif data['status'] == 'paused':
        next_action = ('resume', '时钟已暂停，继续训练后按任务步骤操作')
    elif status == 'waiting':
        next_action = ('wait', '等待服务端火情确认，不提前核验任务')
    elif status == 'pending':
        next_action = ('accept', '由指定执行人或对应角色参演者接收任务')
    elif status == 'executing':
        next_action = ('arrive', '核对实际位置后回执到位')
    elif can_submit:
        next_action = ('submit', '核对处置事实，填写证据后提交核验')
    else:
        next_action = ('wait', '先处理阻塞条件，再提交核验证据')
    blockers = list(task.get('blockers') or [])
    conditions = [
        {'id': 'trigger', 'label': '火情触发', 'met': status != 'waiting',
         'detail': '火情与任务状态来自本场事件和运行模型'},
        {'id': 'arrival', 'label': '到位回执', 'met': status in {'verifying', 'completed'},
         'detail': '到位由责任人回执，不代表仿真人物自动走到设备'},
        {'id': 'domain', 'label': '运行条件', 'met': completed or bool(task.get('verification_ready')),
         'detail': '；'.join(blockers) if blockers else '以本场设备、广播、护送与到场状态校验结果为准'},
        {'id': 'evidence', 'label': '证据核验', 'met': completed,
         'detail': '已保留本场核验证据' if completed else '仍需责任人确认处置事实并提交证据'},
    ]
    # The timestamp and sequence keep task facts distinct from general knowledge.
    return {'drill_id': data['id'], 'task_id': task['id'], 'observed_at_seconds': data['elapsed_seconds'],
            'event_sequence': data.get('latest_event_sequence', 0), 'drill_status': data['status'],
            'task': {key: deepcopy(task.get(key)) for key in ('id', 'title', 'kind', 'target', 'status',
                'responsible_role', 'assignee', 'assignee_id', 'verification_ready', 'can_submit',
                'target_device_id', 'target_floor', 'target_position', 'operation')},
            'next_action': {'kind': next_action[0], 'label': next_action[1]},
            'can_submit': can_submit, 'blockers': blockers, 'conditions': conditions,
            'steps': list(task.get('steps') or []),
            'query': TASK_QUERIES.get(task.get('kind'), task['title'])[:2000]}
