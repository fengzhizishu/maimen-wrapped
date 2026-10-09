"""
麦当劳 MCP 工具探查模式。

用于首次接入时 dump 各工具的原始返回结构，以便核对字段、定稿报告版块。
探查结果仅落本地 data/ 目录（已被 .gitignore 忽略）。

@file    probe.py
@brief   MCP 工具返回结构探查（字段核对 / 降级矩阵定稿依据）
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


#! 探查输出目录（本地，已忽略提交）
PROBE_DIR = os.path.join("data", "probe")

#! 无参只读工具：直接调用即可
NO_ARG_TOOLS = [
    "now-time-info",
    "order-list",
    "list-nutrition-foods",
    "query-my-account",
    "query-my-coupons",
    "available-coupons",
    "campaign-calendar",
    "mall-order-list",
]


async def run_probe(strToken: str, strOutDir: str = PROBE_DIR) -> dict[str, Any]:
    """
    执行探查：依次调用关键工具并保存原始返回。

    @param strToken    MCP Token
    @param strOutDir   输出目录
    @return            工具名到返回数据的映射（调用失败为错误描述字符串）
    """
    os.makedirs(strOutDir, exist_ok=True)
    dictResult: dict[str, Any] = {}

    async with McdMcpClient(strToken) as client:
        listTools = await client.list_tools()
        print(f"[探查] 服务端共 {len(listTools)} 个工具：")
        for strName in sorted(listTools):
            print(f"        - {strName}")
        dictResult["__tools__"] = listTools
        _dump(os.path.join(strOutDir, "__tools__.json"), listTools)

        for strTool in NO_ARG_TOOLS:
            if strTool not in listTools:
                print(f"[跳过] {strTool}（服务端未提供该工具）")
                dictResult[strTool] = {"__error__": "工具不存在"}
                continue

            print(f"[探查] 调用 {strTool} ...")
            try:
                objData = await client.call_tool(strTool, {})
                dictResult[strTool] = objData
                _dump(os.path.join(strOutDir, f"{strTool}.json"), objData)
                _print_summary(strTool, objData)
            except Exception as exc:
                print(f"[失败] {strTool}: {exc}")
                dictResult[strTool] = {"__error__": str(exc)}

    _write_schema_report(os.path.join(strOutDir, "SCHEMA_REPORT.md"), dictResult)
    print(f"\n[完成] 探查结果已保存至 {strOutDir}/")
    print(f"[完成] 字段核对报告：{os.path.join(strOutDir, 'SCHEMA_REPORT.md')}")
    return dictResult


def _dump(strPath: str, objData: Any) -> None:
    """将数据写入 JSON 文件。"""
    try:
        with open(strPath, "w", encoding="utf-8") as file:
            json.dump(objData, file, ensure_ascii=False, indent=2, default=str)
    except OSError as exc:
        print(f"[警告] 写入 {strPath} 失败：{exc}")


def _print_summary(strTool: str, objData: Any) -> None:
    """在终端打印返回结构的简要摘要。"""
    if objData is None:
        print("        返回为空")
        return

    if isinstance(objData, list):
        print(f"        列表，共 {len(objData)} 项")
        if objData:
            print(f"        首项字段：{_field_names(objData[0])}")
        return

    if isinstance(objData, dict):
        print(f"        字典，顶层键：{list(objData.keys())[:12]}")
        for strKey, objValue in list(objData.items())[:6]:
            if isinstance(objValue, list) and objValue:
                print(f"          .{strKey} -> 列表[{len(objValue)}]，首项字段：{_field_names(objValue[0])}")
        return

    print(f"        标量：{str(objData)[:120]}")


def _field_names(objItem: Any) -> list[str]:
    """提取对象字段名列表。"""
    if isinstance(objItem, dict):
        return list(objItem.keys())
    return [f"<{type(objItem).__name__}>"]


def _write_schema_report(strPath: str, dictResult: dict[str, Any]) -> None:
    """
    生成字段核对报告（Markdown），供人工对照降级矩阵定稿。

    @param strPath      输出路径
    @param dictResult   探查结果
    """
    listLines: list[str] = ["# MCP 工具返回结构核对报告", ""]
    listLines.append(f"生成时间：{_now_str()}")
    listLines.append("")
    listLines.append("> 本文件由 `python -m maimen_wrapped --probe` 自动生成，位于本地 data/ 目录，不提交仓库。")
    listLines.append("")

    listLines.append("## 关键字段核对清单")
    listLines.append("")
    listLines.append("| 核对项 | 依赖工具 | 结论 |")
    listLines.append("| --- | --- | --- |")
    listLines.append(f"| 订单是否含金额 | order-list / query-order | {_check_amount(dictResult)} |")
    listLines.append(f"| 订单是否含下单时刻 | order-list / query-order | {_check_time(dictResult)} |")
    listLines.append(f"| 订单时间跨度与总数 | order-list | {_check_span(dictResult)} |")
    listLines.append(f"| 订单是否含就餐方式 | order-list / query-order | {_check_channel(dictResult)} |")
    listLines.append(f"| 营养表条数与字段 | list-nutrition-foods | {_check_nutrition(dictResult)} |")
    listLines.append(f"| 积分账户字段 | query-my-account | {_check_keys(dictResult, 'query-my-account')} |")
    listLines.append(f"| 可用券数量 | available-coupons | {_check_count(dictResult, 'available-coupons')} |")
    listLines.append(f"| 活动日历字段 | campaign-calendar | {_check_keys(dictResult, 'campaign-calendar')} |")
    listLines.append("")

    for strTool, objData in dictResult.items():
        if strTool == "__tools__":
            continue
        listLines.append(f"## {strTool}")
        listLines.append("")
        listLines.append("```json")
        strJson = json.dumps(objData, ensure_ascii=False, indent=2, default=str)
        listLines.append(strJson[:4000])
        if len(strJson) > 4000:
            listLines.append("... (截断，完整内容见同目录 JSON 文件)")
        listLines.append("```")
        listLines.append("")

    try:
        with open(strPath, "w", encoding="utf-8") as file:
            file.write("\n".join(listLines))
    except OSError as exc:
        print(f"[警告] 写入核对报告失败：{exc}")


def _find_first_dict(objData: Any) -> dict[str, Any] | None:
    """在嵌套结构中查找第一个字典（用于字段探测）。"""
    if isinstance(objData, dict):
        for strKey in ("data", "result", "orders", "list", "items"):
            if strKey in objData and isinstance(objData[strKey], list) and objData[strKey]:
                if isinstance(objData[strKey][0], dict):
                    return objData[strKey][0]
        if not any(isinstance(objValue, (list, dict)) for objValue in objData.values()):
            return objData
        for objValue in objData.values():
            objFound = _find_first_dict(objValue)
            if objFound is not None:
                return objFound
    elif isinstance(objData, list) and objData:
        return _find_first_dict(objData[0])
    return None


def _check_amount(dictResult: dict[str, Any]) -> str:
    """核对是否可获取金额。"""
    for strTool in ("order-list", "query-order"):
        objItem = _find_first_dict(dictResult.get(strTool))
        if objItem:
            listAmountKeys = [
                strKey
                for strKey in objItem.keys()
                if any(strWord in strKey.lower() for strWord in ("amount", "price", "total", "fee", "money", "金额", "价格", "实付"))
            ]
            if listAmountKeys:
                return f"可用，字段：{listAmountKeys}（{strTool}）"
    return "未发现金额字段 → 需降级（隐藏花费卡）"


def _check_time(dictResult: dict[str, Any]) -> str:
    """核对是否可获取下单时刻。"""
    for strTool in ("order-list", "query-order"):
        objItem = _find_first_dict(dictResult.get(strTool))
        if objItem:
            for strKey, objValue in objItem.items():
                if any(strWord in strKey.lower() for strWord in ("time", "date", "created", "时间", "日期")):
                    strText = str(objValue)
                    bHasClock = ":" in strText and len(strText) > 10
                    return f"字段 {strKey} = {strText[:40]}（{'含时刻' if bHasClock else '仅日期'}）"
    return "未发现时间字段 → 需降级"


def _check_span(dictResult: dict[str, Any]) -> str:
    """核对订单时间跨度。"""
    objData = dictResult.get("order-list")
    if isinstance(objData, dict):
        for strKey in ("data", "result", "orders", "list", "items"):
            if strKey in objData and isinstance(objData[strKey], list):
                return f"本次返回 {len(objData[strKey])} 单（总跨度需翻页确认）"
    if isinstance(objData, list):
        return f"本次返回 {len(objData)} 单"
    return "无法判定"


def _check_channel(dictResult: dict[str, Any]) -> str:
    """核对是否可获取就餐方式。"""
    for strTool in ("order-list", "query-order"):
        objItem = _find_first_dict(dictResult.get(strTool))
        if objItem:
            listKeys = [
                strKey
                for strKey in objItem.keys()
                if any(strWord in strKey.lower() for strWord in ("type", "channel", "delivery", "takeout", "mode", "方式", "类型"))
            ]
            if listKeys:
                return f"可用，字段：{listKeys}（{strTool}）"
    return "未发现就餐方式字段 → 保留到店/外送卡需实测确认"


def _check_nutrition(dictResult: dict[str, Any]) -> str:
    """核对营养表结构。"""
    objData = dictResult.get("list-nutrition-foods")
    nCount = 0
    if isinstance(objData, list):
        nCount = len(objData)
    elif isinstance(objData, dict):
        for strKey in ("data", "list", "items", "foods"):
            if isinstance(objData.get(strKey), list):
                nCount = len(objData[strKey])
                break
    objItem = _find_first_dict(objData)
    strFields = str(list(objItem.keys())) if objItem else "未知"
    return f"{nCount} 条；字段：{strFields}"


def _check_keys(dictResult: dict[str, Any], strTool: str) -> str:
    """核对指定工具的顶层字段。"""
    objData = dictResult.get(strTool)
    if isinstance(objData, dict):
        return f"顶层键：{list(objData.keys())[:8]}"
    if isinstance(objData, list):
        return f"列表 {len(objData)} 项"
    return "无数据"


def _check_count(dictResult: dict[str, Any], strTool: str) -> str:
    """统计指定工具返回条数。"""
    objData = dictResult.get(strTool)
    if isinstance(objData, list):
        return f"{len(objData)} 项"
    if isinstance(objData, dict):
        for strKey in ("data", "list", "items", "coupons"):
            if isinstance(objData.get(strKey), list):
                return f"{len(objData[strKey])} 项（.{strKey}）"
    return "无法判定"


def _now_str() -> str:
    """返回当前本地时间字符串。"""
    import datetime

    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def main(strToken: str) -> None:
    """同步入口（供 CLI 调用）。"""
    asyncio.run(run_probe(strToken))


if __name__ == "__main__":
    from .mcp_client import resolve_token

    main(resolve_token())
