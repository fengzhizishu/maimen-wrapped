"""
maimen-wrapped 命令行入口。

用法：
    python -m maimen_wrapped --token <TOKEN>          # 完整流程
    python -m maimen_wrapped --probe                  # 探查模式
    python -m maimen_wrapped --from-json <FILE>       # 离线示例模式

@file    __main__.py
@brief   CLI 入口与流程编排
@author  陈京宇
@date    2026-10-09
@copyright Copyright (c) 2026 maimen-wrapped contributors. MIT License.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import sys

from .aggregate import aggregate, count_cancelled, normalize_orders
from .mcp_client import McdMcpError, McdTokenError, resolve_token
from .nutrition import load_nutrition_table
from .pipeline import NUTRITION_CACHE, fetch_all
from .render import render


#! 默认输出路径
DEFAULT_OUTPUT = os.path.join("output", "maimen-wrapped.html")


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="maimen-wrapped",
        description="麦门年度画像 · 基于麦当劳 MCP 生成你的个人消费故事卡片流",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python -m maimen_wrapped --token YOUR_TOKEN\n"
            "  python -m maimen_wrapped --probe --token YOUR_TOKEN\n"
            "  python -m maimen_wrapped --from-json examples/sample_data.json\n"
        ),
    )
    parser.add_argument("--token", type=str, default=None, help="麦当劳 MCP Token（优先级最高）")
    parser.add_argument("--probe", action="store_true", help="探查模式：dump 各工具返回结构，供字段核对")
    parser.add_argument("--from-json", type=str, default=None, help="离线模式：从本地 JSON 数据生成报告（无需 Token）")
    parser.add_argument("--out", type=str, default=DEFAULT_OUTPUT, help=f"输出 HTML 路径（默认 {DEFAULT_OUTPUT}）")
    parser.add_argument("--repo", type=str, default=None, help="报告中展示的仓库地址")
    parser.add_argument("--cache", action="store_true", help="复用本地营养表缓存，减少网络请求")
    parser.add_argument("--quiet", action="store_true", help="精简输出")
    return parser


def main(listArgv: list[str] | None = None) -> int:
    """
    主入口。

    @param listArgv  命令行参数（None 时取 sys.argv）
    @return          进程退出码
    """
    parser = build_parser()
    objArgs = parser.parse_args(listArgv)
    bVerbose = not objArgs.quiet

    try:
        if objArgs.from_json:
            return _run_offline(objArgs, bVerbose)

        strToken = resolve_token(objArgs.token)

        if objArgs.probe:
            return _run_probe(strToken)

        return _run_online(objArgs, strToken, bVerbose)

    except McdTokenError as exc:
        print(f"\n[Token 错误] {exc}", file=sys.stderr)
        return 2
    except McdMcpError as exc:
        print(f"\n[MCP 错误] {exc}", file=sys.stderr)
        return 3
    except FileNotFoundError as exc:
        print(f"\n[文件错误] {exc}", file=sys.stderr)
        return 4
    except KeyboardInterrupt:
        print("\n[中断] 用户取消操作", file=sys.stderr)
        return 130


def _run_probe(strToken: str) -> int:
    """执行探查模式。"""
    from .probe import run_probe

    print("=" * 62)
    print("  麦当劳 MCP 工具探查模式")
    print("  目的：dump 各工具返回结构，核对字段以定稿报告版块")
    print("=" * 62)
    asyncio.run(run_probe(strToken))
    return 0


def _run_online(objArgs: argparse.Namespace, strToken: str, bVerbose: bool) -> int:
    """
    在线模式：拉取 MCP 数据并生成报告。

    @param objArgs   命令行参数
    @param strToken  MCP Token
    @param bVerbose  是否输出进度
    @return          退出码
    """
    if bVerbose:
        print("=" * 62)
        print("  麦门年度画像 · 数据拉取中")
        print("=" * 62)

    dictData = asyncio.run(fetch_all(strToken, bVerbose=bVerbose, bUseCache=objArgs.cache))

    return _build_and_render(dictData, objArgs, bVerbose, strSource="MCP 实时数据")


def _run_offline(objArgs: argparse.Namespace, bVerbose: bool) -> int:
    """
    离线模式：从本地 JSON 生成报告。

    @param objArgs   命令行参数
    @param bVerbose  是否输出进度
    @return          退出码
    """
    strPath = objArgs.from_json
    if not os.path.isfile(strPath):
        print(f"\n[文件不存在] {strPath}", file=sys.stderr)
        return 4

    with open(strPath, "r", encoding="utf-8") as file:
        dictData = json.load(file)

    if bVerbose:
        print(f"[离线模式] 数据来源：{strPath}")

    return _build_and_render(dictData, objArgs, bVerbose, strSource=f"本地文件 {os.path.basename(strPath)}")


def _build_and_render(
    dictData: dict, objArgs: argparse.Namespace, bVerbose: bool, strSource: str
) -> int:
    """
    聚合数据并渲染报告。

    @param dictData  原始数据（MCP 或本地）
    @param objArgs   命令行参数
    @param bVerbose  是否输出进度
    @param strSource 数据来源描述
    @return          退出码
    """
    # 营养表
    objTable = load_nutrition_table(
        objMcpData=dictData.get("nutrition"),
        strCachePath=NUTRITION_CACHE if not objArgs.from_json else "",
    )
    if bVerbose:
        print(f"[营养表] 加载 {len(objTable.m_listAll)} 条餐品数据")

    # 订单标准化（合并列表与详情）
    listRawOrders = _merge_orders(dictData.get("orderList"), dictData.get("orderDetails"))
    listOrders = normalize_orders(listRawOrders)
    nCancelled = count_cancelled(listRawOrders)
    if bVerbose:
        print(f"[订单] 标准化 {len(listOrders)} 单（已过滤取消单 {nCancelled} 单）")

    # 营养匹配
    listItemNames: list[str] = []
    for objOrder in listOrders:
        listItemNames.extend(objOrder.listItems)
    objMatch = objTable.match_many(listItemNames)
    if bVerbose:
        print(f"[营养匹配] 匹配率 {objMatch.get_rate():.1%}，未匹配 {len(objMatch.listUnmatched)} 项")

    # 聚合
    strGeneratedAt = _resolve_now_str(dictData.get("nowTime"))
    objStats = aggregate(
        listOrders=listOrders,
        objMatch=objMatch,
        objAccount=dictData.get("account"),
        objAvailableCoupons=dictData.get("availableCoupons"),
        objMyCoupons=dictData.get("myCoupons"),
        objCampaign=dictData.get("campaign"),
        strGeneratedAt=strGeneratedAt,
    )
    objStats.nCancelledCount = nCancelled

    # 渲染
    strRepo = objArgs.repo or "github.com/fengzhizishu/maimen-wrapped"
    strOutPath = render(objStats, objArgs.out, strRepoUrl=strRepo)

    if bVerbose:
        _print_summary(objStats, strSource, strOutPath)
    return 0


def _merge_orders(objList: object, objDetails: object) -> list:
    """
    合并订单列表与详情数据（详情优先，缺失时回落到列表项）。

    @param objList      order-list 返回
    @param objDetails   query-order 详情返回
    @return             合并后的原始订单记录列表
    """
    listBase = _to_list(objList)
    listDetails = [obj for obj in _to_list(objDetails) if isinstance(obj, dict)]

    if not listDetails:
        return listBase

    # 以订单号建立索引，详情覆盖列表项
    dictById: dict[str, dict] = {}
    listNoId: list[dict] = []

    for objItem in listBase:
        if isinstance(objItem, dict):
            strId = _pick_id(objItem)
            if strId:
                dictById[strId] = objItem
            else:
                listNoId.append(objItem)
        else:
            listNoId.append(objItem)  # type: ignore[arg-type]

    for objDetail in listDetails:
        strId = _pick_id(objDetail)
        if strId and strId in dictById:
            dictById[strId] = {**dictById[strId], **objDetail}
        elif strId:
            dictById[strId] = objDetail

    return list(dictById.values()) + listNoId


def _pick_id(dictItem: dict) -> str:
    """提取订单号。"""
    for strKey in ("orderId", "order_id", "orderNo", "id"):
        if strKey in dictItem and dictItem[strKey]:
            return str(dictItem[strKey])
    return ""


def _to_list(objData: object) -> list:
    """将返回值统一为列表。"""
    if objData is None:
        return []
    if isinstance(objData, list):
        return objData
    if isinstance(objData, dict):
        for strKey in ("data", "orders", "list", "items", "result", "orderList", "records"):
            objValue = objData.get(strKey)
            if isinstance(objValue, list):
                return objValue
            if isinstance(objValue, dict):
                listNested = _to_list(objValue)
                if listNested:
                    return listNested
    return []


def _resolve_now_str(objNow: object) -> str:
    """解析服务端时间；失败则回落到本地时间。"""
    if isinstance(objNow, dict):
        for strKey in ("time", "datetime", "date", "currentTime", "timestamp", "now"):
            if objNow.get(strKey):
                return str(objNow[strKey])[:19]
    if isinstance(objNow, str) and objNow:
        return objNow[:19]
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _print_summary(objStats, strSource: str, strOutPath: str) -> None:
    """打印生成结果摘要。"""
    print()
    print("=" * 62)
    print("  生成完成")
    print("=" * 62)
    print(f"  数据来源    ：{strSource}")
    print(f"  订单总数    ：{objStats.nOrderCount} 单")
    print(f"  统计区间    ：{objStats.strSpanLabel or '未知'}")
    if objStats.bHasAmount:
        print(f"  总花费      ：¥{objStats.dTotalAmount:.2f}（客单价 ¥{objStats.dAmountPerOrder:.1f}）")
    else:
        print("  总花费      ：订单数据中未发现金额字段（已自动隐藏该卡片）")
    if objStats.listTopItems:
        print(f"  本命餐品    ：{objStats.listTopItems[0][0]}（{objStats.listTopItems[0][1]} 次）")
    print(f"  麦门称号    ：{objStats.strTitleName} —— {objStats.strTitleReason}")
    if objStats.dTotalEnergy > 0:
        print(f"  累计热量    ：{objStats.dTotalEnergy:.0f} kcal（匹配率 {objStats.dNutritionMatchRate:.0%}）")
    print(f"  输出文件    ：{os.path.abspath(strOutPath)}")
    if objStats.listWarnings:
        for strWarn in objStats.listWarnings:
            print(f"  [提示] {strWarn}")
    print("=" * 62)
    print("  用浏览器打开输出文件即可翻阅卡片流（含原创 BGM）")
    print()


if __name__ == "__main__":
    sys.exit(main())
