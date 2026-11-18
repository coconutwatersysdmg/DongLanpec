"""Display names for recorded worker IDs and the actual local controllers."""
AGENT_NAMES = {
    'project': '项目识别 Agent', 'conditions': '条件 Agent', 'elements': '材料 Agent',
    'nozzles': '管口 Agent', 'tube_structure': '结构参数 Agent', 'tube_bundle': '管束 Agent',
    'review_conditions': '原文复查 Agent', 'Orchestrator': '主控编排',
    'ReviewLoop': '审核规则服务', 'Fabric': '数据空间服务',
}


def agent_label(identity):
    return AGENT_NAMES.get(identity, 'Agent')+' · '+identity
