"""
卡片流报告渲染器。

将聚合统计结果渲染为单文件 HTML 故事卡片流（10 张 9:16 全屏卡片）。
缺数据的卡片自动跳过，进度页码动态重排。

@file    render.py
@brief   故事卡片流 HTML 渲染（含降级处理）
@author  陈京宇
@date    2026-10-09
@copyright Copyright (c) 2026 maimen-wrapped contributors. MIT License.
"""

from __future__ import annotations

import html
import json
import os
from typing import Any

from .aggregate import KCAL_PER_BIG_MAC, KCAL_PER_KM_RUN, RUN_SPEED_KMH, SStats


#! 模板路径
TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "report.html")

#! 仓库地址（传播回流）
REPO_URL = "github.com/your-id/maimen-wrapped"

#! 卡片配色方案：(背景, 主文字色)
CARD_THEMES = [
    ("#C8102E", "#FFF8EC"),   # 1 封面：正红
    ("#B00E22", "#FFF8EC"),   # 2 数字：深红
    ("#E8590C", "#FFF8EC"),   # 3 花费：橙
    ("#F77F00", "#FFF8EC"),   # 4 本命餐品：亮橙
    ("#7A0E1D", "#FFF8EC"),   # 5 干饭时钟：酒红
    ("#D94F04", "#FFF8EC"),   # 6 月度：砖橙
    ("#A31621", "#FFF8EC"),   # 7 热量：红
    ("#E85D04", "#FFF8EC"),   # 8 省钱：橙红
    ("#6B0F1A", "#FFF8EC"),   # 9 彩蛋：暗红
    ("#8C0E20", "#FFF8EC"),   # 10 称号：深红
]


def render(objStats: SStats, strOutputPath: str, strRepoUrl: str = REPO_URL) -> str:
    """
    渲染报告并写入文件。

    @param objStats       聚合统计结果
    @param strOutputPath  输出 HTML 路径
    @param strRepoUrl     仓库地址（打印在称号卡）
    @return               输出路径
    """
    strCards = _build_cards(objStats, strRepoUrl)
    strTemplate = _load_template()
    strHtml = strTemplate.replace("__CARDS__", strCards)

    strDirName = os.path.dirname(os.path.abspath(strOutputPath))
    if strDirName:
        os.makedirs(strDirName, exist_ok=True)
    with open(strOutputPath, "w", encoding="utf-8") as file:
        file.write(strHtml)
    return strOutputPath


def _load_template() -> str:
    """加载 HTML 模板；缺失时抛出明确错误。"""
    if not os.path.isfile(TEMPLATE_PATH):
        raise FileNotFoundError(f"报告模板缺失：{TEMPLATE_PATH}")
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as file:
        return file.read()


def _build_cards(objStats: SStats, strRepoUrl: str) -> str:
    """
    构建全部卡片 HTML。

    @param objStats    统计结果
    @param strRepoUrl  仓库地址
    @return            卡片 HTML 片段
    """
    listBuilders = [
        _card_cover,
        _card_count,
        _card_amount,
        _card_top_items,
        _card_clock,
        _card_months,
        _card_energy,
        _card_savings,
        _card_easter_egg,
        _card_title,
    ]

    # 先收集可用卡片，以便页码重排
    listCardsHtml: list[str] = []
    for idx, fnBuilder in enumerate(listBuilders):
        strBody = fnBuilder(objStats, strRepoUrl)
        if strBody:
            listCardsHtml.append(strBody)

    nTotal = len(listCardsHtml)
    listOut: list[str] = []
    for idx, strBody in enumerate(listCardsHtml):
        strTheme = CARD_THEMES[idx % len(CARD_THEMES)]
        listOut.append(_wrap_card(strBody, idx + 1, nTotal, strTheme[0], strTheme[1]))
    return "\n".join(listOut)


def _wrap_card(strBody: str, nIndex: int, nTotal: int, strBg: str, strFg: str) -> str:
    """
    包装单张卡片（统一背景、页码、进度条）。

    @param strBody  卡片内容
    @param nIndex   卡片序号（从 1 计）
    @param nTotal   卡片总数
    @param strBg    背景色
    @param strFg    文字色
    @return         完整卡片 HTML
    """
    strDots = _build_dots(nIndex, nTotal)
    return (
        f'<section class="card" style="background:{strBg};color:{strFg}">\n'
        f"{strBody}\n"
        f'<div class="footer">'
        f'<div class="caption">{nIndex} / {nTotal}</div>'
        f'<div class="dots">{strDots}</div>'
        f"</div>\n"
        f"</section>"
    )


def _build_dots(nIndex: int, nTotal: int) -> str:
    """构建进度条圆点。"""
    return "".join(
        f'<span class="dot{" on" if idx + 1 == nIndex else ""}"></span>' for idx in range(nTotal)
    )


def _card_cover(objStats: SStats, strRepoUrl: str) -> str:
    """卡片 1：封面 + 启动按钮。"""
    strSpan = _esc(objStats.strSpanLabel) or "数据统计区间待确认"
    strStart = ""
    listStartCard = '<div id="startBtn" class="start anim">开启你的麦门之旅 <span style="font-size:19px">♪</span></div>'
    return (
        '<div class="eyebrow anim">2026 · 我的年度报告</div>\n'
        '<div class="headline anim">我的<br>麦门画像</div>\n'
        f'<div class="subhead anim">这一年，麦门见证了你<br>{strSpan}</div>\n'
        '<div class="spacer"></div>\n'
        f"{listStartCard}\n"
        '<div class="hint anim">点击后自动播放原创轻快 BGM，上滑逐张翻阅 · 每张都可截图分享</div>'
    )


def _card_count(objStats: SStats, strRepoUrl: str) -> str:
    """卡片 2：总单数冲击卡。"""
    if not objStats.nOrderCount:
        return ""
    strInsight = _esc(objStats.listInsights[0]) if objStats.listInsights else ""
    return (
        '<div class="eyebrow anim">你一共下了</div>\n'
        f'<div class="big anim"><span data-count="{objStats.nOrderCount}">0</span><span class="unit">单</span></div>\n'
        f'<div class="subhead anim">{strInsight}</div>\n'
        '<div class="spacer"></div>'
    )


def _card_amount(objStats: SStats, strRepoUrl: str) -> str:
    """卡片 3：总花费卡（无金额数据则跳过）。"""
    if not objStats.bHasAmount or objStats.dTotalAmount <= 0:
        return ""
    nCups = int(objStats.dTotalAmount / 18)
    return (
        '<div class="eyebrow anim">在麦门的花销</div>\n'
        f'<div class="big anim"><span style="font-size:52px;letter-spacing:0">¥</span>'
        f'<span data-count="{objStats.dTotalAmount:.0f}">0</span></div>\n'
        f'<div class="subhead anim">平均每单 ¥{objStats.dAmountPerOrder:.1f}</div>\n'
        '<div class="spacer"></div>\n'
        f'<div class="panel anim" style="position:relative;z-index:2">这些钱约等于 {nCups} 杯奶茶</div>'
    )


def _card_top_items(objStats: SStats, strRepoUrl: str) -> str:
    """卡片 4：本命餐品 Top 5。"""
    if not objStats.listTopItems:
        return ""

    strChampion, nChampCount = objStats.listTopItems[0]
    nMax = max(objStats.listTopItems[0][1], 1)
    listRows: list[str] = []
    for idx, (strName, nCount) in enumerate(objStats.listTopItems):
        dPct = nCount / nMax * 100
        strCls = "" if idx == 0 else " alt"
        listRows.append(
            '<div class="bar-row anim">'
            f'<div class="bar-top"><span class="n">{idx + 1} {_esc(strName)}</span>'
            f'<span class="c">{nCount}</span></div>'
            f'<div class="track"><div class="fill{strCls}" data-w="{dPct:.0f}"></div></div>'
            "</div>"
        )

    return (
        '<div class="eyebrow anim">本命餐品 TOP 5</div>\n'
        f'<div class="headline anim" style="font-size:32px">{_esc(strChampion)}<br>见了你 {nChampCount} 次</div>\n'
        f'<div class="bar anim" style="margin-top:22px">{"".join(listRows)}</div>\n'
        '<div class="spacer"></div>'
    )


def _card_clock(objStats: SStats, strRepoUrl: str) -> str:
    """卡片 5：干饭时钟（需下单时刻）。"""
    if not objStats.nSlotTotal or not objStats.bHasClock:
        return ""

    listNames = ["早餐", "午餐", "下午茶", "晚餐", "夜宵"]
    nMax = max(objStats.dictSlotCount.values()) if objStats.dictSlotCount else 1
    listCols: list[str] = []
    for strName in listNames:
        nCount = objStats.dictSlotCount.get(strName, 0)
        dH = (nCount / nMax * 100) if nMax else 0
        strHot = " hot" if nCount == nMax and nCount > 0 else ""
        listCols.append(
            '<div class="col">'
            f'<div class="cb{strHot}" data-h="{dH:.0f}"></div>'
            f'<div class="cl">{strName}</div>'
            "</div>"
        )

    strPeak, nPeakCount = max(objStats.dictSlotCount.items(), key=lambda objPair: objPair[1])
    listNightLines: list[str] = []
    if objStats.dictSlotCount.get("夜宵"):
        dRatio = objStats.dictSlotCount["夜宵"] / objStats.nSlotTotal
        listNightLines.append(f'<div class="subhead anim">{dRatio:.0%} 的订单发生在晚上 9 点以后</div>')

    return (
        '<div class="eyebrow anim">你的干饭时钟</div>\n'
        f'<div class="headline anim" style="font-size:30px">{strPeak}是你的主场</div>\n'
        f'<div class="chart anim">{"".join(listCols)}</div>\n'
        f'{"".join(listNightLines)}\n'
        '<div class="spacer"></div>'
    )


def _card_months(objStats: SStats, strRepoUrl: str) -> str:
    """卡片 6：月度节奏。"""
    if not objStats.dictMonthCount:
        return ""

    listItems = sorted(objStats.dictMonthCount.items())
    nMax = max(nCount for _, nCount in listItems) if listItems else 1
    strPeakMonth, nPeakCount = max(listItems, key=lambda objPair: objPair[1])

    listCols: list[str] = []
    for strMonth, nCount in listItems:
        dH = (nCount / nMax * 100) if nMax else 0
        strHot = " hot" if strMonth == strPeakMonth else ""
        strLabel = strMonth.split("-")[1] if "-" in strMonth else strMonth
        listCols.append(
            '<div class="col">'
            f'<div class="cb{strHot}" data-h="{dH:.0f}"></div>'
            f'<div class="cl">{strLabel}</div>'
            "</div>"
        )

    return (
        '<div class="eyebrow anim">逐月出勤记录</div>\n'
        f'<div class="headline anim" style="font-size:30px">{strPeakMonth.split("-")[-1]} 月是你的麦门之月</div>\n'
        f'<div class="chart anim">{"".join(listCols)}</div>\n'
        f'<div class="subhead anim">那个月你下了 {nPeakCount} 单</div>\n'
        '<div class="spacer"></div>'
    )


def _card_energy(objStats: SStats, strRepoUrl: str) -> str:
    """卡片 7：热量卡（低匹配率自动降级）。"""
    if objStats.dTotalEnergy <= 0:
        return ""

    dKm = objStats.dTotalEnergy / KCAL_PER_KM_RUN
    nBigMac = objStats.dTotalEnergy / KCAL_PER_BIG_MAC
    dRunHours = dKm / RUN_SPEED_KMH
    nRatePct = objStats.dNutritionMatchRate * 100

    strFootnote = ""
    if nRatePct < 90:
        strFootnote = f'<div class="warn anim">营养数据匹配率 {nRatePct:.0f}%，实际热量可能更高</div>'

    return (
        '<div class="eyebrow anim">累计热量估算</div>\n'
        f'<div class="big anim"><span data-count="{objStats.dTotalEnergy:.0f}">0</span><span class="unit">千卡</span></div>\n'
        '<div class="grid2 anim" style="margin-top:20px">'
        f'<div class="stat"><div class="v">≈ {nBigMac:.0f}</div><div class="k">个巨无霸的热量</div></div>'
        f'<div class="stat"><div class="v">≈ {dRunHours:.0f}</div><div class="k">小时慢跑消耗</div></div>'
        "</div>\n"
        '<div class="spacer"></div>\n'
        '<div class="subhead anim">按 60kg 体重估算。好消息：快乐不计入热量</div>\n'
        f"{strFootnote}"
    )


def _card_savings(objStats: SStats, strRepoUrl: str) -> str:
    """卡片 8：省钱行动卡。"""
    if not (objStats.nAvailableCoupons or objStats.nMyCoupons or objStats.nPoints):
        return ""

    listStats: list[str] = []
    if objStats.nAvailableCoupons:
        listStats.append(f'<div class="stat"><div class="v">{objStats.nAvailableCoupons}</div><div class="k">可领券</div></div>')
    if objStats.nMyCoupons:
        listStats.append(f'<div class="stat"><div class="v">{objStats.nMyCoupons}</div><div class="k">已有券</div></div>')
    if objStats.nPoints:
        listStats.append(f'<div class="stat"><div class="v">{objStats.nPoints:.0f}</div><div class="k">可用积分</div></div>')

    strUrgent = ""
    if objStats.nExpiringPoints:
        strUrgent = f'<div class="subhead anim">{objStats.nExpiringPoints:.0f} 积分即将过期，快去兑换</div>'
    else:
        strUrgent = '<div class="subhead anim">券和积分都在这儿，别让它们睡觉</div>'

    return (
        '<div class="eyebrow anim">你的省钱武器库</div>\n'
        f'<div class="headline anim" style="font-size:30px">还有羊毛可以薅</div>\n'
        f'<div class="grid3 anim" style="margin-top:20px">{"".join(listStats)}</div>\n'
        '<div class="spacer"></div>\n'
        f"{strUrgent}"
    )


def _card_easter_egg(objStats: SStats, strRepoUrl: str) -> str:
    """卡片 9：错过的活动彩蛋。"""
    if not objStats.listMissedCampaigns:
        return ""

    listPills = "".join(f'<span class="pill">{_esc(strName)}</span>' for strName in objStats.listMissedCampaigns)
    return (
        '<div class="eyebrow anim">麦麦活动回顾</div>\n'
        '<div class="headline anim" style="font-size:30px">这些活动<br>你完美错过了</div>\n'
        f'<div class="anim" style="margin-top:20px">{listPills}</div>\n'
        '<div class="spacer"></div>\n'
        '<div class="subhead anim">下次记得早点上车</div>'
    )


def _card_title(objStats: SStats, strRepoUrl: str) -> str:
    """卡片 10：麦门称号总结卡。"""
    listStats: list[str] = [f'<div class="stat"><div class="v">{objStats.nOrderCount}</div><div class="k">总单数</div></div>']
    if objStats.bHasAmount:
        listStats.append(f'<div class="stat"><div class="v">¥{objStats.dTotalAmount / 1000:.1f}k</div><div class="k">总花费</div></div>')
    if objStats.bHasClock and objStats.nSlotTotal:
        strTopSlot, _ = max(objStats.dictSlotCount.items(), key=lambda objPair: objPair[1])
        listStats.append(f'<div class="stat"><div class="v">{strTopSlot}</div><div class="k">最常时段</div></div>')
    if objStats.dictChannelCount:
        strTopChannel, _ = max(objStats.dictChannelCount.items(), key=lambda objPair: objPair[1])
        listStats.append(f'<div class="stat"><div class="v">{strTopChannel}</div><div class="k">主要方式</div></div>')
    if objStats.dTotalEnergy > 0:
        listStats.append(f'<div class="stat"><div class="v">{objStats.dTotalEnergy / 1000:.1f}k</div><div class="k">千卡</div></div>')
    if objStats.nPoints:
        listStats.append(f'<div class="stat"><div class="v">{objStats.nPoints:.0f}</div><div class="k">积分</div></div>')

    strReason = _esc(objStats.strTitleReason)
    strGenerated = _esc(objStats.strGeneratedAt)

    return (
        '<div class="eyebrow anim">你的 2026 麦门称号</div>\n'
        f'<div class="badge anim"><span>{_esc(objStats.strTitleName or "稳健干饭人")}</span></div>\n'
        f'<div class="subhead anim" style="text-align:center;margin-top:18px">{strReason}</div>\n'
        f'<div class="grid2 anim" style="margin-top:22px">{"".join(listStats[:4])}</div>\n'
        '<div class="spacer"></div>\n'
        f'<div class="repo anim">生成你的麦门画像 · <b>{_esc(strRepoUrl)}</b></div>\n'
        f'<div class="warn anim" style="text-align:center">本报告由开源项目 maimen-wrapped 生成，非麦当劳官方产品 · {strGenerated}</div>'
    )


def _esc(strText: Any) -> str:
    """HTML 转义。"""
    if strText is None:
        return ""
    return html.escape(str(strText))


def render_preview_data() -> dict[str, Any]:
    """返回推荐用于示例数据的默认结构（供 --from-json 校验）。"""
    return {
        "orderCount": 0,
        "totalAmount": 0,
        "hasAmount": False,
        "topItems": [],
        "monthCount": {},
        "slotCount": {},
        "channelCount": {},
        "totalEnergy": 0,
        "titleName": "稳健干饭人",
    }
