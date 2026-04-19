"""屯象OS tx-agent 成长教练 Agent：技能差距分析、培训推荐、个性化学习路径生成。"""

from __future__ import annotations

from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

from ..base import AgentResult, SkillAgent

logger = structlog.get_logger(__name__)


# ── 岗位技能矩阵 ─────────────────────────────────────────────────────────────

# 各岗位所需技能标签（晋升路径也用此矩阵）
_ROLE_SKILLS: dict[str, list[str]] = {
    "waiter": ["服务礼仪", "菜品知识", "点单操作", "客诉处理", "卫生规范"],
    "chef": ["刀工", "烹饪技术", "食品安全", "成本控制", "出品标准"],
    "cashier": ["收银操作", "支付方式", "会员系统", "对账结算", "基础服务"],
    "manager": ["团队管理", "排班调度", "成本分析", "客户关系", "合规管理", "数据分析", "培训带教"],
    "head_chef": ["菜品研发", "厨房管理", "供应链协调", "食品安全", "成本控制", "出品标准", "团队带教"],
}

# 晋升路径
_PROMOTION_PATH: dict[str, str] = {
    "waiter": "manager",
    "cashier": "manager",
    "chef": "head_chef",
}

# 培训课程库（简化）
_TRAINING_COURSES: list[dict[str, Any]] = [
    {
        "id": "TC001",
        "name": "服务礼仪与沟通",
        "skills": ["服务礼仪", "客诉处理"],
        "duration_hours": 8,
        "level": "basic",
    },
    {
        "id": "TC002",
        "name": "菜品知识深度学习",
        "skills": ["菜品知识", "出品标准"],
        "duration_hours": 12,
        "level": "basic",
    },
    {
        "id": "TC003",
        "name": "食品安全与卫生",
        "skills": ["食品安全", "卫生规范"],
        "duration_hours": 6,
        "level": "basic",
    },
    {
        "id": "TC004",
        "name": "收银系统操作",
        "skills": ["收银操作", "支付方式", "会员系统"],
        "duration_hours": 4,
        "level": "basic",
    },
    {
        "id": "TC005",
        "name": "门店管理基础",
        "skills": ["团队管理", "排班调度"],
        "duration_hours": 16,
        "level": "intermediate",
    },
    {
        "id": "TC006",
        "name": "成本分析与控制",
        "skills": ["成本分析", "成本控制"],
        "duration_hours": 12,
        "level": "intermediate",
    },
    {"id": "TC007", "name": "数据分析入门", "skills": ["数据分析"], "duration_hours": 10, "level": "intermediate"},
    {
        "id": "TC008",
        "name": "客户关系管理",
        "skills": ["客户关系", "客诉处理"],
        "duration_hours": 8,
        "level": "intermediate",
    },
    {
        "id": "TC009",
        "name": "培训带教方法",
        "skills": ["培训带教", "团队带教"],
        "duration_hours": 8,
        "level": "advanced",
    },
    {"id": "TC010", "name": "合规管理实务", "skills": ["合规管理"], "duration_hours": 6, "level": "advanced"},
    {"id": "TC011", "name": "菜品研发与创新", "skills": ["菜品研发"], "duration_hours": 16, "level": "advanced"},
    {
        "id": "TC012",
        "name": "厨房管理与协调",
        "skills": ["厨房管理", "供应链协调"],
        "duration_hours": 12,
        "level": "advanced",
    },
]

_LEVEL_ORDER = {"basic": 1, "intermediate": 2, "advanced": 3}


# ── 辅助函数 ─────────────────────────────────────────────────────────────────


def _identify_skill_gaps(
    current_skills: list[str],
    role: str,
    include_promotion: bool = True,
) -> dict[str, list[str]]:
    """识别技能差距：当前岗位要求 vs 员工已有技能。"""
    role_key = role.lower().strip()
    required = set(_ROLE_SKILLS.get(role_key, []))
    current_set = {s.strip() for s in current_skills}
    current_gaps = sorted(required - current_set)

    result: dict[str, list[str]] = {
        "current_role_gaps": current_gaps,
    }

    if include_promotion:
        next_role = _PROMOTION_PATH.get(role_key)
        if next_role:
            promotion_required = set(_ROLE_SKILLS.get(next_role, []))
            promotion_gaps = sorted(promotion_required - current_set)
            result["promotion_role"] = next_role
            result["promotion_gaps"] = promotion_gaps

    return result


def _match_courses(skill_gaps: list[str]) -> list[dict[str, Any]]:
    """匹配技能差距对应的培训课程，按难度排序。"""
    gap_set = set(skill_gaps)
    matched: list[dict[str, Any]] = []
    for course in _TRAINING_COURSES:
        overlap = gap_set & set(course["skills"])
        if overlap:
            matched.append(
                {
                    **course,
                    "matched_skills": sorted(overlap),
                    "relevance": len(overlap) / max(1, len(course["skills"])),
                }
            )
    matched.sort(key=lambda c: (_LEVEL_ORDER.get(c["level"], 99), -c["relevance"]))
    return matched


def _build_growth_plan(
    employee_name: str,
    role: str,
    gaps: dict[str, list[str]],
    courses: list[dict[str, Any]],
) -> dict[str, Any]:
    """生成个性化学习路径。"""
    phases: list[dict[str, Any]] = []

    # Phase 1: 补齐当前岗位技能
    current_gaps = gaps.get("current_role_gaps", [])
    current_courses = [c for c in courses if set(c["matched_skills"]) & set(current_gaps)]
    if current_courses:
        phases.append(
            {
                "phase": 1,
                "name": "岗位技能补齐",
                "description": f"补齐{role}岗位所需的基础技能",
                "courses": current_courses[:3],
                "estimated_hours": sum(c["duration_hours"] for c in current_courses[:3]),
            }
        )

    # Phase 2: 晋升技能准备
    promotion_gaps = gaps.get("promotion_gaps", [])
    promotion_role = gaps.get("promotion_role")
    if promotion_gaps and promotion_role:
        promo_courses = [c for c in courses if set(c["matched_skills"]) & set(promotion_gaps)]
        # 排除 Phase 1 已包含的
        phase1_ids = {c["id"] for c in (phases[0]["courses"] if phases else [])}
        promo_courses = [c for c in promo_courses if c["id"] not in phase1_ids]
        if promo_courses:
            phases.append(
                {
                    "phase": 2,
                    "name": f"晋升{promotion_role}准备",
                    "description": f"为晋升{promotion_role}岗位储备所需技能",
                    "courses": promo_courses[:4],
                    "estimated_hours": sum(c["duration_hours"] for c in promo_courses[:4]),
                }
            )

    total_hours = sum(p["estimated_hours"] for p in phases)
    return {
        "employee_name": employee_name,
        "current_role": role,
        "promotion_target": promotion_role,
        "phases": phases,
        "total_courses": sum(len(p["courses"]) for p in phases),
        "total_hours": total_hours,
        "estimated_weeks": max(1, total_hours // 8),
    }


# ── 数据查询 ─────────────────────────────────────────────────────────────────


async def _load_employee_skills(
    db: Any,
    tenant_id: str,
    employee_id: str,
) -> Optional[dict[str, Any]]:
    """读取员工技能标签和岗位信息。"""
    q = text("""
        SELECT e.id::text AS employee_id, e.emp_name, e.role,
               e.skill_tags, e.grade_level, e.training_completed,
               e.performance_score, e.seniority_months,
               e.store_id::text AS store_id
        FROM employees e
        WHERE e.tenant_id = CAST(:tenant_id AS uuid)
          AND e.id = CAST(:employee_id AS uuid)
          AND e.is_deleted = false
        LIMIT 1
    """)
    try:
        result = await db.execute(q, {"tenant_id": tenant_id, "employee_id": employee_id})
        row = result.mappings().first()
        return dict(row) if row else None
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("growth_load_employee_failed", error=str(exc))
        return None


async def _load_training_courses(
    db: Any,
    tenant_id: str,
) -> list[dict[str, Any]]:
    """从 training_courses 表查培训课程，降级为内置课程库。"""
    try:
        q = text("""
            SELECT id::text, name, skills, duration_hours, level
            FROM training_courses
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND COALESCE(is_deleted, false) = false
              AND COALESCE(is_active, true) = true
            ORDER BY level, name
            LIMIT 50
        """)
        result = await db.execute(q, {"tenant_id": tenant_id})
        rows = [dict(r) for r in result.mappings()]
        if rows:
            return rows
    except (OperationalError, ProgrammingError):
        pass
    # 降级为内置课程库
    return _TRAINING_COURSES


# ── Agent 类 ─────────────────────────────────────────────────────────────────


class GrowthCoachAgent(SkillAgent):
    """成长教练 Skill：技能差距分析、培训推荐、个性化学习路径生成。"""

    agent_id = "growth_coach"
    agent_name = "成长教练"
    description = "基于员工技能标签与岗位要求，识别技能差距并生成个性化培训路径"
    priority = "P2"
    run_location = "cloud"

    def get_supported_actions(self) -> list[str]:
        return [
            "analyze_skill_gaps",
            "recommend_training",
            "create_growth_plan",
            "menu_skill_match",
        ]

    def _store_scope(self, params: dict[str, Any]) -> Optional[str]:
        sid = params.get("store_id")
        if sid is not None and str(sid).strip():
            return str(sid).strip()
        if self.store_id is not None and str(self.store_id).strip():
            return str(self.store_id).strip()
        return None

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch: dict[str, Any] = {
            "analyze_skill_gaps": self._analyze_skill_gaps,
            "recommend_training": self._recommend_training,
            "create_growth_plan": self._create_growth_plan,
            "menu_skill_match": self._menu_skill_match,
        }
        handler = dispatch.get(action)
        if handler is None:
            return AgentResult(
                success=False,
                action=action,
                error=f"不支持的操作: {action}",
            )
        return await handler(params)

    async def _analyze_skill_gaps(self, params: dict[str, Any]) -> AgentResult:
        """分析技能差距。"""
        employee_id = params.get("employee_id")
        if not employee_id:
            return AgentResult(success=False, action="analyze_skill_gaps", error="缺少 employee_id")

        if not self._db:
            logger.warning("growth_gaps_no_db", tenant_id=self.tenant_id)
            return AgentResult(
                success=False,
                action="analyze_skill_gaps",
                error="数据库连接不可用",
            )

        emp = await _load_employee_skills(self._db, self.tenant_id, employee_id)
        if not emp:
            return AgentResult(
                success=False,
                action="analyze_skill_gaps",
                error=f"未找到员工 {employee_id}",
            )

        role = str(emp.get("role") or "waiter").lower()
        current_skills = emp.get("skill_tags") or []
        if isinstance(current_skills, str):
            current_skills = [s.strip() for s in current_skills.split(",") if s.strip()]

        gaps = _identify_skill_gaps(current_skills, role)
        emp_name = emp.get("emp_name") or employee_id

        return AgentResult(
            success=True,
            action="analyze_skill_gaps",
            data={
                "employee_name": emp_name,
                "employee_id": employee_id,
                "current_role": role,
                "current_skills": current_skills,
                "gaps": gaps,
                "gap_count": len(gaps.get("current_role_gaps", [])),
                "promotion_gap_count": len(gaps.get("promotion_gaps", [])),
            },
            reasoning=f"{emp_name}当前岗位技能差距{len(gaps.get('current_role_gaps', []))}项",
            confidence=0.88,
        )

    async def _recommend_training(self, params: dict[str, Any]) -> AgentResult:
        """推荐培训课程。"""
        skill_gaps = params.get("skill_gaps", [])
        if not skill_gaps:
            # 如果未直接传 skill_gaps，尝试从 employee_id 推导
            employee_id = params.get("employee_id")
            if employee_id and self._db:
                emp = await _load_employee_skills(self._db, self.tenant_id, employee_id)
                if emp:
                    role = str(emp.get("role") or "waiter").lower()
                    current_skills = emp.get("skill_tags") or []
                    if isinstance(current_skills, str):
                        current_skills = [s.strip() for s in current_skills.split(",") if s.strip()]
                    gaps = _identify_skill_gaps(current_skills, role)
                    skill_gaps = gaps.get("current_role_gaps", []) + gaps.get("promotion_gaps", [])

        if not skill_gaps:
            skill_gaps = ["菜品知识", "客诉处理"]  # fallback

        courses = _match_courses(skill_gaps)

        return AgentResult(
            success=True,
            action="recommend_training",
            data={
                "skill_gaps": skill_gaps,
                "recommended_courses": courses,
                "course_count": len(courses),
            },
            reasoning=f"基于{len(skill_gaps)}项技能差距推荐{len(courses)}门培训课程",
            confidence=0.82,
        )

    async def _create_growth_plan(self, params: dict[str, Any]) -> AgentResult:
        """创建完整成长计划。"""
        employee_id = params.get("employee_id")
        if not employee_id:
            return AgentResult(success=False, action="create_growth_plan", error="缺少 employee_id")

        if not self._db:
            logger.warning("growth_plan_no_db", tenant_id=self.tenant_id)
            return AgentResult(
                success=False,
                action="create_growth_plan",
                error="数据库连接不可用",
            )

        emp = await _load_employee_skills(self._db, self.tenant_id, employee_id)
        if not emp:
            return AgentResult(success=False, action="create_growth_plan", error=f"未找到员工 {employee_id}")

        role = str(emp.get("role") or "waiter").lower()
        emp_name = emp.get("emp_name") or employee_id
        current_skills = emp.get("skill_tags") or []
        if isinstance(current_skills, str):
            current_skills = [s.strip() for s in current_skills.split(",") if s.strip()]

        gaps = _identify_skill_gaps(current_skills, role)
        all_gaps = gaps.get("current_role_gaps", []) + gaps.get("promotion_gaps", [])
        courses = _match_courses(list(set(all_gaps)))
        plan = _build_growth_plan(emp_name, role, gaps, courses)

        return AgentResult(
            success=True,
            action="create_growth_plan",
            data=plan,
            reasoning=f"已为{emp_name}生成成长计划，共{plan['total_courses']}门课程，预计{plan['estimated_weeks']}周完成",
            confidence=0.85,
        )

    # ── 功能7：菜品技能匹配分析 ──────────────────────────────────────────────

    # 菜品分类 → 所需技能映射
    _CUISINE_SKILL_MAP: dict[str, list[str]] = {
        "粤菜": ["cantonese_cooking", "dim_sum", "seafood"],
        "川菜": ["sichuan_cooking", "spicy_wok", "hotpot"],
        "湘菜": ["hunan_cooking", "spicy_wok", "smoked_cured"],
        "日料": ["sashimi", "sushi", "tempura"],
        "西餐": ["steak_grill", "pasta", "sauce_making"],
        "烘焙": ["baking", "pastry", "dessert"],
        "火锅": ["hotpot_prep", "broth_cooking", "dipping_sauce"],
        "海鲜": ["seafood", "steaming", "live_prep"],
        "面点": ["noodle_making", "dumpling", "pastry"],
        "烧烤": ["grill", "marinating", "skewer"],
    }

    _SKILL_LABELS: dict[str, str] = {
        "cantonese_cooking": "粤菜烹饪",
        "dim_sum": "点心制作",
        "seafood": "海鲜处理",
        "sichuan_cooking": "川菜烹饪",
        "spicy_wok": "爆炒技术",
        "hotpot": "火锅制备",
        "hunan_cooking": "湘菜烹饪",
        "smoked_cured": "腊味烟熏",
        "sashimi": "刺身处理",
        "sushi": "寿司制作",
        "tempura": "天妇罗技术",
        "steak_grill": "牛排煎烤",
        "pasta": "意面制作",
        "sauce_making": "酱汁制作",
        "baking": "烘焙技术",
        "pastry": "糕点制作",
        "dessert": "甜品制作",
        "hotpot_prep": "火锅食材备料",
        "broth_cooking": "汤底熬制",
        "dipping_sauce": "蘸料调配",
        "steaming": "蒸制技术",
        "live_prep": "活鲜处理",
        "noodle_making": "面条制作",
        "dumpling": "饺子包子",
        "grill": "烧烤技术",
        "marinating": "腌制技术",
        "skewer": "串烤技术",
    }

    async def _menu_skill_match(self, params: dict[str, Any]) -> AgentResult:
        """菜品技能匹配分析

        当新菜品上线时：
        1. 将菜品要求映射为技能需求
        2. 扫描所有门店厨师的skill_tags
        3. 识别哪些门店缺少该技能
        4. 推荐培训/借调/招聘
        """
        cuisine_type = params.get("cuisine_type")
        dish_name = params.get("dish_name", "")
        store_ids = params.get("store_ids")  # 可选，不传则查全部
        if not cuisine_type:
            return AgentResult(
                success=False,
                action="menu_skill_match",
                error="缺少参数: cuisine_type（菜品分类）",
            )

        # 1. 映射技能需求
        required_skills = self._CUISINE_SKILL_MAP.get(cuisine_type, [])
        if not required_skills:
            return AgentResult(
                success=False,
                action="menu_skill_match",
                error=f"不支持的菜品分类: {cuisine_type}，支持: {list(self._CUISINE_SKILL_MAP.keys())}",
            )

        # 2. 扫描门店厨师技能
        store_coverage = await self._scan_store_chef_skills(required_skills, store_ids)

        # 3. 识别技能缺口
        gaps: list[dict[str, Any]] = []
        training_plans: list[dict[str, Any]] = []
        transferable_chefs: list[dict[str, Any]] = []

        for store in store_coverage:
            missing = store.get("missing_skills", [])
            if missing:
                gaps.append(
                    {
                        "store_id": store["store_id"],
                        "store_name": store["store_name"],
                        "missing_skills": missing,
                        "missing_labels": [self._SKILL_LABELS.get(s, s) for s in missing],
                        "gap_count": len(missing),
                        "action": "需要培训" if len(missing) <= 2 else "需要招聘",
                    }
                )
                # 为每个缺失技能匹配培训课程
                for skill in missing:
                    label = self._SKILL_LABELS.get(skill, skill)
                    training_plans.append(
                        {
                            "store_id": store["store_id"],
                            "store_name": store["store_name"],
                            "skill": skill,
                            "skill_label": label,
                            "course_name": f"{label}专项培训",
                            "target_trainees": store.get("chef_count", 0),
                            "estimated_hours": 16,
                        }
                    )

            # 收集可借调厨师
            for chef in store.get("qualified_chefs", []):
                transferable_chefs.append(
                    {
                        "employee_id": chef["employee_id"],
                        "emp_name": chef["emp_name"],
                        "store_id": store["store_id"],
                        "store_name": store["store_name"],
                        "matched_skills": chef.get("matched_skills", []),
                        "matched_labels": [self._SKILL_LABELS.get(s, s) for s in chef.get("matched_skills", [])],
                    }
                )

        # 构建热力图数据（门店 x 技能）
        heatmap: list[dict[str, Any]] = []
        for store in store_coverage:
            for skill in required_skills:
                count = store.get("skill_counts", {}).get(skill, 0)
                heatmap.append(
                    {
                        "store_id": store["store_id"],
                        "store_name": store["store_name"],
                        "skill": skill,
                        "skill_label": self._SKILL_LABELS.get(skill, skill),
                        "count": count,
                    }
                )

        data = {
            "cuisine_type": cuisine_type,
            "dish_name": dish_name,
            "required_skills": required_skills,
            "required_skill_labels": [self._SKILL_LABELS.get(s, s) for s in required_skills],
            "store_count": len(store_coverage),
            "gap_store_count": len(gaps),
            "store_gaps": gaps,
            "heatmap": heatmap,
            "training_plans": training_plans,
            "transferable_chefs": transferable_chefs,
            "ai_tag": "AI分析",
        }

        gap_pct = f"{len(gaps)}/{len(store_coverage)}" if store_coverage else "0/0"
        return AgentResult(
            success=True,
            action="menu_skill_match",
            data=data,
            reasoning=(
                f"分析{cuisine_type}{'(' + dish_name + ')' if dish_name else ''}所需技能，"
                f"覆盖{len(store_coverage)}家门店，"
                f"{gap_pct}家存在技能缺口，"
                f"可借调厨师{len(transferable_chefs)}人"
            ),
            confidence=0.80,
        )

    async def _scan_store_chef_skills(
        self,
        required_skills: list[str],
        store_ids: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """扫描门店厨师技能覆盖情况"""
        if self._db is not None:
            store_filter = ""
            params: dict[str, Any] = {"tenant_id": self.tenant_id}
            if store_ids:
                store_filter = "AND e.store_id = ANY(CAST(:store_ids AS uuid[]))"
                params["store_ids"] = store_ids

            q = text(f"""
                SELECT e.store_id::text, s.store_name,
                       e.id::text AS employee_id, e.emp_name,
                       e.skill_tags, e.role
                FROM employees e
                JOIN stores s ON s.id = e.store_id AND s.tenant_id = e.tenant_id
                WHERE e.tenant_id = CAST(:tenant_id AS uuid)
                  AND LOWER(e.role) IN ('chef', 'head_chef')
                  AND e.is_deleted = false
                  AND COALESCE(e.is_active, true) = true
                  {store_filter}
                ORDER BY s.store_name, e.emp_name
            """)
            try:
                result = await self._db.execute(q, params)
                rows = [dict(r) for r in result.mappings()]
                return self._aggregate_store_skills(rows, required_skills)
            except (OperationalError, ProgrammingError) as exc:
                logger.warning("menu_skill_scan_failed", error=str(exc))
                return []

        logger.warning("menu_skill_scan_no_db", tenant_id=self.tenant_id)
        return []

    @staticmethod
    def _aggregate_store_skills(
        rows: list[dict[str, Any]],
        required_skills: list[str],
    ) -> list[dict[str, Any]]:
        """将员工行数据聚合为门店级技能覆盖"""
        from collections import defaultdict

        store_map: dict[str, dict[str, Any]] = {}
        for r in rows:
            sid = r["store_id"]
            if sid not in store_map:
                store_map[sid] = {
                    "store_id": sid,
                    "store_name": r.get("store_name", ""),
                    "chefs": [],
                    "skill_counts": defaultdict(int),
                    "chef_count": 0,
                }
            tags = r.get("skill_tags") or []
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]

            store_map[sid]["chefs"].append(
                {
                    "employee_id": r["employee_id"],
                    "emp_name": r.get("emp_name", ""),
                    "skills": tags,
                }
            )
            store_map[sid]["chef_count"] += 1
            for tag in tags:
                store_map[sid]["skill_counts"][tag] += 1

        results: list[dict[str, Any]] = []
        for store in store_map.values():
            counts = store["skill_counts"]
            missing = [s for s in required_skills if counts.get(s, 0) == 0]
            qualified = []
            for chef in store["chefs"]:
                matched = [s for s in required_skills if s in chef["skills"]]
                if matched:
                    qualified.append(
                        {
                            "employee_id": chef["employee_id"],
                            "emp_name": chef["emp_name"],
                            "matched_skills": matched,
                        }
                    )
            results.append(
                {
                    "store_id": store["store_id"],
                    "store_name": store["store_name"],
                    "chef_count": store["chef_count"],
                    "skill_counts": dict(counts),
                    "missing_skills": missing,
                    "qualified_chefs": qualified,
                }
            )
        return results
