"""#7 巡店质检 Agent — P2 | 云端

来源：OpsAgent(11action) + ops_flow部分
能力：健康检查、故障诊断、Runbook、预测维护、食安状态

迁移自 tunxiang V2.x ops_agent.py
"""
from datetime import datetime, timezone
from typing import Any
import structlog
from ..base import SkillAgent, AgentResult

logger = structlog.get_logger(__name__)


RUNBOOK_DB = {
    "printer_jam": {"title": "打印机卡纸", "steps": ["1.关闭打印机电源", "2.打开上盖取出卡纸", "3.重新装纸合盖", "4.重启打印机"], "rollback": "联系商米售后"},
    "network_down": {"title": "网络断开", "steps": ["1.检查路由器电源灯", "2.重启路由器(等30秒)", "3.检查网线连接", "4.确认Mac mini可ping"], "rollback": "切换备用4G热点"},
    "pos_crash": {"title": "POS应用崩溃", "steps": ["1.强制关闭App", "2.清除WebView缓存", "3.重启App", "4.如仍崩溃重启设备"], "rollback": "使用备用设备"},
    "db_connection": {"title": "数据库连接失败", "steps": ["1.检查Mac mini运行状态", "2.检查PG服务: systemctl status postgresql", "3.重启PG服务", "4.检查磁盘空间"], "rollback": "切换到离线模式"},
    "scale_error": {"title": "电子秤异常", "steps": ["1.检查USB连接", "2.重启秤设备", "3.在商米设置中重新校准", "4.测试称重准确性"], "rollback": "手动输入重量"},
}

MAINTENANCE_SCHEDULE = {
    "printer": {"interval_days": 90, "task": "清洁打印头+检查走纸", "parts": ["热敏打印头", "走纸轮"]},
    "scale": {"interval_days": 180, "task": "校准称重精度", "parts": ["传感器"]},
    "kds_tablet": {"interval_days": 365, "task": "更换电池+系统更新", "parts": ["电池"]},
    "router": {"interval_days": 365, "task": "固件更新+安全检查", "parts": []},
    "ups": {"interval_days": 180, "task": "电池健康检测", "parts": ["UPS电池"]},
}


class StoreInspectAgent(SkillAgent):
    agent_id = "store_inspect"
    agent_name = "巡店质检"
    description = "门店IT健康检查、故障诊断、预测维护、食安巡检"
    priority = "P2"
    run_location = "cloud"

    def get_supported_actions(self) -> list[str]:
        return [
            "health_check", "diagnose_fault", "suggest_runbook",
            "predict_maintenance", "security_advice", "food_safety_status", "store_dashboard",
            "trigger_shift_checklist", "log_attendance_issue", "create_followup_task",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "health_check": self._health_check,
            "diagnose_fault": self._diagnose_fault,
            "suggest_runbook": self._suggest_runbook,
            "predict_maintenance": self._predict_maintenance,
            "food_safety_status": self._food_safety,
            "security_advice": self._security,
            "store_dashboard": self._dashboard,
            "trigger_shift_checklist": self._trigger_shift_checklist,
            "log_attendance_issue": self._log_attendance_issue,
            "create_followup_task": self._create_followup_task,
        }
        handler = dispatch.get(action)
        if handler:
            return await handler(params)
        return AgentResult(success=False, action=action, error=f"Unsupported: {action}")

    async def _health_check(self, params: dict) -> AgentResult:
        """三域健康检查：软件/硬件/网络"""
        devices = params.get("devices", {})

        software = {
            "mac_station": devices.get("mac_station_running", True),
            "sync_engine": devices.get("sync_engine_running", True),
            "coreml_bridge": devices.get("coreml_running", True),
        }
        hardware = {
            "printer": devices.get("printer_ok", True),
            "scale": devices.get("scale_ok", True),
            "cash_box": devices.get("cash_box_ok", True),
            "kds_tablet": devices.get("kds_ok", True),
        }
        network = {
            "internet": devices.get("internet_ok", True),
            "tailscale": devices.get("tailscale_ok", True),
            "local_lan": devices.get("lan_ok", True),
        }

        def domain_score(d: dict) -> int:
            if not d:
                return 0
            return round(sum(1 for v in d.values() if v) / len(d) * 100)

        scores = {"software": domain_score(software), "hardware": domain_score(hardware), "network": domain_score(network)}
        overall = round(sum(scores.values()) / 3)
        issues = []
        for domain, items in [("software", software), ("hardware", hardware), ("network", network)]:
            for k, v in items.items():
                if not v:
                    issues.append({"domain": domain, "component": k, "status": "down"})

        return AgentResult(
            success=True, action="health_check",
            data={"overall_score": overall, "domain_scores": scores, "issues": issues, "details": {"software": software, "hardware": hardware, "network": network}},
            reasoning=f"门店健康度 {overall}%，{len(issues)} 个问题",
            confidence=0.9,
        )

    async def _diagnose_fault(self, params: dict) -> AgentResult:
        """故障根因分析"""
        symptom = params.get("symptom", "")
        error_log = params.get("error_log", "")

        # 关键词匹配
        fault_map = {
            "打印": ("printer_jam", "打印机故障"),
            "网络": ("network_down", "网络连接问题"),
            "崩溃": ("pos_crash", "POS应用异常"),
            "数据库": ("db_connection", "数据库连接问题"),
            "秤": ("scale_error", "电子秤异常"),
        }

        matched = None
        for keyword, (fault_id, label) in fault_map.items():
            if keyword in symptom or keyword in error_log:
                matched = (fault_id, label)
                break

        if not matched:
            return AgentResult(
                success=True, action="diagnose_fault",
                data={"diagnosis": "unknown", "suggestion": "建议检查设备日志或联系技术支持"},
                reasoning="未能自动诊断，建议人工排查",
                confidence=0.4,
            )

        fault_id, label = matched
        runbook = RUNBOOK_DB.get(fault_id, {})

        return AgentResult(
            success=True, action="diagnose_fault",
            data={
                "fault_id": fault_id,
                "diagnosis": label,
                "runbook": runbook,
                "estimated_fix_minutes": 10,
            },
            reasoning=f"诊断结果：{label}，预计修复 10 分钟",
            confidence=0.8,
        )

    async def _suggest_runbook(self, params: dict) -> AgentResult:
        """Runbook 建议"""
        fault_id = params.get("fault_id", "")
        runbook = RUNBOOK_DB.get(fault_id)
        if not runbook:
            return AgentResult(success=False, action="suggest_runbook",
                             error=f"未知故障类型: {fault_id}，可选: {list(RUNBOOK_DB.keys())}")

        return AgentResult(
            success=True, action="suggest_runbook",
            data=runbook,
            reasoning=f"Runbook: {runbook['title']}，{len(runbook['steps'])} 步",
            confidence=0.95,
        )

    async def _predict_maintenance(self, params: dict) -> AgentResult:
        """预测性维护"""
        devices = params.get("devices", [])
        predictions = []

        for dev in devices:
            device_type = dev.get("type", "")
            last_maintained = dev.get("last_maintained_days_ago", 0)
            schedule = MAINTENANCE_SCHEDULE.get(device_type)
            if not schedule:
                continue

            days_overdue = last_maintained - schedule["interval_days"]
            urgency = "overdue" if days_overdue > 0 else "due_soon" if days_overdue > -30 else "ok"

            predictions.append({
                "device_type": device_type,
                "task": schedule["task"],
                "interval_days": schedule["interval_days"],
                "days_since_last": last_maintained,
                "days_overdue": max(0, days_overdue),
                "urgency": urgency,
                "spare_parts": schedule["parts"],
            })

        predictions.sort(key=lambda p: -p.get("days_overdue", 0))

        return AgentResult(
            success=True, action="predict_maintenance",
            data={"predictions": predictions, "total": len(predictions)},
            reasoning=f"{len([p for p in predictions if p['urgency'] != 'ok'])} 个设备需要维护",
            confidence=0.85,
        )

    async def _food_safety(self, params: dict) -> AgentResult:
        """食安合规状态"""
        violations = params.get("violations", [])
        total_inspections = params.get("total_inspections", 0)

        violation_count = len(violations)
        compliance_rate = (total_inspections - violation_count) / total_inspections * 100 if total_inspections > 0 else 100

        by_type = {}
        for v in violations:
            t = v.get("type", "other")
            by_type[t] = by_type.get(t, 0) + 1

        return AgentResult(
            success=True, action="food_safety_status",
            data={
                "compliance_rate_pct": round(compliance_rate, 1),
                "violation_count": violation_count,
                "total_inspections": total_inspections,
                "violations_by_type": by_type,
                "unresolved": [v for v in violations if not v.get("resolved")],
                "status": "critical" if compliance_rate < 90 else "warning" if compliance_rate < 95 else "good",
            },
            reasoning=f"食安合规率 {compliance_rate:.1f}%，{violation_count} 个违规",
            confidence=0.9,
        )

    async def _security(self, params: dict) -> AgentResult:
        issues = []
        if params.get("weak_passwords"): issues.append("弱密码需更换")
        if params.get("unauthorized_devices"): issues.append("发现未授权设备")
        if params.get("firmware_outdated"): issues.append("固件需更新")
        if not params.get("vpn_enabled", True): issues.append("VPN未启用")
        return AgentResult(success=True, action="security_advice",
                         data={"issues": issues, "total": len(issues),
                               "risk_level": "high" if len(issues) >= 3 else "medium" if issues else "low"},
                         reasoning=f"{len(issues)} 个安全风险", confidence=0.85)

    async def _dashboard(self, params: dict) -> AgentResult:
        return AgentResult(success=True, action="store_dashboard",
                         data={"software_score": params.get("sw", 100), "hardware_score": params.get("hw", 100),
                               "network_score": params.get("net", 100),
                               "overall": round((params.get("sw", 100) + params.get("hw", 100) + params.get("net", 100)) / 3)},
                         reasoning="门店健康总览", confidence=0.9)

    # ─── 事件驱动：班次交接质检清单 ───

    async def _trigger_shift_checklist(self, params: dict) -> AgentResult:
        """shift_handover / trade.daily_settlement.completed 触发：生成班次交接质检清单

        根据班次类型（早/晚班）生成不同的检查项，
        并将未完成项推送给当班人员，确保交接规范。
        """
        store_id = params.get("store_id") or self.store_id
        event_data = params.get("event_data", {})
        shift_type = params.get("shift_type") or event_data.get("shift_type", "day")
        shift_date = params.get("shift_date") or event_data.get("shift_date", "")
        handover_person = params.get("handover_person") or event_data.get("handover_person", "")

        # 通用交接检查项
        common_items = [
            {"id": "cash_count", "name": "现金盘点核对", "category": "financial", "required": True},
            {"id": "pos_settle", "name": "POS日结/班结操作", "category": "financial", "required": True},
            {"id": "receipt_print", "name": "打印交接单", "category": "financial", "required": True},
            {"id": "fridge_temp", "name": "冰箱温度记录（≤4°C）", "category": "food_safety", "required": True},
            {"id": "surface_clean", "name": "台面/地面清洁检查", "category": "hygiene", "required": True},
            {"id": "waste_bin", "name": "垃圾桶清理", "category": "hygiene", "required": True},
            {"id": "stock_check", "name": "关键食材盘点", "category": "inventory", "required": True},
            {"id": "device_status", "name": "设备状态确认（POS/打印机/秤）", "category": "equipment", "required": True},
        ]

        # 晚班额外项
        night_only_items = [
            {"id": "door_lock", "name": "门窗上锁检查", "category": "security", "required": True},
            {"id": "gas_off", "name": "燃气总阀关闭确认", "category": "safety", "required": True},
            {"id": "light_off", "name": "非必要照明关闭", "category": "energy", "required": False},
            {"id": "cash_safe", "name": "营业款存入保险柜", "category": "financial", "required": True},
            {"id": "data_backup", "name": "确认 Mac mini 同步完成", "category": "data", "required": True},
        ]

        checklist = common_items.copy()
        if shift_type in ("night", "closing"):
            checklist.extend(night_only_items)

        required_count = sum(1 for item in checklist if item["required"])

        checklist_id = f"CHK-{store_id[:8] if store_id else 'STORE'}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

        logger.info(
            "shift_checklist_triggered",
            store_id=store_id,
            shift_type=shift_type,
            shift_date=shift_date,
            checklist_id=checklist_id,
            total_items=len(checklist),
        )

        return AgentResult(
            success=True,
            action="trigger_shift_checklist",
            data={
                "checklist_id": checklist_id,
                "store_id": store_id,
                "shift_type": shift_type,
                "shift_date": shift_date,
                "handover_person": handover_person,
                "checklist": checklist,
                "total_items": len(checklist),
                "required_items": required_count,
                "status": "pending",
                "triggered_at": datetime.now(timezone.utc).isoformat(),
            },
            reasoning=(
                f"{shift_date} {shift_type}班质检清单已触发：{len(checklist)}项（必填{required_count}项）"
            ),
            confidence=0.95,
        )

    # ─── 事件驱动：记录考勤问题 ───

    async def _log_attendance_issue(self, params: dict) -> AgentResult:
        """org.attendance.late 触发：记录迟到事件，评估影响等级

        将考勤事件结构化记录，并根据频次判断是否需要升级处理。
        实际写 DB 由 tx-org service 负责；Agent 做分析和建议。
        """
        store_id = params.get("store_id") or self.store_id
        event_data = params.get("event_data", {})
        employee_id = params.get("employee_id") or event_data.get("employee_id")
        employee_name = params.get("employee_name") or event_data.get("employee_name", "")
        scheduled_time = params.get("scheduled_time") or event_data.get("scheduled_time", "")
        actual_time = params.get("actual_time") or event_data.get("actual_time", "")
        late_minutes = params.get("late_minutes") or event_data.get("late_minutes", 0)
        late_count_this_month = params.get("late_count_this_month") or event_data.get("late_count_this_month", 1)
        role = params.get("role") or event_data.get("role", "staff")

        # 严重程度评估
        severity = (
            "critical" if late_minutes > 60 or late_count_this_month >= 5 else
            "high" if late_minutes > 30 or late_count_this_month >= 3 else
            "medium" if late_minutes > 15 or late_count_this_month >= 2 else
            "low"
        )

        # 影响评估（关键岗位迟到影响更大）
        critical_roles = {"manager", "chef", "cashier"}
        operational_impact = role in critical_roles

        recommended_actions = []
        if severity in ("critical", "high"):
            recommended_actions.append("通知直属上级")
        if late_count_this_month >= 3:
            recommended_actions.append("启动考勤约谈流程")
        if operational_impact:
            recommended_actions.append("安排临时顶岗，避免运营影响")
        if late_minutes > 0:
            recommended_actions.append(f"按制度扣除{min(late_minutes // 10, 3)}分绩效分")

        issue_id = f"ATT-{employee_id or 'EMP'}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

        logger.info(
            "attendance_issue_logged",
            store_id=store_id,
            employee_id=employee_id,
            late_minutes=late_minutes,
            late_count_this_month=late_count_this_month,
            severity=severity,
        )

        return AgentResult(
            success=True,
            action="log_attendance_issue",
            data={
                "issue_id": issue_id,
                "store_id": store_id,
                "employee_id": employee_id,
                "employee_name": employee_name,
                "role": role,
                "scheduled_time": scheduled_time,
                "actual_time": actual_time,
                "late_minutes": late_minutes,
                "late_count_this_month": late_count_this_month,
                "severity": severity,
                "operational_impact": operational_impact,
                "recommended_actions": recommended_actions,
                "logged_at": datetime.now(timezone.utc).isoformat(),
            },
            reasoning=(
                f"考勤问题记录：{employee_name or employee_id} 迟到{late_minutes}分钟，"
                f"本月第{late_count_this_month}次，严重度={severity}"
            ),
            confidence=0.95,
        )

    # ─── 事件驱动：创建跟进任务 ───

    async def _create_followup_task(self, params: dict) -> AgentResult:
        """org.attendance.exception 触发：针对考勤异常创建跟进任务

        将需要人工介入的考勤异常自动转化为结构化任务，
        分配给对应责任人并设置截止时间。
        """
        store_id = params.get("store_id") or self.store_id
        event_data = params.get("event_data", {})
        exception_type = params.get("exception_type") or event_data.get("exception_type", "attendance_anomaly")
        employee_id = params.get("employee_id") or event_data.get("employee_id")
        employee_name = params.get("employee_name") or event_data.get("employee_name", "")
        exception_detail = params.get("exception_detail") or event_data.get("exception_detail", "")
        assigned_to = params.get("assigned_to") or event_data.get("assigned_to", "store_manager")

        # 按异常类型生成任务模板
        task_templates = {
            "absence": {
                "title": f"处理{employee_name or '员工'}旷工异常",
                "description": "核实旷工原因，按制度处理，更新考勤台账",
                "due_hours": 24,
                "priority": "high",
            },
            "overtime_exception": {
                "title": f"核查{employee_name or '员工'}超时加班",
                "description": "确认加班是否获授权，核算加班费，更新排班",
                "due_hours": 48,
                "priority": "medium",
            },
            "late_repeat": {
                "title": f"约谈{employee_name or '员工'}多次迟到",
                "description": "与员工面谈了解情况，说明制度，制定改善计划",
                "due_hours": 72,
                "priority": "medium",
            },
            "attendance_anomaly": {
                "title": f"跟进{employee_name or '员工'}考勤异常",
                "description": f"异常详情：{exception_detail or '待核实'}",
                "due_hours": 48,
                "priority": "medium",
            },
        }

        template = task_templates.get(exception_type, task_templates["attendance_anomaly"])
        task_id = f"TASK-{store_id[:8] if store_id else 'STORE'}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

        from datetime import timedelta
        due_at = (
            datetime.now(timezone.utc) + timedelta(hours=template["due_hours"])
        ).isoformat()

        logger.info(
            "followup_task_created",
            store_id=store_id,
            task_id=task_id,
            exception_type=exception_type,
            employee_id=employee_id,
            assigned_to=assigned_to,
        )

        return AgentResult(
            success=True,
            action="create_followup_task",
            data={
                "task_id": task_id,
                "store_id": store_id,
                "title": template["title"],
                "description": template["description"],
                "exception_type": exception_type,
                "employee_id": employee_id,
                "employee_name": employee_name,
                "assigned_to": assigned_to,
                "priority": template["priority"],
                "due_at": due_at,
                "status": "open",
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            reasoning=(
                f"跟进任务已创建：{template['title']}，"
                f"分配给{assigned_to}，{template['due_hours']}小时内处理"
            ),
            confidence=0.9,
        )
