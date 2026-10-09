"""
生成全虚构的示例数据（examples/sample_data.json）。

数据完全虚构，不含任何真实用户信息，用于：
  - `--from-json` 离线模式演示（无 Token 也能一键出报告）
  - README 效果图与截图
  - 回归测试

@file    make_sample_data.py
@brief   构造虚构示例数据
@author  陈京宇
@date    2026-10-09
@copyright Copyright (c) 2026 maimen-wrapped contributors. MIT License.
"""

from __future__ import annotations

import datetime
import json
import os
import random

random.seed(20261009)

#! 虚构餐品池：(名称, 权重)
FOOD_POOL = [
    ("板烧鸡腿堡", 26),
    ("巨无霸", 18),
    ("麦辣鸡腿汉堡", 14),
    ("双层吉士汉堡", 11),
    ("薯条(中)", 16),
    ("可口可乐(中)", 15),
    ("麦乐鸡", 10),
    ("麦辣鸡翅", 7),
    ("奥利奥麦旋风", 5),
    ("猪柳蛋麦满分", 6),
    ("麦香鱼", 4),
    ("玉米杯", 3),
    ("香芋派", 2),
    ("拿铁", 4),
]

#! 虚构营养表
NUTRITION_TABLE = [
    {"name": "板烧鸡腿堡", "energy": 430, "protein": 25.0, "fat": 18.0, "carbohydrate": 41.0, "sodium": 900},
    {"name": "巨无霸", "energy": 510, "protein": 27.0, "fat": 25.0, "carbohydrate": 42.0, "sodium": 950},
    {"name": "麦辣鸡腿堡", "energy": 470, "protein": 23.0, "fat": 21.0, "carbohydrate": 45.0, "sodium": 1020},
    {"name": "双层吉士汉堡", "energy": 450, "protein": 25.0, "fat": 24.0, "carbohydrate": 33.0, "sodium": 1050},
    {"name": "薯条(中)", "energy": 340, "protein": 4.0, "fat": 16.0, "carbohydrate": 44.0, "sodium": 230},
    {"name": "可口可乐(中)", "energy": 150, "protein": 0.0, "fat": 0.0, "carbohydrate": 38.0, "sodium": 12},
    {"name": "麦乐鸡", "energy": 250, "protein": 15.0, "fat": 13.0, "carbohydrate": 18.0, "sodium": 490},
    {"name": "麦辣鸡翅", "energy": 230, "protein": 14.0, "fat": 15.0, "carbohydrate": 10.0, "sodium": 560},
    {"name": "奥利奥麦旋风", "energy": 340, "protein": 6.0, "fat": 12.0, "carbohydrate": 51.0, "sodium": 160},
    {"name": "猪柳蛋麦满分", "energy": 380, "protein": 19.0, "fat": 19.0, "carbohydrate": 31.0, "sodium": 780},
    {"name": "麦香鱼", "energy": 340, "protein": 15.0, "fat": 16.0, "carbohydrate": 34.0, "sodium": 620},
    {"name": "玉米杯", "energy": 90, "protein": 3.0, "fat": 1.0, "carbohydrate": 19.0, "sodium": 5},
    {"name": "香芋派", "energy": 230, "protein": 3.0, "fat": 11.0, "carbohydrate": 29.0, "sodium": 190},
    {"name": "拿铁", "energy": 130, "protein": 7.0, "fat": 6.0, "carbohydrate": 11.0, "sodium": 90},
]

#! 时段权重：制造"深夜党"人设
SLOT_WEIGHTS = {
    "早餐": 8,
    "午餐": 22,
    "下午茶": 10,
    "晚餐": 26,
    "夜宵": 34,
}


def _pick_food_list() -> list[dict]:
    """按权重组一份随机构造的餐品组合。"""
    listNames = [obj[0] for obj in FOOD_POOL]
    listWeights = [obj[1] for obj in FOOD_POOL]
    nSize = random.choices([1, 2, 3, 4], weights=[18, 42, 28, 12])[0]
    listChosen = random.choices(listNames, weights=listWeights, k=nSize)
    listOut: list[dict] = []
    dictSeen: dict[str, int] = {}
    for strName in listChosen:
        dictSeen[strName] = dictSeen.get(strName, 0) + 1
    for strName, nQty in dictSeen.items():
        listOut.append({"name": strName, "quantity": nQty})
    return listOut


def _pick_hour() -> int:
    """按时段权重挑选小时。"""
    listSlots = list(SLOT_WEIGHTS.keys())
    listWeights = [SLOT_WEIGHTS[strKey] for strKey in listSlots]
    strSlot = random.choices(listSlots, weights=listWeights, k=1)[0]
    dictRange = {
        "早餐": (6, 9),
        "午餐": (11, 13),
        "下午茶": (14, 16),
        "晚餐": (17, 20),
        "夜宵": (21, 23),
    }
    nLow, nHigh = dictRange[strSlot]
    return random.randint(nLow, nHigh)


def _pick_channel() -> str:
    """挑选就餐方式（偏麦乐送）。"""
    return random.choices(["外送", "到店"], weights=[68, 32], k=1)[0]


def build_orders(nCount: int = 127) -> list[dict]:
    """
    构造虚构订单列表。

    @param nCount  订单数量
    @return        订单列表
    """
    dtStart = datetime.datetime(2026, 1, 5)
    dtEnd = datetime.datetime(2026, 10, 8)
    nSpan = (dtEnd - dtStart).days

    listOrders: list[dict] = []
    for nIdx in range(nCount):
        dtOrder = dtStart + datetime.timedelta(
            days=random.randint(0, nSpan), hours=random.randint(0, 23), minutes=random.randint(0, 59)
        )
        nHour = _pick_hour()
        dtOrder = dtOrder.replace(hour=nHour, minute=random.randint(0, 59), second=random.randint(0, 59))

        listItems = _pick_food_list()
        dAmount = round(sum(random.uniform(12, 32) for _ in listItems) * random.uniform(0.85, 1.15), 2)
        dAmount = max(11.0, dAmount)

        listOrders.append(
            {
                "orderId": f"DEMO{nIdx + 1:05d}",
                "createTime": dtOrder.strftime("%Y-%m-%d %H:%M:%S"),
                "totalAmount": dAmount,
                "orderType": _pick_channel(),
                "storeName": f"麦当劳(示例门店{random.randint(1, 6)}店)",
                "items": listItems,
            }
        )

    listOrders.sort(key=lambda dictItem: dictItem["createTime"])
    return listOrders


def build_sample_data() -> dict:
    """构造完整的示例数据集（与 MCP 返回结构对齐）。"""
    listOrders = build_orders(127)

    return {
        "nowTime": {"time": "2026-10-09 18:30:00", "weekday": "周五"},
        "orderList": listOrders,
        "orderDetails": [],
        "nutrition": NUTRITION_TABLE,
        "account": {"points": 3240, "availablePoints": 3240, "expiringPoints": 1180, "totalPoints": 12800},
        "availableCoupons": [
            {"couponId": "C001", "name": "满 30 减 8"},
            {"couponId": "C002", "name": "巨无霸第二份半价"},
            {"couponId": "C003", "name": "麦乐送免配送费"},
            {"couponId": "C004", "name": "麦乐鸡买一送一"},
            {"couponId": "C005", "name": "早餐满 15 减 5"},
            {"couponId": "C006", "name": "甜品第二份半价"},
        ],
        "myCoupons": [
            {"couponId": "M001", "name": "薯条免费券"},
            {"couponId": "M002", "name": "可乐升杯券"},
        ],
        "mallOrders": [],
        "campaign": {
            "data": [
                {"name": "麦麦农场春日季"},
                {"name": "超级午餐周"},
                {"name": "麦乐送免配送费日"},
                {"name": "甜筒回归限定"},
                {"name": "麦麦夜市烧烤季"},
            ]
        },
        "_meta": {
            "note": "本数据完全虚构，仅用于 maimen-wrapped 的演示与测试，不含任何真实个人信息。",
            "generatedAt": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "generator": "examples/make_sample_data.py",
        },
    }


def main() -> None:
    """生成并写入 examples/sample_data.json。"""
    strDir = os.path.dirname(os.path.abspath(__file__))
    strPath = os.path.join(strDir, "sample_data.json")
    dictData = build_sample_data()
    with open(strPath, "w", encoding="utf-8") as file:
        json.dump(dictData, file, ensure_ascii=False, indent=2)
    print(f"[完成] 示例数据已生成：{strPath}")
    print(f"        订单 {len(dictData['orderList'])} 单，营养表 {len(dictData['nutrition'])} 条")
    print(f"        用法：python -m maimen_wrapped --from-json {os.path.relpath(strPath)}")


if __name__ == "__main__":
    main()
