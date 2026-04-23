"""语音盘点 API — Voice Inventory Count

移动端将ASR识别结果发到此接口，系统解析商品名/数量/单位，
模糊匹配物料库，返回识别结果供用户确认后提交正式盘点单。

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。

端点清单：
  ── 盘点会话管理 ──────────────────────────────────────────────────────────────
  POST   /api/v1/supply/voice-count/sessions                       — 创建盘点会话
  GET    /api/v1/supply/voice-count/sessions/{session_id}          — 会话状态
  POST   /api/v1/supply/voice-count/sessions/{session_id}/close    — 关闭会话（不提交）

  ── 语音录入 ──────────────────────────────────────────────────────────────────
  POST   /api/v1/supply/voice-count/sessions/{session_id}/voice-entry    — 语音识别提交
  POST   /api/v1/supply/voice-count/sessions/{session_id}/entries        — 确认/修正录入
  GET    /api/v1/supply/voice-count/sessions/{session_id}/entries        — 当前录入列表
  DELETE /api/v1/supply/voice-count/sessions/{session_id}/entries/{id}   — 删除录入

  ── 盘点分析与提交 ────────────────────────────────────────────────────────────
  GET    /api/v1/supply/voice-count/sessions/{session_id}/variance  — 差异分析
  POST   /api/v1/supply/voice-count/sessions/{session_id}/submit    — 提交盘点单
"""

import asyncio
import difflib
import json
import re
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import InventoryEventType
from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/supply/voice-count", tags=["voice-count"])


# ─── 工具函数 ─────────────────────────────────────────────────────────────────


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> None:
    raise HTTPException(
        status_code=code,
        detail={"ok": False, "data": None, "error": {"message": msg}},
    )


# ─── NLP语音盘点解析（B2 核心函数）─────────────────────────────────────────────

# 中文数字映射
_CN_DIGIT_MAP = {
    "零": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "百": 100,
    "千": 1000,
    # 兼容大写数字
    "壹": 1,
    "贰": 2,
    "叁": 3,
    "肆": 4,
    "伍": 5,
    "陆": 6,
    "柒": 7,
    "捌": 8,
    "玖": 9,
    "拾": 10,
    "佰": 100,
}

# 支持的计量单位（按优先级排列）
_UNITS = [
    "公斤",
    "千克",
    "克",
    "斤",
    "两",  # 重量
    "升",
    "毫升",
    "斤",  # 体积
    "箱",
    "件",
    "包",
    "袋",
    "瓶",
    "桶",
    "罐",
    "盒",  # 包装
    "个",
    "只",
    "条",
    "块",
    "片",
    "颗",
    "粒",
    "根",  # 计件
    "份",  # 份量
]

# 单位标准化映射
_UNIT_NORMALIZE = {
    "千克": "公斤",
    "克": "克",
    "两": "两",
}

_UNIT_PATTERN = "|".join(re.escape(u) for u in _UNITS)


def _cn_number_to_float(cn_str: str) -> Optional[float]:
    """将中文数字字符串转为浮点数。
    支持：三十五、十二、一百二十、二百五十五点五 等形式。
    """
    if not cn_str:
        return None

    # 处理小数点（中文"点"）
    if "点" in cn_str:
        parts = cn_str.split("点", 1)
        integer_part = _cn_integer_to_int(parts[0])
        if integer_part is None:
            return None
        decimal_str = parts[1]
        decimal_val = 0.0
        for i, ch in enumerate(decimal_str):
            digit = _CN_DIGIT_MAP.get(ch)
            if digit is None:
                break
            decimal_val += digit * (10 ** (-(i + 1)))
        return float(integer_part) + decimal_val

    result = _cn_integer_to_int(cn_str)
    return float(result) if result is not None else None


def _cn_integer_to_int(cn_str: str) -> Optional[int]:
    """将中文整数字符串转为整数。"""
    if not cn_str:
        return None

    # 全是阿拉伯数字，直接返回
    try:
        return int(cn_str)
    except ValueError:
        pass

    # 含有中文数字
    result = 0
    current = 0
    prev_unit = 1

    # 处理 "十x" 简写（如"十二"=12，"十"=10）
    if cn_str.startswith("十"):
        cn_str = "一" + cn_str

    for ch in cn_str:
        if ch in ("十", "拾"):
            if current == 0:
                current = 1
            result += current * 10
            current = 0
            prev_unit = 10
        elif ch in ("百", "佰"):
            if current == 0:
                current = 1
            result += current * 100
            current = 0
            prev_unit = 100
        elif ch in ("千",):
            if current == 0:
                current = 1
            result += current * 1000
            current = 0
            prev_unit = 1000
        else:
            digit = _CN_DIGIT_MAP.get(ch)
            if digit is not None:
                current = digit
            else:
                return None  # 无法识别

    result += current
    return result if result > 0 else None


def parse_voice_inventory_text(raw_text: str, item_list: list) -> dict:
    """解析语音盘点文本，提取商品名/数量/单位，并模糊匹配物料库。

    算法：
      1. 用正则从文本中提取数字（支持阿拉伯数字和中文数字）
      2. 提取紧跟数字后的计量单位
      3. 文本剩余部分作为商品名候选
      4. 用 difflib.get_close_matches 对物料库做模糊匹配
      5. 根据匹配置信度返回 high/medium/low

    Args:
        raw_text: ASR原始文字，如"五花肉三十五点五公斤"、"鸡蛋30个"
        item_list: 物料列表，每项需包含 {item_id, item_name, unit}

    Returns:
        {
            recognized: bool,
            item_id: str | None,
            item_name: str | None,
            quantity: float | None,
            unit: str | None,
            confidence_level: "high" | "medium" | "low",
            alternatives: [...],
            parse_detail: {...}
        }
    """
    text = raw_text.strip()

    # ── 步骤1：提取数量 ───────────────────────────────────────────────────────
    quantity: Optional[float] = None
    unit: Optional[str] = None
    name_candidate = text

    # 先尝试阿拉伯数字（含小数）
    arabic_pattern = r"(\d+(?:\.\d+)?)"
    arabic_match = re.search(arabic_pattern, text)

    # 再尝试中文数字（含"点"小数）
    cn_pattern = (
        r"([零一二三四五六七八九十百千壹贰叁肆伍陆柒捌玖拾佰]+"
        r"(?:点[零一二三四五六七八九]+)?)"
    )
    cn_match = re.search(cn_pattern, text)

    # ── 步骤2：提取单位 ───────────────────────────────────────────────────────
    unit_pattern = rf"({_UNIT_PATTERN})"

    if arabic_match:
        quantity = float(arabic_match.group(1))
        num_end = arabic_match.end()
        # 单位紧跟在数字后
        unit_match = re.match(unit_pattern, text[num_end:])
        if unit_match:
            unit = unit_match.group(1)
            unit = _UNIT_NORMALIZE.get(unit, unit)
            # 商品名 = 去掉数字和单位后的文本
            name_candidate = text[: arabic_match.start()].strip()
            if not name_candidate:
                name_candidate = text[num_end + unit_match.end() :].strip()
        else:
            name_candidate = text[: arabic_match.start()].strip()
            if not name_candidate:
                name_candidate = text[num_end:].strip()

    elif cn_match:
        cn_qty = _cn_number_to_float(cn_match.group(1))
        if cn_qty is not None:
            quantity = cn_qty
            num_end = cn_match.end()
            unit_match = re.match(unit_pattern, text[num_end:])
            if unit_match:
                unit = unit_match.group(1)
                unit = _UNIT_NORMALIZE.get(unit, unit)
                name_candidate = text[: cn_match.start()].strip()
                if not name_candidate:
                    name_candidate = text[num_end + unit_match.end() :].strip()
            else:
                name_candidate = text[: cn_match.start()].strip()
                if not name_candidate:
                    name_candidate = text[num_end:].strip()

    # 清理商品名：去除多余标点/空白
    name_candidate = re.sub(r"[，。、！？,.!?]+", "", name_candidate).strip()

    # ── 步骤3：模糊匹配物料库 ─────────────────────────────────────────────────
    if not item_list:
        return {
            "recognized": False,
            "item_id": None,
            "item_name": None,
            "quantity": quantity,
            "unit": unit,
            "confidence_level": "low",
            "alternatives": [],
            "parse_detail": {
                "raw_text": raw_text,
                "extracted_name": name_candidate,
                "extracted_quantity": quantity,
                "extracted_unit": unit,
            },
        }

    item_names = [item["item_name"] for item in item_list]
    item_by_name = {item["item_name"]: item for item in item_list}

    # 精确匹配
    if name_candidate in item_by_name:
        matched_item = item_by_name[name_candidate]
        effective_unit = unit or matched_item.get("unit", "")
        return {
            "recognized": True,
            "item_id": matched_item["item_id"],
            "item_name": matched_item["item_name"],
            "quantity": quantity,
            "unit": effective_unit,
            "confidence_level": "high",
            "alternatives": [],
            "parse_detail": {
                "raw_text": raw_text,
                "extracted_name": name_candidate,
                "match_type": "exact",
            },
        }

    # 模糊匹配（cutoff=0.6 中等置信度；cutoff=0.4 低置信度备选）
    close_matches = difflib.get_close_matches(name_candidate, item_names, n=5, cutoff=0.4)

    if not close_matches:
        # 尝试包含匹配（商品名包含关键词）
        close_matches = [n for n in item_names if name_candidate and (name_candidate in n or n in name_candidate)][:5]

    if not close_matches:
        return {
            "recognized": False,
            "item_id": None,
            "item_name": name_candidate or None,
            "quantity": quantity,
            "unit": unit,
            "confidence_level": "low",
            "alternatives": [],
            "parse_detail": {
                "raw_text": raw_text,
                "extracted_name": name_candidate,
                "extracted_quantity": quantity,
                "extracted_unit": unit,
                "match_type": "no_match",
            },
        }

    # 计算相似度分数以确定置信度
    best_match = close_matches[0]
    ratio = difflib.SequenceMatcher(None, name_candidate, best_match).ratio()
    confidence_level = "high" if ratio >= 0.8 else ("medium" if ratio >= 0.6 else "low")

    best_item = item_by_name[best_match]
    effective_unit = unit or best_item.get("unit", "")

    alternatives = [
        {
            "item_id": item_by_name[n]["item_id"],
            "item_name": n,
            "similarity": round(difflib.SequenceMatcher(None, name_candidate, n).ratio(), 3),
        }
        for n in close_matches[1:]
    ]

    return {
        "recognized": True,
        "item_id": best_item["item_id"],
        "item_name": best_item["item_name"],
        "quantity": quantity,
        "unit": effective_unit,
        "confidence_level": confidence_level,
        "alternatives": alternatives,
        "parse_detail": {
            "raw_text": raw_text,
            "extracted_name": name_candidate,
            "extracted_quantity": quantity,
            "extracted_unit": unit,
            "best_match": best_match,
            "similarity_ratio": round(ratio, 3),
            "match_type": "fuzzy",
        },
    }


# ─── Pydantic 请求模型 ────────────────────────────────────────────────────────


class CreateVoiceCountSessionReq(BaseModel):
    """创建语音盘点会话"""

    store_id: str = Field(description="门店ID")
    warehouse_id: Optional[str] = Field(default=None, description="仓库ID（不传则盘整个门店）")
    count_type: str = Field(
        default="full",
        description="盘点类型：full=全盘 / partial=部分盘 / spot=抽盘",
    )
    category_filter: list[str] = Field(
        default=[],
        description="限定盘点的物料分类列表，空列表=不限制（全盘）",
    )
    operator_id: Optional[str] = Field(default=None, description="盘点人员工ID")


class VoiceEntryReq(BaseModel):
    """语音识别提交"""

    raw_text: str = Field(description="ASR原始文字，如：五花肉三十五点五公斤")
    confidence: float = Field(ge=0.0, le=1.0, description="ASR置信度（0-1）")
    audio_duration_ms: int = Field(ge=0, description="语音时长（毫秒）")


class ConfirmEntryReq(BaseModel):
    """确认/修正语音录入"""

    item_id: str = Field(description="物料ID")
    quantity: float = Field(gt=0, description="盘点数量")
    unit: str = Field(description="计量单位")
    source: str = Field(
        default="voice",
        description="来源：voice=语音录入 / manual=手动输入",
    )
    original_text: Optional[str] = Field(
        default=None,
        description="语音识别原始文本（source=voice时建议填写）",
    )


# ─── 盘点会话管理 ─────────────────────────────────────────────────────────────


@router.post("/sessions")
async def create_voice_count_session(
    req: CreateVoiceCountSessionReq,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建语音盘点会话，返回待盘物料列表。

    流程：
      1. 根据 count_type 和 category_filter 从库存表拉取待盘物料
      2. 创建盘点会话记录（状态 open）
      3. 返回 session_id 和 item_list（含预期库存量）
    """
    if req.count_type not in ("full", "partial", "spot"):
        _err("count_type 必须是 full / partial / spot")

    session_id = str(uuid4())
    now = datetime.now(timezone.utc)

    # 构建物料查询条件
    params: dict = {"tenant_id": x_tenant_id, "store_id": req.store_id}
    category_filter_sql = ""
    if req.category_filter:
        category_filter_sql = "AND category = ANY(:categories)"
        params["categories"] = list(req.category_filter)

    warehouse_filter_sql = ""
    if req.warehouse_id:
        warehouse_filter_sql = "AND warehouse_id = :warehouse_id"
        params["warehouse_id"] = req.warehouse_id

    spot_limit_sql = ""
    if req.count_type == "spot":
        # 抽盘：随机抽取20%物料，最少10条
        spot_limit_sql = "ORDER BY RANDOM() LIMIT GREATEST(CEIL(COUNT(*) * 0.2)::int, 10)"

    # 拉取待盘物料列表（含当前库存量作为预期值）
    items_rows = await db.execute(
        text(f"""
            SELECT i.ingredient_id AS item_id,
                   i.ingredient_name AS item_name,
                   i.unit,
                   i.category,
                   COALESCE(s.current_quantity, 0) AS expected_count
            FROM ingredients i
            LEFT JOIN inventory_stock s
              ON s.ingredient_id = i.ingredient_id
             AND s.store_id = :store_id
             AND s.tenant_id = :tenant_id
            WHERE i.tenant_id = :tenant_id
              AND i.is_deleted = FALSE
              {category_filter_sql}
              {warehouse_filter_sql}
            ORDER BY i.category, i.ingredient_name
        """),
        params,
    )
    item_list = [dict(r._mapping) for r in items_rows.fetchall()]

    if not item_list:
        _err("未找到可盘点的物料，请检查门店库存配置")

    try:
        await db.execute(
            text("""
                INSERT INTO voice_count_sessions (
                    id, tenant_id, store_id, warehouse_id, count_type,
                    category_filter, item_snapshot, operator_id,
                    status, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :store_id, :warehouse_id, :count_type,
                    :category_filter::jsonb, :item_snapshot::jsonb, :operator_id,
                    'open', :now, :now
                )
            """),
            {
                "id": session_id,
                "tenant_id": x_tenant_id,
                "store_id": req.store_id,
                "warehouse_id": req.warehouse_id,
                "count_type": req.count_type,
                "category_filter": json.dumps(req.category_filter),
                "item_snapshot": json.dumps(item_list),
                "operator_id": req.operator_id,
                "now": now,
            },
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error("voice_count_session_create_failed", error=str(exc), exc_info=True)
        _err(f"创建盘点会话失败：{exc}", code=500)

    logger.info(
        "voice_count_session_created",
        session_id=session_id,
        store_id=req.store_id,
        item_count=len(item_list),
    )
    return _ok(
        {
            "session_id": session_id,
            "store_id": req.store_id,
            "count_type": req.count_type,
            "status": "open",
            "item_list": item_list,
            "total_items": len(item_list),
            "created_at": now.isoformat(),
        }
    )


@router.get("/sessions/{session_id}")
async def get_voice_count_session(
    session_id: str,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取盘点会话状态（含已录入进度）。"""
    row = await db.execute(
        text("""
            SELECT s.id, s.store_id, s.warehouse_id, s.count_type,
                   s.category_filter, s.status, s.operator_id,
                   s.created_at, s.updated_at,
                   COALESCE(e.entry_count, 0) AS entry_count
            FROM voice_count_sessions s
            LEFT JOIN (
                SELECT session_id, COUNT(*) AS entry_count
                FROM voice_count_entries
                WHERE session_id = :session_id AND tenant_id = :tenant_id
                GROUP BY session_id
            ) e ON e.session_id = s.id
            WHERE s.id = :session_id AND s.tenant_id = :tenant_id
        """),
        {"session_id": session_id, "tenant_id": x_tenant_id},
    )
    session = row.fetchone()
    if not session:
        _err("盘点会话不存在", code=404)

    return _ok(dict(session._mapping))


@router.post("/sessions/{session_id}/close")
async def close_voice_count_session(
    session_id: str,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """关闭盘点会话（不提交，仅标记为已关闭）。"""
    result = await db.execute(
        text("""
            UPDATE voice_count_sessions
            SET status = 'closed', updated_at = :now
            WHERE id = :session_id AND tenant_id = :tenant_id AND status = 'open'
        """),
        {"session_id": session_id, "tenant_id": x_tenant_id, "now": datetime.now(timezone.utc)},
    )
    await db.commit()

    if result.rowcount == 0:
        _err("会话不存在或已关闭/提交", code=404)

    return _ok({"session_id": session_id, "status": "closed"})


# ─── 语音录入 ─────────────────────────────────────────────────────────────────


@router.post("/sessions/{session_id}/voice-entry")
async def submit_voice_entry(
    session_id: str,
    req: VoiceEntryReq,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """语音识别提交：解析ASR文本，返回识别结果供用户确认。

    不直接写入盘点记录，需用户通过 /entries 端点确认后才正式记录。
    """
    # 验证会话
    row = await db.execute(
        text("""
            SELECT id, item_snapshot, status
            FROM voice_count_sessions
            WHERE id = :session_id AND tenant_id = :tenant_id
        """),
        {"session_id": session_id, "tenant_id": x_tenant_id},
    )
    session = row.fetchone()
    if not session:
        _err("盘点会话不存在", code=404)
    if session["status"] != "open":
        _err(f"会话状态为 {session['status']}，只有 open 状态的会话可以录入")

    item_snapshot = session["item_snapshot"]
    if isinstance(item_snapshot, str):
        item_list = json.loads(item_snapshot)
    else:
        item_list = item_snapshot or []

    # 调用NLP解析函数
    parse_result = parse_voice_inventory_text(req.raw_text, item_list)

    # 记录语音解析日志
    logger.info(
        "voice_entry_parsed",
        session_id=session_id,
        raw_text=req.raw_text,
        asr_confidence=req.confidence,
        recognized=parse_result["recognized"],
        confidence_level=parse_result["confidence_level"],
    )

    return _ok(
        {
            "recognized": parse_result["recognized"],
            "item_id": parse_result["item_id"],
            "item_name": parse_result["item_name"],
            "quantity": parse_result["quantity"],
            "unit": parse_result["unit"],
            "confidence_level": parse_result["confidence_level"],
            "alternatives": parse_result["alternatives"],
            "asr_confidence": req.confidence,
            "parse_detail": parse_result["parse_detail"],
        }
    )


@router.post("/sessions/{session_id}/entries")
async def confirm_entry(
    session_id: str,
    req: ConfirmEntryReq,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """确认/修正录入，将盘点数据正式写入会话记录。

    同一会话同一物料多次录入时，以最新一条为准（覆盖）。
    """
    if req.source not in ("voice", "manual"):
        _err("source 必须是 voice 或 manual")

    # 验证会话和物料
    row = await db.execute(
        text("""
            SELECT id, store_id, item_snapshot, status
            FROM voice_count_sessions
            WHERE id = :session_id AND tenant_id = :tenant_id
        """),
        {"session_id": session_id, "tenant_id": x_tenant_id},
    )
    session = row.fetchone()
    if not session:
        _err("盘点会话不存在", code=404)
    if session["status"] != "open":
        _err(f"会话状态为 {session['status']}，只有 open 状态的会话可以录入")

    item_snapshot = session["item_snapshot"]
    if isinstance(item_snapshot, str):
        item_list = json.loads(item_snapshot)
    else:
        item_list = item_snapshot or []

    item_map = {i["item_id"]: i for i in item_list}
    if req.item_id not in item_map:
        _err(f"物料 {req.item_id} 不在本次盘点范围内")

    item = item_map[req.item_id]
    entry_id = str(uuid4())
    now = datetime.now(timezone.utc)

    try:
        await db.execute(
            text("""
                INSERT INTO voice_count_entries (
                    id, tenant_id, session_id, item_id, item_name,
                    quantity, unit, source, original_text,
                    created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :session_id, :item_id, :item_name,
                    :quantity, :unit, :source, :original_text,
                    :now, :now
                )
                ON CONFLICT (session_id, item_id)
                DO UPDATE SET
                    quantity = EXCLUDED.quantity,
                    unit = EXCLUDED.unit,
                    source = EXCLUDED.source,
                    original_text = EXCLUDED.original_text,
                    updated_at = EXCLUDED.updated_at
                RETURNING id
            """),
            {
                "id": entry_id,
                "tenant_id": x_tenant_id,
                "session_id": session_id,
                "item_id": req.item_id,
                "item_name": item["item_name"],
                "quantity": req.quantity,
                "unit": req.unit,
                "source": req.source,
                "original_text": req.original_text,
                "now": now,
            },
        )
        await db.execute(
            text("UPDATE voice_count_sessions SET updated_at = :now WHERE id = :session_id AND tenant_id = :tenant_id"),
            {"session_id": session_id, "tenant_id": tenant_id, "now": now},
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error("voice_count_entry_failed", error=str(exc), exc_info=True)
        _err(f"录入失败：{exc}", code=500)

    logger.info(
        "voice_count_entry_confirmed",
        session_id=session_id,
        item_id=req.item_id,
        quantity=req.quantity,
        unit=req.unit,
        source=req.source,
    )
    return _ok(
        {
            "entry_id": entry_id,
            "session_id": session_id,
            "item_id": req.item_id,
            "item_name": item["item_name"],
            "quantity": req.quantity,
            "unit": req.unit,
            "source": req.source,
        }
    )


@router.get("/sessions/{session_id}/entries")
async def list_entries(
    session_id: str,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取当前会话已录入的盘点明细。"""
    # 验证会话归属
    check = await db.execute(
        text("SELECT id FROM voice_count_sessions WHERE id = :sid AND tenant_id = :tid"),
        {"sid": session_id, "tid": x_tenant_id},
    )
    if not check.fetchone():
        _err("盘点会话不存在", code=404)

    rows = await db.execute(
        text("""
            SELECT id, item_id, item_name, quantity, unit, source,
                   original_text, created_at, updated_at
            FROM voice_count_entries
            WHERE session_id = :session_id AND tenant_id = :tenant_id
            ORDER BY updated_at DESC
        """),
        {"session_id": session_id, "tenant_id": x_tenant_id},
    )
    entries = [dict(r._mapping) for r in rows.fetchall()]
    return _ok({"session_id": session_id, "entries": entries, "total": len(entries)})


@router.delete("/sessions/{session_id}/entries/{entry_id}")
async def delete_entry(
    session_id: str,
    entry_id: str,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除某条录入记录（可重新录入）。"""
    result = await db.execute(
        text("""
            DELETE FROM voice_count_entries
            WHERE id = :entry_id AND session_id = :session_id AND tenant_id = :tenant_id
        """),
        {"entry_id": entry_id, "session_id": session_id, "tenant_id": x_tenant_id},
    )
    await db.commit()

    if result.rowcount == 0:
        _err("录入记录不存在", code=404)

    return _ok({"entry_id": entry_id, "deleted": True})


# ─── 差异分析与提交 ───────────────────────────────────────────────────────────


@router.get("/sessions/{session_id}/variance")
async def get_variance(
    session_id: str,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """差异分析：对比预期库存与实际盘点数量。

    返回每项物料的预期值、实盘值、差异量（正=盘盈，负=盘亏）和差异金额（分）。
    """
    row = await db.execute(
        text("""
            SELECT id, item_snapshot, store_id, status
            FROM voice_count_sessions
            WHERE id = :session_id AND tenant_id = :tenant_id
        """),
        {"session_id": session_id, "tenant_id": x_tenant_id},
    )
    session = row.fetchone()
    if not session:
        _err("盘点会话不存在", code=404)

    item_snapshot = session["item_snapshot"]
    if isinstance(item_snapshot, str):
        item_list = json.loads(item_snapshot)
    else:
        item_list = item_snapshot or []

    # 拉取已录入数量
    entries_rows = await db.execute(
        text("""
            SELECT item_id, quantity, unit
            FROM voice_count_entries
            WHERE session_id = :session_id AND tenant_id = :tenant_id
        """),
        {"session_id": session_id, "tenant_id": x_tenant_id},
    )
    entry_map = {r[0]: {"quantity": r[1], "unit": r[2]} for r in entries_rows.fetchall()}

    # 查询物料成本价（用于计算差异金额）
    item_ids = [i["item_id"] for i in item_list]
    cost_rows = await db.execute(
        text("""
            SELECT ingredient_id, COALESCE(avg_cost_fen, 0) AS cost_fen
            FROM ingredients
            WHERE ingredient_id = ANY(:item_ids) AND tenant_id = :tenant_id
        """),
        {"item_ids": item_ids, "tenant_id": x_tenant_id},
    )
    cost_map = {str(r[0]): r[1] for r in cost_rows.fetchall()}

    variance_list = []
    for item in item_list:
        item_id = item["item_id"]
        expected = float(item.get("expected_count", 0))
        entry = entry_map.get(item_id)
        counted = float(entry["quantity"]) if entry else 0.0
        variance = counted - expected
        cost_fen = cost_map.get(item_id, 0)
        variance_amount_fen = int(variance * cost_fen)

        variance_list.append(
            {
                "item_id": item_id,
                "item_name": item["item_name"],
                "unit": item.get("unit", ""),
                "expected": expected,
                "counted": counted,
                "is_counted": entry is not None,
                "variance": round(variance, 3),
                "variance_amount_fen": variance_amount_fen,
            }
        )

    # 按差异绝对值排序，差异大的排前面
    variance_list.sort(key=lambda x: abs(x["variance_amount_fen"]), reverse=True)

    total_variance_amount_fen = sum(v["variance_amount_fen"] for v in variance_list)
    variance_items_count = sum(1 for v in variance_list if v["variance"] != 0)
    uncounted_items = sum(1 for v in variance_list if not v["is_counted"])

    return _ok(
        {
            "session_id": session_id,
            "variance_list": variance_list,
            "summary": {
                "total_items": len(variance_list),
                "counted_items": len(variance_list) - uncounted_items,
                "uncounted_items": uncounted_items,
                "variance_items": variance_items_count,
                "total_variance_amount_fen": total_variance_amount_fen,
            },
        }
    )


@router.post("/sessions/{session_id}/submit")
async def submit_voice_count(
    session_id: str,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """提交盘点结果：写入正式盘点单，更新库存数量。

    流程：
      1. 验证会话状态为 open
      2. 生成盘点单号
      3. 写入 inventory_count_sheets 盘点单主表
      4. 写入 inventory_count_items 盘点明细
      5. 根据差异更新 inventory_stock（用盘点数覆盖）
      6. 更新会话状态为 submitted
      7. 旁路写入事件总线
    """
    row = await db.execute(
        text("""
            SELECT id, store_id, warehouse_id, count_type, item_snapshot,
                   operator_id, status
            FROM voice_count_sessions
            WHERE id = :session_id AND tenant_id = :tenant_id
        """),
        {"session_id": session_id, "tenant_id": x_tenant_id},
    )
    session = row.fetchone()
    if not session:
        _err("盘点会话不存在", code=404)
    if session["status"] != "open":
        _err(f"会话状态为 {session['status']}，只有 open 状态的会话可以提交")

    item_snapshot = session["item_snapshot"]
    if isinstance(item_snapshot, str):
        item_list = json.loads(item_snapshot)
    else:
        item_list = item_snapshot or []

    # 拉取已录入明细
    entries_rows = await db.execute(
        text("""
            SELECT item_id, item_name, quantity, unit, source
            FROM voice_count_entries
            WHERE session_id = :session_id AND tenant_id = :tenant_id
        """),
        {"session_id": session_id, "tenant_id": x_tenant_id},
    )
    entries = [dict(r._mapping) for r in entries_rows.fetchall()]
    entry_map = {e["item_id"]: e for e in entries}

    # 查询成本价
    item_ids = [i["item_id"] for i in item_list]
    cost_rows = await db.execute(
        text("""
            SELECT ingredient_id, COALESCE(avg_cost_fen, 0) AS cost_fen
            FROM ingredients
            WHERE ingredient_id = ANY(:item_ids) AND tenant_id = :tenant_id
        """),
        {"item_ids": item_ids, "tenant_id": x_tenant_id},
    )
    cost_map = {str(r[0]): r[1] for r in cost_rows.fetchall()}

    now = datetime.now(timezone.utc)
    count_sheet_id = str(uuid4())
    count_sheet_no = f"VC{session['store_id'][:4].upper()}{now.strftime('%Y%m%d%H%M%S')}"

    variance_items = 0
    total_variance_amount_fen = 0

    count_items = []
    for item in item_list:
        item_id = item["item_id"]
        expected = float(item.get("expected_count", 0))
        entry = entry_map.get(item_id)
        counted = float(entry["quantity"]) if entry else expected  # 未录入则视为一致
        variance = counted - expected
        cost_fen = cost_map.get(item_id, 0)
        variance_amount_fen = int(variance * cost_fen)

        if abs(variance) > 0.001:
            variance_items += 1
            total_variance_amount_fen += variance_amount_fen

        count_items.append(
            {
                "item_id": item_id,
                "item_name": item["item_name"],
                "unit": item.get("unit", ""),
                "expected": expected,
                "counted": counted,
                "variance": round(variance, 3),
                "variance_amount_fen": variance_amount_fen,
                "source": entry["source"] if entry else "expected",
            }
        )

    try:
        # 写入盘点单主表
        await db.execute(
            text("""
                INSERT INTO inventory_count_sheets (
                    id, tenant_id, store_id, warehouse_id, sheet_no,
                    count_type, session_id, operator_id, total_items,
                    variance_items, total_variance_amount_fen,
                    items, status, submitted_at, created_at
                ) VALUES (
                    :id, :tenant_id, :store_id, :warehouse_id, :sheet_no,
                    :count_type, :session_id, :operator_id, :total_items,
                    :variance_items, :total_variance_amount_fen,
                    :items::jsonb, 'submitted', :now, :now
                )
            """),
            {
                "id": count_sheet_id,
                "tenant_id": x_tenant_id,
                "store_id": session["store_id"],
                "warehouse_id": session["warehouse_id"],
                "sheet_no": count_sheet_no,
                "count_type": session["count_type"],
                "session_id": session_id,
                "operator_id": session["operator_id"],
                "total_items": len(count_items),
                "variance_items": variance_items,
                "total_variance_amount_fen": total_variance_amount_fen,
                "items": json.dumps(count_items),
                "now": now,
            },
        )

        # 更新库存数量（用盘点数覆盖 inventory_stock）
        for ci in count_items:
            if entry_map.get(ci["item_id"]):
                # 仅更新已录入的物料
                await db.execute(
                    text("""
                        UPDATE inventory_stock
                        SET current_quantity = :counted,
                            last_count_at = :now,
                            updated_at = :now
                        WHERE ingredient_id = :item_id
                          AND store_id = :store_id
                          AND tenant_id = :tenant_id
                    """),
                    {
                        "counted": ci["counted"],
                        "item_id": ci["item_id"],
                        "store_id": session["store_id"],
                        "tenant_id": x_tenant_id,
                        "now": now,
                    },
                )

        # 更新会话状态 → submitted
        await db.execute(
            text("""
                UPDATE voice_count_sessions
                SET status = 'submitted', updated_at = :now
                WHERE id = :session_id AND tenant_id = :tenant_id
            """),
            {"session_id": session_id, "tenant_id": tenant_id, "now": now},
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error("voice_count_submit_failed", error=str(exc), exc_info=True)
        _err(f"提交盘点失败：{exc}", code=500)

    # 旁路写入事件总线
    asyncio.create_task(
        emit_event(
            event_type=InventoryEventType.ADJUSTED,
            tenant_id=x_tenant_id,
            stream_id=count_sheet_id,
            payload={
                "count_sheet_no": count_sheet_no,
                "total_items": len(count_items),
                "variance_items": variance_items,
                "total_variance_amount_fen": total_variance_amount_fen,
                "source": "voice_count",
            },
            store_id=session["store_id"],
            source_service="tx-supply",
        )
    )

    logger.info(
        "voice_count_submitted",
        count_sheet_id=count_sheet_id,
        sheet_no=count_sheet_no,
        total_items=len(count_items),
        variance_items=variance_items,
    )
    return _ok(
        {
            "count_sheet_id": count_sheet_id,
            "count_sheet_no": count_sheet_no,
            "session_id": session_id,
            "total_items": len(count_items),
            "variance_items": variance_items,
            "total_variance_amount_fen": total_variance_amount_fen,
            "status": "submitted",
        }
    )
