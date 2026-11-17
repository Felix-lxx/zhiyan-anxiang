"""Frozen human-action contract; reports never imply evidence verification."""


def freeze_workflow(world):
    world['task_workflow_version'] = 2 if world.get('community_training') else 1
    for task in world['tasks']:
        if requires_action_report(world, task):
            task['steps'] = ['接收责任任务', '回执到位并完成现场操作',
                             '报告动作结果并释放作业岗位', '提交核验证据并归档']


def requires_action_report(world, task):
    return world.get('task_workflow_version', 1) >= 2 and task.get('kind') in {'gas_off', 'power_off'}
