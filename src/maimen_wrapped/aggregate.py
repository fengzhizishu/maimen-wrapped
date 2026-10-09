"""
订单数据聚合与称号规则引擎。

将原始订单+营养数据聚合为报告所需的统计结构，并按规则发放麦门称号。
本模块为纯函数实现（无网络、无 IO），便于单元测试。

@file    aggregate.py
@brief   统计聚合与麦门称号规则引擎
@author  陈京宇
@date    2026-10-09
@copyright Copyright (c) 2026 maimen-wrapped contributors. MIT License.
"""

from __future__ import annotations

import datetime
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from .nutrition import CNutritionTable, SNutrition, normalize_name


#! 每公里慢跑约消耗的热量（kcal，按 60kg 体重估算）
KCAL_PER_KM_RUN = 60.0

#! 慢跑速度（km/h），用于折算消耗时间
RUN_SPEED_KMH = 8.0

#! 一杯奶茶的估算热量（kcal）
KCAL_PER_MILK_TEA = 400.0

#! 一个巨无霸的参考热量（kcal，来自公开营养信息，仅用于趣味换算）
KCAL_PER_BIG_MAC = 510.0

#! 到店/外送识别关键词
CHANNEL_TAKEOUT = ("到店", "堂食", "自取", "取餐", "dine", "self")
CHANNEL_DELIVERY = ("外送", "麦乐送", "外卖", "delivery", "express")

#! 订单状态：视为已取消的关键词
CANCELLED_KEYWORDS = ("取消", "已关闭", "cancel", "closed")

#! 时段划分：(名称, 起始小时, 结束小时)
TIME_SLOTS = [
    ("早餐", 5, 10),
    ("午餐", 10, 14),
    ("下午茶", 14, 17),
    ("晚餐", 17, 21),
    ("夜宵", 21, 29),
]


@dataclass
class SOrder:
    """
    标准化订单记录。

    @author 陈京宇
    @date   2026-10-09
    """

    strOrderId: str = ""
    dtTime: datetime.datetime | None = None
    bHasClock: bool = False     #!< 是否含有效时刻（仅日期则为 False）
    dAmount: float | None = None
    strChannel: str = ""
    strStatus: str = ""         #!< 原始订单状态文本
    bCancelled: bool = False    #!< 是否为已取消订单
    bFreeOrder: bool = False    #!< 是否为券/积分兑换的零元订单
    listItems: list[str] = field(default_factory=list)
    dictItemQty: dict[str, int] = field(default_factory=dict)
    listComboItems: list[str] = field(default_factory=list)   #!< 套餐拆解出的单品明细


@dataclass
class SStats:
    """
    聚合统计结果。

    @author 陈京宇
    @date   2026-10-09
    """

    nOrderCount: int = 0
    dTotalAmount: float = 0.0
    bHasAmount: bool = False
    dtEarliest: datetime.datetime | None = None
    dtLatest: datetime.datetime | None = None
    nSpanDays: int = 0
    dAmountPerOrder: float = 0.0
    nCancelledCount: int = 0        #!< 已过滤的取消单数量
    nFreeOrderCount: int = 0        #!< 零元单（券/积分兑换）数量
    dFreeOrderValue: float = 0.0    #!< 零元单折算价值（按同类单品均价估算）

    listTopItems: list[tuple[str, int]] = field(default_factory=list)
    dictMonthCount: dict[str, int] = field(default_factory=dict)
    dictWeekdayCount: dict[str, int] = field(default_factory=dict)
    dictSlotCount: dict[str, int] = field(default_factory=dict)
    nSlotTotal: int = 0
    bHasClock: bool = False                                     #!< 订单数据是否含有效时刻
    dictChannelCount: dict[str, int] = field(default_factory=dict)

    dTotalEnergy: float = 0.0
    dTotalProtein: float = 0.0
    dNutritionMatchRate: float = 1.0
    nUnmatchedItems: int = 0

    nAvailableCoupons: int = 0
    nMyCoupons: int = 0
    nPoints: float = 0.0
    nTotalPoints: float = 0.0        #!< 累计积分（含已用/已过期）
    nExpiringPoints: float = 0.0

    strTitle: str = "我的麦门画像"
    strSpanLabel: str = ""
    strTitleName: str = ""
    strTitleReason: str = ""
    strGeneratedAt: str = ""

    listInsights: list[str] = field(default_factory=list)
    listWarnings: list[str] = field(default_factory=list)
    listMissedCampaigns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化字典。"""
        return {
            "orderCount": self.nOrderCount,
            "totalAmount": round(self.dTotalAmount, 2),
            "hasAmount": self.bHasAmount,
            "amountPerOrder": round(self.dAmountPerOrder, 2),
            "spanDays": self.nSpanDays,
            "cancelledCount": self.nCancelledCount,
            "freeOrderCount": self.nFreeOrderCount,
            "freeOrderValue": round(self.dFreeOrderValue, 2),
            "dateStart": self.dtEarliest.strftime("%Y.%m") if self.dtEarliest else "",
            "dateEnd": self.dtLatest.strftime("%Y.%m") if self.dtLatest else "",
            "topItems": [{"name": obj[0], "count": obj[1]} for obj in self.listTopItems],
            "monthCount": self.dictMonthCount,
            "weekdayCount": self.dictWeekdayCount,
            "slotCount": self.dictSlotCount,
            "hasClock": self.bHasClock,
            "channelCount": self.dictChannelCount,
            "totalEnergy": round(self.dTotalEnergy, 0),
            "totalProtein": round(self.dTotalProtein, 1),
            "nutritionMatchRate": round(self.dNutritionMatchRate, 3),
            "unmatchedItems": self.nUnmatchedItems,
            "availableCoupons": self.nAvailableCoupons,
            "myCoupons": self.nMyCoupons,
            "points": round(self.nPoints, 0),
            "totalPoints": round(self.nTotalPoints, 0),
            "expiringPoints": round(self.nExpiringPoints, 0),
            "titleName": self.strTitleName,
            "titleReason": self.strTitleReason,
            "spanLabel": self.strSpanLabel,
            "generatedAt": self.strGeneratedAt,
            "insights": self.listInsights,
            "warnings": self.listWarnings,
            "missedCampaigns": self.listMissedCampaigns,
        }


def normalize_orders(
    objRawData: Any,
    objNutrition: CNutritionTable | None = None,
    bDropCancelled: bool = True,
) -> list[SOrder]:
    """
    将 MCP 返回的原始订单数据标准化为 SOrder 列表。

    处理要点：
    ① 过滤取消单（orderStatus 含「取消」），被过滤的订单以 strStatus 保留痕迹；
    ② 保留零元单但标记 bFreeOrder（券/积分兑换是真实消费行为，不应丢弃）；
    ③ 拆解套餐 comboItemList，让「最爱单品」统计落到具体餐品而非「精选超值随心配」。

    @param objRawData       order-list / query-order 返回数据
    @param objNutrition     营养表（保留参数，供后续扩展）
    @param bDropCancelled   是否过滤取消单
    @return                 标准化订单列表
    """
    listRaw = _extract_order_list(objRawData)
    listOrders: list[SOrder] = []

    for objItem in listRaw:
        if not isinstance(objItem, dict):
            continue

        #! 取消单过滤
        strStatus = str(_pick(objItem, ("orderStatus", "status", "订单状态")) or "")
        bCancelled = any(strWord in strStatus for strWord in CANCELLED_KEYWORDS)
        if bCancelled and bDropCancelled:
            continue

        objOrder = SOrder()
        objOrder.strStatus = strStatus
        objOrder.bCancelled = bCancelled
        objOrder.strOrderId = str(_pick(objItem, ("orderId", "order_id", "id", "orderNo", "订单号")) or "")
        objOrder.dtTime, objOrder.bHasClock = _parse_datetime_ex(
            _pick(objItem, ("createTime", "createdAt", "orderTime", "time", "date", "下单时间", "订单时间"))
        )
        objOrder.dAmount = _parse_amount(objItem)
        objOrder.bFreeOrder = objOrder.dAmount is None
        objOrder.strChannel = _parse_channel(objItem)

        dictQty, listCombo = _extract_meal_quantities(objItem)
        objOrder.dictItemQty = dictQty
        objOrder.listItems = _expand_items(dictQty)
        objOrder.listComboItems = listCombo

        listOrders.append(objOrder)

    return listOrders


def count_cancelled(objRawData: Any) -> int:
    """
    统计原始数据中的取消单数量（供报告展示「你取消了 N 单」）。

    @param objRawData  原始订单数据
    @return            取消单数量
    """
    nCount = 0
    for objItem in _extract_order_list(objRawData):
        if not isinstance(objItem, dict):
            continue
        strStatus = str(_pick(objItem, ("orderStatus", "status", "订单状态")) or "")
        if any(strWord in strStatus for strWord in CANCELLED_KEYWORDS):
            nCount += 1
    return nCount


def aggregate(
    listOrders: list[SOrder],
    objMatch: Any = None,
    objAccount: Any = None,
    objAvailableCoupons: Any = None,
    objMyCoupons: Any = None,
    objCampaign: Any = None,
    strGeneratedAt: str = "",
) -> SStats:
    """
    聚合统计（纯函数）。

    @param listOrders           标准化订单列表
    @param objMatch             营养匹配结果（SMatchResult）
    @param objAccount           query-my-account 返回数据
    @param objAvailableCoupons  available-coupons 返回数据
    @param objMyCoupons         query-my-coupons 返回数据
    @param objCampaign          campaign-calendar 返回数据
    @param strGeneratedAt       报告生成时间
    @return                     SStats 统计结果
    """
    objStats = SStats()
    objStats.nOrderCount = len(listOrders)
    objStats.strGeneratedAt = strGeneratedAt or datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    # ---- 金额 ----
    listAmounts = [obj.dAmount for obj in listOrders if obj.dAmount is not None and obj.dAmount > 0]
    if listAmounts:
        objStats.bHasAmount = True
        objStats.dTotalAmount = sum(listAmounts)
        objStats.dAmountPerOrder = objStats.dTotalAmount / len(listAmounts)

    # ---- 零元单（券/积分兑换）：单独计数，不污染客单价 ----
    listFree = [obj for obj in listOrders if obj.bFreeOrder and not obj.bCancelled]
    objStats.nFreeOrderCount = len(listFree)
    if listFree and objStats.dAmountPerOrder > 0:
        #! 折算价值：按已付费订单的客单价估算这些「白嫖」的份量
        objStats.dFreeOrderValue = objStats.dAmountPerOrder * len(listFree)

    # ---- 时间跨度 ----
    listTimes = sorted(obj.dtTime for obj in listOrders if obj.dtTime is not None)
    if listTimes:
        objStats.dtEarliest = listTimes[0]
        objStats.dtLatest = listTimes[-1]
        objStats.nSpanDays = max(1, (listTimes[-1] - listTimes[0]).days + 1)
        objStats.strSpanLabel = _make_span_label(objStats.dtEarliest, objStats.dtLatest)

    # ---- 餐品频次 ----
    objCounter: Counter[str] = Counter()
    for obj in listOrders:
        for strItem in obj.listItems:
            objCounter[strItem] += 1
    objStats.listTopItems = objCounter.most_common(5)

    # ---- 月度分布 ----
    dictMonth: dict[str, int] = defaultdict(int)
    for obj in listOrders:
        if obj.dtTime:
            dictMonth[obj.dtTime.strftime("%Y-%m")] += 1
    objStats.dictMonthCount = dict(sorted(dictMonth.items()))

    # ---- 星期分布 ----
    listWeekNames = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    dictWeek: dict[str, int] = defaultdict(int)
    for obj in listOrders:
        if obj.dtTime:
            dictWeek[listWeekNames[obj.dtTime.weekday()]] += 1
    objStats.dictWeekdayCount = {strName: dictWeek.get(strName, 0) for strName in listWeekNames}

    # ---- 时段分布（仅在数据含有效时刻时统计）----
    dictSlot: dict[str, int] = {strName: 0 for strName, _, _ in TIME_SLOTS}
    nSlotTotal = 0
    for obj in listOrders:
        if obj.dtTime is None or not obj.bHasClock:
            continue
        nHour = obj.dtTime.hour
        for strName, nStart, nEnd in TIME_SLOTS:
            if nStart <= nHour < nEnd or (nEnd > 24 and nHour < nEnd - 24):
                dictSlot[strName] += 1
                nSlotTotal += 1
                break
    objStats.dictSlotCount = dictSlot
    objStats.nSlotTotal = nSlotTotal
    if nSlotTotal:
        objStats.bHasClock = True
    else:
        objStats.listWarnings.append("订单数据未包含下单时刻，已跳过「干饭时钟」卡片")
        objStats.listWarnings.append("称号判定不含时段维度")

    # ---- 就餐方式 ----
    dictChannel: dict[str, int] = defaultdict(int)
    for obj in listOrders:
        if obj.strChannel:
            dictChannel[obj.strChannel] += 1
    objStats.dictChannelCount = dict(dictChannel)

    # ---- 营养累计 ----
    if objMatch is not None:
        objStats.dNutritionMatchRate = objMatch.get_rate()
        objStats.nUnmatchedItems = len(objMatch.listUnmatched)
        for strName, nQty in objCounter.items():
            objNutr: SNutrition | None = objMatch.dictMatched.get(strName)
            if objNutr is None:
                continue
            objStats.dTotalEnergy += objNutr.dEnergy * nQty
            objStats.dTotalProtein += objNutr.dProtein * nQty
        if objStats.dNutritionMatchRate < 0.5:
            objStats.listWarnings.append("营养数据匹配率偏低，热量为低估值")

    # ---- 积分与券 ----
    objStats.nPoints, objStats.nTotalPoints, objStats.nExpiringPoints = _parse_account(objAccount)
    objStats.nAvailableCoupons = _count_items(objAvailableCoupons)
    objStats.nMyCoupons = _count_items(objMyCoupons)

    # ---- 活动彩蛋 ----
    objStats.listMissedCampaigns = _parse_campaigns(objCampaign)

    # ---- 称号与洞察 ----
    objStats.listInsights = _make_insights(objStats)
    objStats.strTitleName, objStats.strTitleReason = _decide_title(objStats)

    return objStats


def _make_span_label(dtStart: datetime.datetime, dtEnd: datetime.datetime) -> str:
    """生成统计区间文案。"""
    nDays = (dtEnd - dtStart).days + 1
    if nDays >= 300:
        return f"{dtStart.strftime('%Y.%m')} — {dtEnd.strftime('%Y.%m')}"
    return f"{dtStart.strftime('%Y.%m.%d')} — {dtEnd.strftime('%Y.%m.%d')}（{nDays} 天）"


def _make_insights(objStats: SStats) -> list[str]:
    """
    生成文案钩子列表（梗化但克制）。

    @param objStats  统计结果
    @return          文案列表
    """
    listOut: list[str] = []

    if objStats.nOrderCount and objStats.nSpanDays:
        dFreq = objStats.nSpanDays / objStats.nOrderCount
        if dFreq < 3:
            listOut.append(f"{objStats.nOrderCount} 单，平均每 {dFreq:.1f} 天一餐，麦门日常已上线")
        else:
            listOut.append(f"{objStats.nOrderCount} 单，平均每 {dFreq:.1f} 天一餐")

    if objStats.listTopItems:
        strName, nCount = objStats.listTopItems[0]
        listOut.append(f"{strName}见了你 {nCount} 次，真爱无疑")

    # 峰值月
    if objStats.dictMonthCount:
        strPeakMonth, nPeakCount = max(objStats.dictMonthCount.items(), key=lambda objPair: objPair[1])
        listOut.append(f"{strPeakMonth.split('-')[1]} 月是你的麦门之月（{nPeakCount} 单）")

    # 高峰时段（仅在含有效时刻时输出）
    if objStats.bHasClock and objStats.nSlotTotal:
        strSlot, nSlotCount = max(objStats.dictSlotCount.items(), key=lambda objPair: objPair[1])
        if nSlotCount:
            listOut.append(f"你最常在{strSlot}下单（{nSlotCount} 次）")

    # 深夜党
    if objStats.bHasClock and objStats.nSlotTotal and objStats.dictSlotCount.get("夜宵", 0):
        dNightRatio = objStats.dictSlotCount["夜宵"] / objStats.nSlotTotal
        if dNightRatio > 0.25:
            listOut.append(f"{dNightRatio:.0%} 的订单发生在晚上 9 点后")

    # 花费换算
    if objStats.bHasAmount and objStats.dTotalAmount:
        nCups = int(objStats.dTotalAmount / 18)
        listOut.append(f"这些钱约等于 {nCups} 杯奶茶")

    # 营养换算
    if objStats.dTotalEnergy > 0:
        nBigMac = objStats.dTotalEnergy / KCAL_PER_BIG_MAC
        listOut.append(f"累计热量约 {objStats.dTotalEnergy:.0f} 千卡，≈ {nBigMac:.0f} 个巨无霸。好消息：快乐不计入热量")

    return listOut[:6]


def _decide_title(objStats: SStats) -> tuple[str, str]:
    """
    称号规则引擎。

    规则优先级从上到下，首个命中即返回。

    @param objStats  统计结果
    @return          (称号, 称号理由)
    """
    dictSlot = objStats.dictSlotCount
    nSlotTotal = objStats.nSlotTotal if objStats.bHasClock else 0

    # 规则 1：夜宵占比 > 30%
    if nSlotTotal and dictSlot.get("夜宵", 0) / nSlotTotal > 0.30:
        return ("深夜麦乐送战士", f"你有 {dictSlot['夜宵']} 单发生在晚上 9 点以后")

    # 规则 2：早餐占比 > 40%
    if nSlotTotal and dictSlot.get("早餐", 0) / nSlotTotal > 0.40:
        return ("早餐狂魔", f"{dictSlot['早餐']} 单早餐，清晨的麦门由你守护")

    # 规则 3：单一餐品占比 > 30%
    if objStats.listTopItems and objStats.nOrderCount:
        strName, nCount = objStats.listTopItems[0]
        if nCount / objStats.nOrderCount > 0.30:
            strShort = _short_name(strName)
            return (f"{strShort}信徒", f"{strName}下单 {nCount} 次，占比超过三成")

    # 规则 4：麦乐送占比 > 70%
    nChannelTotal = sum(objStats.dictChannelCount.values())
    if nChannelTotal:
        nDelivery = sum(
            nCount for strKey, nCount in objStats.dictChannelCount.items() if _is_delivery(strKey)
        )
        if nDelivery / nChannelTotal > 0.70:
            return ("麦乐送 VIP", f"{nDelivery / nChannelTotal:.0%} 的订单来自麦乐送")

    # 规则 5：客单价 < 25 元
    if objStats.bHasAmount and 0 < objStats.dAmountPerOrder < 25:
        return ("穷鬼套餐守护者", f"客单价 {objStats.dAmountPerOrder:.1f} 元，精打细算的麦门选手")

    # 规则 6：客单价 > 60 元
    if objStats.bHasAmount and objStats.dAmountPerOrder > 60:
        return ("麦门大户", f"客单价 {objStats.dAmountPerOrder:.1f} 元，出手阔绰")

    # 规则 7：单数极多
    if objStats.nOrderCount >= 100:
        return ("麦门资深信徒", f"全年 {objStats.nOrderCount} 单，出勤率拉满")

    return ("稳健干饭人", "稳定输出的麦门日常")


def _short_name(strName: str) -> str:
    """提取餐品简称（用于称号）。"""
    strClean = re.sub(r"[（(][^)）]*[)）]", "", strName)
    strClean = strClean.replace("套餐", "").replace("汉堡", "堡").strip()
    return strClean[:8] or "麦门"


def _is_delivery(strChannel: str) -> bool:
    """判断就餐方式是否为外送。"""
    strLower = strChannel.lower()
    return any(strWord in strLower or strWord in strChannel for strWord in CHANNEL_DELIVERY)


def _extract_order_list(objData: Any) -> list[Any]:
    """从各种包装结构中提取订单列表。"""
    if isinstance(objData, list):
        return objData
    if isinstance(objData, dict):
        for strKey in ("data", "orders", "list", "items", "result", "orderList"):
            objValue = objData.get(strKey)
            if isinstance(objValue, list):
                return objValue
            if isinstance(objValue, dict):
                listNested = _extract_order_list(objValue)
                if listNested:
                    return listNested
    return []


def _extract_meal_quantities(objItem: dict[str, Any]) -> tuple[dict[str, int], list[str]]:
    """
    提取订单内的餐品及数量，并拆解套餐内含单品。

    真实数据中 orderProductList 的元素结构为::

        {"productCode": "9900015568", "productName": "精选超值随心配", "quantity": 1,
         "comboItemList": [{"productCode": "1600", "name": "麦香鱼", "quantity": 1}, ...]}

    套餐名本身不具备画像价值（全是「精选超值随心配」），因此统计口径落到 comboItemList 的
    单品上；无 comboItemList 的条目直接取自身名称。

    @param objItem  原始订单记录
    @return         (餐品名 -> 数量, 套餐拆解出的单品名称列表)
    """
    dictOut: dict[str, int] = {}
    listCombo: list[str] = []

    listCandidates = None
    for strKey in ("orderProductList", "items", "products", "meals", "details", "orderItems", "productList", "餐品", "商品"):
        objValue = objItem.get(strKey)
        if isinstance(objValue, list):
            listCandidates = objValue
            break

    if listCandidates is None:
        strSingle = _pick(objItem, ("productName", "mealName", "name", "餐品名称"))
        if strSingle:
            dictOut[str(strSingle)] = 1
        return dictOut, listCombo

    for objProduct in listCandidates:
        if not isinstance(objProduct, dict):
            if isinstance(objProduct, str):
                dictOut[objProduct] = dictOut.get(objProduct, 0) + 1
            continue

        nQty = int(_parse_number(_pick(objProduct, ("quantity", "qty", "count", "num", "数量"))) or 1)
        nQty = max(1, nQty)
        objCombo = objProduct.get("comboItemList")

        #! 套餐：统计口径下沉到内含单品
        if isinstance(objCombo, list) and objCombo:
            for objSub in objCombo:
                if not isinstance(objSub, dict):
                    continue
                strSubName = _pick(objSub, ("name", "productName", "mealName", "title", "商品名称"))
                if not strSubName:
                    continue
                nSubQty = int(_parse_number(_pick(objSub, ("quantity", "qty", "count", "num"))) or 1)
                nSubQty = max(1, nSubQty) * nQty
                strSubName = str(strSubName)
                dictOut[strSubName] = dictOut.get(strSubName, 0) + nSubQty
                listCombo.extend([strSubName] * nSubQty)
            continue

        strName = _pick(objProduct, ("name", "productName", "mealName", "title", "商品名称", "餐品名称"))
        if not strName:
            continue
        strName = str(strName)
        dictOut[strName] = dictOut.get(strName, 0) + nQty

    return dictOut, listCombo


def _expand_items(dictQty: dict[str, int]) -> list[str]:
    """将 {餐品: 数量} 展开为重复名称列表（便于 Counter 统计）。"""
    listOut: list[str] = []
    for strName, nQty in dictQty.items():
        listOut.extend([strName] * max(1, nQty))
    return listOut


def _parse_amount(objItem: dict[str, Any]) -> float | None:
    """
    解析订单金额（兼容多种字段与币种符号）。

    真实 order-list 使用 realTotalAmount；零元单（券/积分兑换）返回 None，
    由调用方通过 bFreeOrder 标记保留。

    @param objItem  原始订单记录
    @return         金额；无金额或零元返回 None
    """
    objValue = _pick(
        objItem,
        (
            "realTotalAmount", "totalAmount", "payAmount", "actualAmount", "amount",
            "totalPrice", "price", "orderAmount", "实付", "金额", "总价",
        ),
    )
    if objValue is None:
        return None
    dValue = _parse_number(objValue)
    return dValue if dValue > 0 else None


def _parse_channel(objItem: dict[str, Any]) -> str:
    """
    解析就餐方式。

    真实 order-list 通过 orderType / beType 数字编码标识渠道：
    beType=1 为到店（含外带），其余值按文本关键词兜底判定。

    @param objItem  原始订单记录
    @return         渠道名称（外送 / 到店 / 堂食 / 外带 / 原始文本片段）
    """
    #! 数字编码优先
    objBeType = _pick(objItem, ("beType",))
    objOrderType = _pick(objItem, ("orderType",))
    if objBeType is not None:
        strBe = str(objBeType).strip()
        if strBe == "1":
            return "到店"
        if strBe == "2":
            return "外送"

    #! 文本关键词
    objValue = _pick(objItem, ("takeWay", "channel", "deliveryType", "mode", "takeType", "就餐方式", "取餐方式", "订单类型"))
    if objValue is not None:
        strText = str(objValue)
        strLower = strText.lower()
        if any(strWord in strText for strWord in CHANNEL_TAKEOUT):
            return "到店"
        if any(strWord in strText for strWord in CHANNEL_DELIVERY) or any(strWord in strLower for strWord in CHANNEL_DELIVERY):
            return "外送"
        if strText.strip():
            return strText.strip()[:10]

    if objOrderType is not None:
        return "外送" if str(objOrderType).strip() == "2" else "到店"
    return ""


def _parse_datetime_ex(objValue: Any) -> tuple[datetime.datetime | None, bool]:
    """
    解析时间字段并返回时间精度。

    时间戳与含时刻的字符串返回 (时间, True)；
    仅日期的字符串返回 (时间, False)，此时时刻被置为 00:00:00。

    @param objValue  原始时间值
    @return          (解析结果, 是否含有效时刻)
    """
    if objValue is None:
        return None, False

    # 时间戳必然含时刻
    if isinstance(objValue, (int, float)):
        objTime = _parse_datetime(objValue)
        return objTime, objTime is not None

    strText = str(objValue).strip()
    if not strText:
        return None, False

    # 纯日期格式（无时分秒）判定为不含时刻
    if re.fullmatch(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", strText) or re.fullmatch(
        r"\d{4}年\d{1,2}月\d{1,2}日", strText
    ):
        return _parse_datetime(strText), False

    # 数字字符串可能是时间戳
    if re.fullmatch(r"\d{10,13}", strText):
        objTime = _parse_datetime(int(strText))
        return objTime, objTime is not None

    objTime = _parse_datetime(strText)
    if objTime is None:
        return None, False

    # 字符串中含冒号视为含时刻
    bHasClock = ":" in strText
    return objTime, bHasClock


def _parse_datetime(objValue: Any) -> datetime.datetime | None:
    """解析时间字段（兼容时间戳与多种字符串格式）。"""
    if objValue is None:
        return None
    if isinstance(objValue, (int, float)):
        dValue = float(objValue)
        if dValue > 1e12:
            dValue /= 1000.0
        try:
            return datetime.datetime.fromtimestamp(dValue)
        except (OSError, OverflowError, ValueError):
            return None

    strText = str(objValue).strip()
    if not strText:
        return None
    if re.fullmatch(r"\d{10,13}", strText):
        return _parse_datetime(int(strText))

    listFormats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y年%m月%d日 %H:%M",
        "%Y年%m月%d日",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
    ]
    strClean = strText.replace("+08:00", "").replace("Z", "")
    for strFmt in listFormats:
        try:
            return datetime.datetime.strptime(strClean, strFmt)
        except ValueError:
            continue

    match = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})", strText)
    if match:
        try:
            return datetime.datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    return None


def _parse_account(objData: Any) -> tuple[float, float, float]:
    """
    解析积分账户数据。

    真实 query-my-account 字段：
    availablePoint（可用）/ accumulativePoint（累计）/ usedPoint（已用）/
    expiredPoint（已过期）/ currentMouthExpirePoint（本月将过期）。

    @param objData  query-my-account 返回
    @return         (可用积分, 累计积分, 即将过期积分)
    """
    if not isinstance(objData, dict):
        return 0.0, 0.0, 0.0
    dictFlat = _flatten(objData)
    dPoints = 0.0
    dTotal = 0.0
    dExpiring = 0.0
    for strKey, objValue in dictFlat.items():
        strLower = strKey.lower()
        #! 即将过期（含 currentMouthExpirePoint / nextMouthExpirePoint）
        if "expir" in strLower or "过期" in strKey:
            dExpiring = max(dExpiring, _parse_number(objValue))
        #! 累计积分（优先于可用积分，更具故事性）
        elif "accumul" in strLower or "total" in strLower or "累计" in strKey:
            dTotal = max(dTotal, _parse_number(objValue))
        elif "available" in strLower or "balance" in strLower or "可用" in strKey or strLower == "points":
            dPoints = max(dPoints, _parse_number(objValue))
    return dPoints, dTotal, dExpiring


def _count_items(objData: Any) -> int:
    """
    统计返回数据中的条目数。

    available-coupons / query-my-coupons 实测返回 **Markdown 文本**，
    而非结构化数组，需按 Markdown 结构计数：
    · query-my-coupons → 以 ``## 券名`` 为条目标题；
    · available-coupons → 以 ``- 优惠券标题：xxx`` 为条目。

    @param objData  工具返回数据
    @return         条目数
    """
    if isinstance(objData, list):
        return len(objData)

    #! Markdown 文本形态
    if isinstance(objData, str):
        return _count_markdown_coupons(objData)
    if isinstance(objData, dict):
        objInner = objData.get("data")
        if isinstance(objInner, str):
            return _count_markdown_coupons(objInner)
        for strKey in ("data", "list", "items", "coupons", "result"):
            objValue = objData.get(strKey)
            if isinstance(objValue, list):
                return len(objValue)
            if isinstance(objValue, str):
                return _count_markdown_coupons(objValue)
        return 1 if objData else 0
    return 0


def _count_markdown_coupons(strText: str) -> int:
    """
    统计 Markdown 优惠券文本中的券条目数。

    兼容两种标题层级：``## 券名``（query-my-coupons）
    与 ``- 优惠券标题：券名``（available-coupons）。

    @param strText  Markdown 文本
    @return         券条目数
    """
    if not strText:
        return 0
    nCount = len(re.findall(r"^##\s+", strText, flags=re.MULTILINE))
    if nCount:
        return nCount
    return len(re.findall(r"优惠券标题：", strText))


def _parse_campaigns(objData: Any) -> list[str]:
    """
    解析活动日历，提取活动名称列表。

    campaign-calendar 实测返回 Markdown 文本，活动以
    ``- **活动标题**：xxx`` 的列表项形式给出，需按此结构抽取。

    @param objData  campaign-calendar 返回数据
    @return         活动名称列表
    """
    #! Markdown 文本形态
    if isinstance(objData, str):
        return _parse_campaign_markdown(objData)
    if isinstance(objData, dict):
        objInner = objData.get("data")
        if isinstance(objInner, str):
            return _parse_campaign_markdown(objInner)
        for strKey in ("data", "list", "items", "campaigns", "activities", "result"):
            objValue = objData.get(strKey)
            if isinstance(objValue, list):
                return _parse_campaign_list(objValue)
            if isinstance(objValue, str):
                return _parse_campaign_markdown(objValue)
        if objData:
            return _parse_campaign_list([objData])
    if isinstance(objData, list):
        return _parse_campaign_list(objData)
    return []


def _parse_campaign_markdown(strText: str, nLimit: int = 8) -> list[str]:
    """
    从活动日历 Markdown 文本中抽取活动标题。

    @param strText  Markdown 文本
    @param nLimit   最多返回条数
    @return         活动名称列表（已去重，保持出现顺序）
    """
    if not strText:
        return []
    listOut: list[str] = []
    for strMatch in re.findall(r"\*\*活动标题\*\*\s*[：:]\s*(.+)", strText):
        strName = strMatch.strip()
        #! 剔除 emoji 变体选择符与多余空白，避免卡片排版错乱
        strName = re.sub(r"[\uFE0F\u200D]", "", strName).strip()
        if strName and strName not in listOut:
            listOut.append(strName[:24])
        if len(listOut) >= nLimit:
            break
    return listOut


def _parse_campaign_list(listItems: list[Any]) -> list[str]:
    """从活动列表中提取名称。"""
    listOut: list[str] = []
    for objItem in listItems[:6]:
        if isinstance(objItem, dict):
            strName = _pick(objItem, ("name", "title", "campaignName", "activityName", "活动名称", "名称"))
            if strName:
                listOut.append(str(strName)[:24])
        elif isinstance(objItem, str):
            listOut.append(objItem[:24])
    return listOut


def _flatten(objData: dict[str, Any], strPrefix: str = "") -> dict[str, Any]:
    """展平嵌套字典（仅两层，够用且避免复杂）。"""
    dictOut: dict[str, Any] = {}
    for strKey, objValue in objData.items():
        strFullKey = f"{strPrefix}{strKey}"
        if isinstance(objValue, dict):
            dictOut.update(_flatten(objValue, f"{strFullKey}."))
        else:
            dictOut[strFullKey] = objValue
    return dictOut


def _pick(dictItem: dict[str, Any], tupleKeys: tuple[str, ...]) -> Any:
    """按键名候选列表取值（忽略大小写与分隔符差异）。"""
    for strKey in tupleKeys:
        if strKey in dictItem and dictItem[strKey] not in (None, ""):
            return dictItem[strKey]
    dictLower = {str(k).lower().replace("_", ""): v for k, v in dictItem.items()}
    for strKey in tupleKeys:
        strNorm = strKey.lower().replace("_", "")
        if strNorm in dictLower and dictLower[strNorm] not in (None, ""):
            return dictLower[strNorm]
    return None


def _parse_number(objValue: Any) -> float:
    """从任意值中提取数字。"""
    if objValue is None:
        return 0.0
    if isinstance(objValue, (int, float)):
        return float(objValue)
    match = re.search(r"-?\d+(?:\.\d+)?", str(objValue))
    return float(match.group()) if match else 0.0
