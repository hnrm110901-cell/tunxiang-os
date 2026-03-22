"""#7 巡店质检 Agent — P2 | 云端

来源：OpsAgent(11action) + ops_flow部分
能力：健康检查、故障诊断、Runbook、预测维护、食安状态

迁移自 tunxiang V2.x ops_agent.py
"""
from typing import Any
from ..base import SkillAgent, AgentResult


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
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "health_check": self._health_check,
            "diagnose_fault": self._diagnose_fault,
            "suggest_runbook": self._suggest_runbook,
            "predict_maintenance": self._predict_maintenance,
            "food_safety_status": self._food_safety,
        }
        handler = dispatch.get(action)
        if handler:
            return await handler(params)
        return AgentResult(success=True, action=action, data={"message": f"{action} ready"}, confidence=0.8)

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
