"""
数据拉取流水线。

编排 order-list → query-order → 其他只读工具的调用顺序，
产出聚合所需的全部原始数据。

@file    pipeline.py
@brief   订单数据拉取与补全编排
@author  陈京宇
@date    2026-10-09
@copyright Copyright (c) 2026 maimen-wrapped contributors. MIT License.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from .mcp_client import McdMcpClient


#! 营养表本地缓存路径
NUTRITION_CACHE = "nutrition_cache.json"

#! 原始数据落盘目录
RAW_DIR = os.path.join("data", "raw")

#! order-list 最大翻页数（防御性上限）
MAX_PAGES = 30


async def fetch_all(strToken: str, bVerbose: bool = True, bUseCache: bool = False) -> dict[str, Any]:
    """
    拉取聚合所需的全部数据。

    @param strToken    MCP Token
    @param bVerbose    是否输出进度
    @param bUseCache   是否优先使用本地营养表缓存
    @return            包含各工具返回数据的字典
    """
    def _log(strMsg: str) -> None:
        if bVerbose:
            print(strMsg)

    dictData: dict[str, Any] = {}

    async with McdMcpClient(strToken) as client:
        listTools = await client.list_tools()

        # ---- 1. 当前时间（报告时间戳）----
        if "now-time-info" in listTools:
            _log("[1/6] 获取当前时间 ...")
            try:
                dictData["nowTime"] = await client.call_tool("now-time-info", {})
            except Exception as exc:
                _log(f"      失败（忽略）：{exc}")

        # ---- 2. 历史订单列表 ----
        _log("[2/6] 拉取历史订单 ...")
        dictData["orderList"] = await _fetch_paged_orders(client, listTools, _log)

        # ---- 3. 订单详情补全 ----
        _log("[3/6] 补全订单详情 ...")
        dictData["orderDetails"] = await _fetch_order_details(client, dictData["orderList"], _log)

        # ---- 4. 营养表 ----
        _log("[4/6] 拉取餐品营养表 ...")
        if bUseCache and os.path.isfile(NUTRITION_CACHE):
            _log(f"      使用本地缓存 {NUTRITION_CACHE}")
            dictData["nutrition"] = _load_json(NUTRITION_CACHE)
        elif "list-nutrition-foods" in listTools:
            try:
                dictData["nutrition"] = await client.call_tool("list-nutrition-foods", {})
            except Exception as exc:
                _log(f"      失败：{exc}")
                dictData["nutrition"] = _load_json(NUTRITION_CACHE)
        else:
            dictData["nutrition"] = _load_json(NUTRITION_CACHE)

        # ---- 5. 账户与优惠券 ----
        _log("[5/6] 查询积分与优惠券 ...")
        dictData.update(await _fetch_account_tools(client, listTools, _log))

        # ---- 6. 活动日历 ----
        _log("[6/6] 查询活动日历 ...")
        if "campaign-calendar" in listTools:
            try:
                dictData["campaign"] = await client.call_tool("campaign-calendar", {})
            except Exception as exc:
                _log(f"      失败（忽略）：{exc}")

    _save_raw(dictData)
    return dictData


async def _fetch_paged_orders(client: McdMcpClient, listTools: list[str], _log) -> list[Any]:
    """
    分页拉取历史订单。

    由于分页参数形式未知，先尝试无参调用，再根据返回结构嗅探分页字段。

    @param client      MCP 客户端
    @param listTools   可用工具列表
    @param _log        日志函数
    @return            订单列表
    """
    if "order-list" not in listTools:
        _log("      服务端未提供 order-list 工具")
        return []

    listAll: list[Any] = []
    strPageParam = None
    dictExtra: dict[str, Any] = {}

    for nPage in range(1, MAX_PAGES + 1):
        dictArgs: dict[str, Any] = dict(dictExtra)
        if strPageParam and nPage > 1:
            dictArgs[strPageParam] = nPage

        try:
            objData = await client.call_tool("order-list", dictArgs)
        except Exception as exc:
            _log(f"      第 {nPage} 页失败：{exc}")
            break

        listBatch = _extract_list(objData)
        if not listBatch:
            if nPage == 1:
                _log("      未获取到订单数据（可能是账号无历史订单，或返回结构待探查）")
            break

        listAll.extend(listBatch)
        _log(f"      第 {nPage} 页：{len(listBatch)} 单（累计 {len(listAll)}）")

        # 首屏嗅探分页字段
        if nPage == 1:
            strPageParam = _sniff_page_param(objData)
            nTotal = _sniff_total(objData)
            if nTotal:
                _log(f"      服务端报告总数：{nTotal}")

        if len(listBatch) < 1:
            break
        if strPageParam is None:
            break
        if nTotal and len(listAll) >= nTotal:
            break

    return listAll


def _sniff_page_param(objData: Any) -> str | None:
    """
    嗅探分页参数名（page / pageNum / offset / cursor）。

    @param objData  返回数据
    @return         参数名；未识别返回 None
    """
    if not isinstance(objData, dict):
        return None
    dictFlat = _flatten_keys(objData)
    for strCandidate in ("pageNum", "pageNo", "page", "pageIndex", "offset", "cursor", "nextCursor"):
        if any(strCandidate.lower() == strKey.lower() for strKey in dictFlat):
            return strCandidate
    # 只有当返回结构中出现 total / hasNext 等分页迹象时才认为支持翻页
    if any(strKey.lower() in ("total", "totalcount", "hasnext", "hasmore") for strKey in dictFlat):
        return "page"
    return None


def _sniff_total(objData: Any) -> int:
    """嗅探总条数。"""
    if not isinstance(objData, dict):
        return 0
    dictFlat = _flatten_keys(objData)
    for strKey, objValue in dictFlat.items():
        if strKey.lower() in ("total", "totalcount", "count", "totalnum"):
            match = str(objValue)
            if match.isdigit():
                return int(match)
    return 0


async def _fetch_order_details(client: McdMcpClient, listOrders: list[Any], _log) -> list[Any]:
    """
    并发补全订单详情。

    @param client       MCP 客户端
    @param listOrders   订单列表
    @param _log         日志函数
    @return             详情列表（失败项为 None）
    """
    if not listOrders:
        return []

    listArgs: list[dict[str, Any]] = []
    for objOrder in listOrders:
        if not isinstance(objOrder, dict):
            continue
        strId = _pick(order_id_candidates(), objOrder)
        if strId:
            listArgs.append({"orderId": str(strId)})

    if not listArgs:
        _log("      未识别到订单号字段，跳过详情补全")
        return []

    _log(f"      并发补全 {len(listArgs)} 单详情（并发 {client.m_nConcurrency}）...")
    listResults = await client.call_tools_concurrent("query-order", listArgs, bIgnoreErrors=True)
    nOk = sum(1 for obj in listResults if obj is not None)
    _log(f"      成功 {nOk}/{len(listArgs)} 单")
    return listResults


def order_id_candidates() -> tuple[str, ...]:
    """订单号候选字段名。"""
    return ("orderId", "order_id", "orderNo", "id", "订单号")


async def _fetch_account_tools(client: McdMcpClient, listTools: list[str], _log) -> dict[str, Any]:
    """并发拉取积分、券相关工具。"""
    dictOut: dict[str, Any] = {}
    listTargets = [
        ("account", "query-my-account"),
        ("availableCoupons", "available-coupons"),
        ("myCoupons", "query-my-coupons"),
        ("mallOrders", "mall-order-list"),
    ]

    async def _one(strKey: str, strTool: str) -> tuple[str, Any]:
        if strTool not in listTools:
            return strKey, None
        try:
            return strKey, await client.call_tool(strTool, {})
        except Exception as exc:
            _log(f"      {strTool} 失败（忽略）：{exc}")
            return strKey, None

    listPairs = await asyncio.gather(*[_one(strKey, strTool) for strKey, strTool in listTargets])
    for strKey, objValue in listPairs:
        dictOut[strKey] = objValue
    return dictOut


def _save_raw(dictData: dict[str, Any]) -> None:
    """保存原始数据到本地（便于离线复现与调试）。"""
    try:
        os.makedirs(RAW_DIR, exist_ok=True)
        strPath = os.path.join(RAW_DIR, "last_fetch.json")
        with open(strPath, "w", encoding="utf-8") as file:
            json.dump(dictData, file, ensure_ascii=False, indent=2, default=str)
    except OSError:
        pass


def _load_json(strPath: str) -> Any:
    """读取本地 JSON 文件。"""
    if not os.path.isfile(strPath):
        return None
    try:
        with open(strPath, "r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return None


def _extract_list(objData: Any) -> list[Any]:
    """从各种包装结构中提取列表。"""
    if isinstance(objData, list):
        return objData
    if isinstance(objData, dict):
        for strKey in ("data", "orders", "list", "items", "result", "orderList", "records"):
            objValue = objData.get(strKey)
            if isinstance(objValue, list):
                return objValue
            if isinstance(objValue, dict):
                listNested = _extract_list(objValue)
                if listNested:
                    return listNested
    return []


def _flatten_keys(objData: dict[str, Any], strPrefix: str = "") -> dict[str, Any]:
    """展平字典键（用于字段嗅探）。"""
    dictOut: dict[str, Any] = {}
    for strKey, objValue in objData.items():
        if isinstance(objValue, dict):
            dictOut.update(_flatten_keys(objValue, f"{strPrefix}{strKey}."))
        else:
            dictOut[strKey] = objValue
    return dictOut


def _pick(tupleKeys: tuple[str, ...], dictItem: dict[str, Any]) -> Any:
    """按键名候选列表取值。"""
    for strKey in tupleKeys:
        if strKey in dictItem and dictItem[strKey] not in (None, ""):
            return dictItem[strKey]
    dictLower = {str(k).lower().replace("_", ""): v for k, v in dictItem.items()}
    for strKey in tupleKeys:
        strNorm = strKey.lower().replace("_", "")
        if strNorm in dictLower and dictLower[strNorm] not in (None, ""):
            return dictLower[strNorm]
    return None
