"""
行动本体化服务（Action Ontology Service）

解决的问题：
  L5 行动层派发了动作，但"谁做了什么、结果如何"从未写入 Neo4j 知识图谱。
  这意味着跨店学习（L3）无法利用"哪些行动在哪种门店状态下有效"的历史模式。

本服务职责：
  L5 行动完成后 → 写入 Neo4j Action 节点
  → 建立关系：(Store)-[:TOOK_ACTION]->(Action)-[:RESULTED_IN]->(Outcome)
  → 若 outcome=success → 推送 LEARNED_PATTERN 到 L3 知识聚合层

节点结构：
  Action {
      action_id, store_id, action_type, description,
      expected_impact_yuan, actual_impact_yuan,
      outcome, confidence, executed_at
  }

  若同类行动在 ≥3 个门店均有效 → 升级为 LEARNED_PATTERN（跨店共享）
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, Optional

import structlog

logger = structlog.get_logger()


class ActionOntologyService:
    """
    行动本体化服务。

    Neo4j 不可用时静默降级（不影响主业务）。
    """

    def __init__(self):
        self._driver = None

    def _get_driver(self):
        if self._driver is not None:
            return self._driver
        try:
            from neo4j import GraphDatabase
            uri  = os.getenv("NEO4J_URI",     "bolt://localhost:7687")
            user = os.getenv("NEO4J_USER",    "neo4j")
            pwd  = os.getenv("NEO4J_PASSWORD", "")
            if not pwd:
                return None
            self._driver = GraphDatabase.driver(uri, auth=(user, pwd))
        except Exception as exc:
            logger.debug("action_ontology.neo4j_unavailable", error=str(exc))
        return self._driver

    def close(self):
        if self._driver:
            self._driver.close()
            self._driver = None

    def _run(self, cypher: str, params: Dict) -> None:
        driver = self._get_driver()
        if not driver:
            return
        try:
            with driver.session() as session:
                session.run(cypher, **params)
        except Exception as exc:
            logger.warning("action_ontology.cypher_failed", error=str(exc))

    # ── 公开方法 ──────────────────────────────────────────────────────────────

    def record_action(
        self,
        action_id:             str,
        store_id:              str,
        action_type:           str,
        description:           str,
        expected_impact_yuan:  float,
        executed_at:           datetime,
        confidence:            float = 0.0,
        actual_impact_yuan:    Optional[float] = None,
        outcome:               Optional[str] = None,
    ) -> None:
        """
        在 Neo4j 中创建/更新 Action 节点，并建立 Store-[:TOOK_ACTION]->Action 关系。

        调用时机：L5 行动派发完成后立即调用（不等待 outcome）。
        后续通过 record_outcome 补充结果。
        """
        self._run("""
            MERGE (a:Action {action_id: $action_id})
            SET a.store_id             = $store_id,
                a.action_type          = $action_type,
                a.description          = $description,
                a.expected_impact_yuan = $expected_impact_yuan,
                a.actual_impact_yuan   = $actual_impact_yuan,
                a.outcome              = $outcome,
                a.confidence           = $confidence,
                a.executed_at          = $executed_at

            WITH a
            MATCH (s:Store {store_id: $store_id})
            MERGE (s)-[:TOOK_ACTION {executed_at: $executed_at}]->(a)
        """, {
            "action_id":             action_id,
            "store_id":              store_id,
            "action_type":           action_type,
            "description":           description,
            "expected_impact_yuan":  expected_impact_yuan,
            "actual_impact_yuan":    actual_impact_yuan,
            "outcome":               outcome,
            "confidence":            confidence,
            "executed_at":           executed_at.isoformat(),
        })
        logger.debug("action_ontology.recorded", action_id=action_id, store_id=store_id)

    def record_outcome(
        self,
        action_id:          str,
        store_id:           str,
        outcome:            str,
        actual_impact_yuan: float,
        accuracy_ratio:     float,
    ) -> None:
        """
        补充行动结果到 Neo4j，并在效果良好时推广为跨店 LearnedPattern。

        accuracy_ratio ≥ 0.8（80% 兑现率）才写入 RESULTED_IN 关系。
        同类 action_type 在 ≥3 个门店均有效 → 升级为 LearnedPattern。
        """
        # 更新 Action 节点
        self._run("""
            MATCH (a:Action {action_id: $action_id})
            SET a.outcome            = $outcome,
                a.actual_impact_yuan = $actual_impact_yuan,
                a.accuracy_ratio     = $accuracy_ratio,
                a.result_recorded_at = $ts

            WITH a
            MATCH (s:Store {store_id: $store_id})
            MERGE (s)-[r:RESULTED_IN]->(a)
            SET r.outcome        = $outcome,
                r.accuracy_ratio = $accuracy_ratio
        """, {
            "action_id":          action_id,
            "store_id":           store_id,
            "outcome":            outcome,
            "actual_impact_yuan": actual_impact_yuan,
            "accuracy_ratio":     round(accuracy_ratio, 4),
            "ts":                 datetime.utcnow().isoformat(),
        })

        # 若效果良好，检查是否可升级为跨店 LearnedPattern
        if accuracy_ratio >= 0.8 and outcome == "success":
            self._try_promote_to_pattern(action_id, store_id, accuracy_ratio)

        logger.info(
            "action_ontology.outcome_recorded",
            action_id=action_id, outcome=outcome, accuracy_ratio=accuracy_ratio,
        )

    def _try_promote_to_pattern(
        self,
        action_id:      str,
        store_id:       str,
        accuracy_ratio: float,
    ) -> None:
        """
        统计同类 action_type 在不同门店的成功次数。
        ≥3 个门店成功 → 创建 LearnedPattern 节点（供 L3 跨店知识聚合使用）。
        """
        driver = self._get_driver()
        if not driver:
            return
        try:
            with driver.session() as session:
                rec = session.run("""
                    MATCH (a:Action {action_id: $action_id})
                    WITH a.action_type AS atype
                    MATCH (a2:Action {action_type: atype})
                    WHERE a2.outcome = 'success' AND a2.accuracy_ratio >= 0.8
                    WITH atype, COUNT(DISTINCT a2.store_id) AS success_store_count,
                         AVG(a2.accuracy_ratio) AS avg_accuracy,
                         AVG(a2.actual_impact_yuan) AS avg_impact_yuan
                    WHERE success_store_count >= 3
                    MERGE (p:LearnedPattern {action_type: atype})
                    SET p.success_store_count = success_store_count,
                        p.avg_accuracy        = avg_accuracy,
                        p.avg_impact_yuan     = avg_impact_yuan,
                        p.last_updated        = $ts
                    RETURN p.action_type AS promoted_type
                """, action_id=action_id, ts=datetime.utcnow().isoformat())
                record = rec.single()
                if record:
                    logger.info(
                        "action_ontology.pattern_promoted",
                        action_type=record["promoted_type"],
                    )
        except Exception as exc:
            logger.warning("action_ontology.promote_failed", error=str(exc))
