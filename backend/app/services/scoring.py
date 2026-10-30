"""Deterministic scoring for frozen exercise worlds.

The score is derived only from persisted domain events and the authoritative
simulation projection.  Keeping the calculation outside the HTTP route makes
previews, final reports and agent forecasts use the same rubric.
"""
from __future__ import annotations

from typing import Any


def score_frozen_world(world: dict[str, Any], history: list[Any], simulation: dict[str, Any]) -> dict[str, Any]:
    summary = simulation["summary"]
    residents = simulation["residents"]
    completed = {event.payload.get("task_id"): event for event in history if event.event_type == "task.completed"}
    total = max(1, summary["total"])
    alarm = next((event for event in history if event.event_type == "robot.alarm_confirmed"), None)
    acknowledgement = next(
        (event for event in history if event.event_type == "participant.acknowledge" and alarm and event.elapsed_seconds >= alarm.elapsed_seconds),
        None,
    )
    tasks = world.get("tasks", [])
    timely = sum(
        task["id"] in completed
        and alarm is not None
        and completed[task["id"]].elapsed_seconds - alarm.elapsed_seconds <= task["deadline_seconds"]
        for task in tasks
    )
    vulnerable = [person for person in residents if person["vulnerable"]]
    arrivals = [
        person.get("assembly_arrived_at_seconds", person.get("evacuated_at_seconds"))
        for person in residents
        if person.get("status") == "evacuated"
    ]
    arrivals = [int(value) for value in arrivals if value is not None]
    all_arrived = summary['total'] > 0 and summary['evacuated'] == summary['total'] and len(arrivals) == summary['total']
    completion_seconds = max(arrivals) if all_arrived else None
    indoor = world.get("parameters", {}).get("fire_source_type") == "kitchen" or bool(world.get("indoor_environment"))
    target_seconds = max(120, total * 3) + (40 if indoor else 0)
    reference = world.get('scoring_reference') or {}
    reference_applied = reference.get('version') == 1 and not reference.get('unreachable_resident_ids')
    if reference_applied:
        target_seconds = max(1, int(reference['target_seconds']))
    evacuated_ratio = min(1.0, summary["evacuated"] / total)
    if evacuated_ratio < 1:
        speed_score = round(6 * evacuated_ratio)
    elif all_arrived:
        delay = max(0, (completion_seconds or target_seconds) - target_seconds)
        speed_score = max(0, 6 - (delay + 14) // 15)
    else:
        speed_score = 0
    average_queue = round(sum(float(person.get("queue_seconds", 0)) for person in residents) / total, 1)
    # A stationary population has no queue, but has not demonstrated efficiency.
    queue_score = round(evacuated_ratio * max(0, 4 - max(0, int(average_queue) - 10 + 9) // 10))
    arrival_evidence = (f'全员到达 {completion_seconds} 秒' if all_arrived else
                        f"疏散未完成（已到达 {summary['evacuated']}/{summary['total']} 人）")
    assisted_score = 10 if not vulnerable else round(
        10 * sum(person["status"] == "evacuated" and person.get("assisted") for person in vulnerable) / len(vulnerable)
    )

    criteria = [
        ("疏散与清点", round((15 * summary["evacuated"] + 10 * summary.get("counted", summary["evacuated"])) / total), 25,
         "participant.resident_counted" if world.get("schema_version", 2) >= 3 else "resident.command",
         f"已到达 {summary['evacuated']}/{total} 人；已核验 {summary.get('counted', summary['evacuated'])}/{total} 人"),
        ("烟气与失联控制", max(0, round(20 * (1 - (summary["smoke_exposed"] + summary["missing"]) / total))), 20,
         "resident.command", f"暴露 {summary['smoke_exposed']} 人；失联 {summary['missing']} 人"),
        ("按时核验处置", round(20 * timely / max(1, len(tasks))), 20, "task.completed",
         f"按时完成 {timely}/{len(tasks)} 项，超时完成仍留证但不计此项"),
        ("重点人员护送", assisted_score, 10, "resident.command",
         "本场无重点人员，本项不扣分" if not vulnerable else "只计算护送会合后的真实到达，不按下达指令次数计分"),
        ("感知与响应", (5 if alarm else 0) + (5 if acknowledgement and acknowledgement.elapsed_seconds - alarm.elapsed_seconds <= 30 else 0),
         10, "robot.alarm_confirmed", "连续采样确认后 30 秒内回执告警"),
        ("决策效率", speed_score + queue_score, 10, "resident.command",
         f"{arrival_evidence}（参考 {target_seconds} 秒）；人均排队 {average_queue} 秒"),
        ("演练完整性", 5 if any(event.event_type == "drill.ended" for event in history) else 0, 5,
         "drill.ended", "场次结束并冻结结果"),
    ]
    details = [
        {
            "name": name,
            "score": value,
            "max_score": maximum,
            "evidence": explanation,
            "event_ids": [event.id for event in history if event.event_type == kind],
            "at_seconds": next((event.elapsed_seconds for event in reversed(history) if event.event_type == kind), 0),
        }
        for name, value, maximum, kind, explanation in criteria
    ]
    if world.get("outdoor_smoke_domain") == "exterior_v1":
        details[1]["evidence"] += "；本场为室外烟羽模型，暴露从进入室外通道累计，不模拟楼内渗透"
    if reference_applied:
        details[5]['evidence'] += '；参考时长来自冻结路网、楼梯速度与护送接近时间，不是全场预测'
    metrics = {
        "completion_seconds": completion_seconds,
        "target_seconds": target_seconds,
        "average_queue_seconds": average_queue,
        "evacuated": summary["evacuated"],
        "counted": summary.get("counted", summary["evacuated"]),
    }
    return {
        "version": 3,
        "total_score": sum(item["score"] for item in details),
        "details": details,
        "metrics": metrics,
        "recommendations": [item["name"] + "：" + item["evidence"] for item in details if item["score"] < item["max_score"]]
        or ["本轮所有结果指标已达标，可调整扰动重新验证。"],
    }
