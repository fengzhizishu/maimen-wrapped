"""
餐品营养数据加载与匹配。

将订单中的餐品名称映射到营养表的营养数据，采用三级匹配策略：
① 归一化精确匹配 → ② difflib 模糊匹配 → ③ aliases.json 手动映射表兜底。

@file    nutrition.py
@brief   餐品名到营养数据的映射（三级匹配 + 匹配率统计）
@author  陈京宇
@date    2026-10-09
@copyright Copyright (c) 2026 maimen-wrapped contributors. MIT License.
"""

from __future__ import annotations

import difflib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any


#! 模糊匹配阈值（低于该值不认为匹配成功）
FUZZY_THRESHOLD = 0.65

#! aliases.json 路径
ALIASES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aliases.json")

#! 归一化时需剔除的噪声词
NOISE_PATTERNS = [
    r"[（(][^)）]*[)）]",      # 括号及其内容：(中)、(大)、(套餐)
    r"套餐",
    r"单点",
    r"组合",
    r"\s+",
    r"·",
    r"[，,。.]",
]


@dataclass
class SNutrition:
    """
    单个餐品的营养数据。

    @author 陈京宇
    @date   2026-10-09
    """

    strName: str = ""
    dEnergy: float = 0.0        #!< 能量（kcal）
    dProtein: float = 0.0       #!< 蛋白质（g）
    dFat: float = 0.0           #!< 脂肪（g）
    dCarbohydrate: float = 0.0  #!< 碳水化合物（g）
    dSodium: float = 0.0        #!< 钠（mg）
    strRawUnit: str = ""        #!< 原始能量单位（kJ 或 kcal）


@dataclass
class SMatchResult:
    """
    匹配结果统计。

    @author 陈京宇
    @date   2026-10-09
    """

    dictMatched: dict[str, SNutrition] = field(default_factory=dict)   #!< 原始餐品名 -> 营养数据
    dictSuspicious: dict[str, tuple[str, float]] = field(default_factory=dict)  #!< 疑似匹配（0.5-0.65）
    listUnmatched: list[str] = field(default_factory=list)             #!< 未匹配餐品名列表

    def get_rate(self) -> float:
        """计算匹配率（0-1）。"""
        nTotal = len(self.dictMatched) + len(self.listUnmatched)
        if nTotal == 0:
            return 1.0
        return len(self.dictMatched) / nTotal


class CNutritionTable:
    """
    营养表：加载、索引与匹配。

    @author 陈京宇
    @date   2026-10-09
    """

    def __init__(self) -> None:
        """构造空的营养表。"""
        self.m_dictByNorm: dict[str, SNutrition] = {}
        self.m_listAll: list[SNutrition] = []
        self.m_dictAliases: dict[str, str] = {}
        self.m_dictAliasCache: dict[str, SNutrition | None] = {}

    def load_from_mcp(self, objData: Any) -> int:
        """
        从 MCP list-nutrition-foods 返回数据加载营养表。

        @param objData  MCP 返回数据
        @return         加载条数
        """
        listItems = _extract_list(objData)
        for objItem in listItems:
            if not isinstance(objItem, dict):
                continue
            objNutr = _parse_nutrition_item(objItem)
            if objNutr and objNutr.strName:
                self.m_listAll.append(objNutr)
                self.m_dictByNorm[normalize_name(objNutr.strName)] = objNutr
        self._load_aliases()
        return len(self.m_listAll)

    def load_from_file(self, strPath: str) -> int:
        """
        从本地 JSON 文件加载营养表（缓存场景）。

        @param strPath  JSON 文件路径
        @return         加载条数
        """
        if not os.path.isfile(strPath):
            return 0
        with open(strPath, "r", encoding="utf-8") as file:
            objData = json.load(file)
        return self.load_from_mcp(objData)

    def save_cache(self, strPath: str) -> None:
        """
        保存营养表缓存到本地。

        @param strPath  输出路径
        """
        listData = [
            {
                "name": objNutr.strName,
                "energy": objNutr.dEnergy,
                "protein": objNutr.dProtein,
                "fat": objNutr.dFat,
                "carbohydrate": objNutr.dCarbohydrate,
                "sodium": objNutr.dSodium,
                "unit": objNutr.strRawUnit,
            }
            for objNutr in self.m_listAll
        ]
        with open(strPath, "w", encoding="utf-8") as file:
            json.dump(listData, file, ensure_ascii=False, indent=2)

    def match_many(self, listNames: list[str]) -> SMatchResult:
        """
        批量匹配餐品名。

        @param listNames  餐品名列表（可重复）
        @return           匹配结果统计
        """
        objResult = SMatchResult()
        dictCache: dict[str, SNutrition | None] = {}

        for strName in listNames:
            if strName in dictCache:
                objNutr = dictCache[strName]
            else:
                objNutr = self.match_one(strName)
                dictCache[strName] = objNutr

            if objNutr is not None:
                objResult.dictMatched[strName] = objNutr
            else:
                objSuspicious = self._find_suspicious(strName)
                if objSuspicious is not None:
                    objResult.dictSuspicious[strName] = objSuspicious
                if strName not in objResult.listUnmatched:
                    objResult.listUnmatched.append(strName)

        return objResult

    def match_one(self, strName: str) -> SNutrition | None:
        """
        匹配单个餐品名（三级匹配）。

        @param strName  餐品名
        @return         营养数据；未匹配返回 None
        """
        if not strName:
            return None

        strNorm = normalize_name(strName)
        if not strNorm:
            return None

        # 第一级：归一化精确匹配
        objNutr = self.m_dictByNorm.get(strNorm)
        if objNutr is not None:
            return objNutr

        # 第三级（提前查表）：aliases.json 手动映射
        if strNorm in self.m_dictAliases:
            strTarget = normalize_name(self.m_dictAliases[strNorm])
            objNutr = self.m_dictByNorm.get(strTarget)
            if objNutr is not None:
                return objNutr
        if strName in self.m_dictAliases:
            strTarget = normalize_name(self.m_dictAliases[strName])
            objNutr = self.m_dictByNorm.get(strTarget)
            if objNutr is not None:
                return objNutr

        # 第二级：difflib 模糊匹配
        listNormKeys = list(self.m_dictByNorm.keys())
        if not listNormKeys:
            return None
        listClose = difflib.get_close_matches(strNorm, listNormKeys, n=1, cutoff=FUZZY_THRESHOLD)
        if listClose:
            return self.m_dictByNorm[listClose[0]]

        return None

    def _find_suspicious(self, strName: str) -> tuple[str, float] | None:
        """
        查找疑似匹配（相似度 0.5-0.65），供人工核对补充 aliases。

        @param strName  餐品名
        @return         (候选名, 相似度)；无候选返回 None
        """
        strNorm = normalize_name(strName)
        if not strNorm:
            return None
        objBest = None
        dBest = 0.0
        for strKey in self.m_dictByNorm.keys():
            dRatio = difflib.SequenceMatcher(None, strNorm, strKey).ratio()
            if dRatio > dBest:
                dBest = dRatio
                objBest = strKey
        if objBest is not None and 0.5 <= dBest < FUZZY_THRESHOLD:
            return (objBest, round(dBest, 3))
        return None

    def _load_aliases(self) -> None:
        """加载 aliases.json 映射表。"""
        if not os.path.isfile(ALIASES_PATH):
            return
        try:
            with open(ALIASES_PATH, "r", encoding="utf-8") as file:
                objData = json.load(file)
            if isinstance(objData, dict):
                dictMap = objData.get("mappings", objData)
                if isinstance(dictMap, dict):
                    self.m_dictAliases = {
                        strKey: strValue
                        for strKey, strValue in dictMap.items()
                        if not strKey.startswith("_") and isinstance(strValue, str)
                    }
        except (OSError, json.JSONDecodeError):
            self.m_dictAliases = {}


def normalize_name(strName: str) -> str:
    """
    归一化餐品名：剔除括号内容、规格后缀、空白与标点。

    @param strName  原始餐品名
    @return         归一化名称
    """
    if not strName:
        return ""
    strResult = strName
    for strPattern in NOISE_PATTERNS:
        strResult = re.sub(strPattern, "", strResult)
    strResult = strResult.replace("（", "").replace("）", "").replace("(", "").replace(")", "")
    strResult = strResult.lower()
    return strResult


def _extract_list(objData: Any) -> list[Any]:
    """从各种包装结构中提取列表。"""
    if isinstance(objData, list):
        return objData
    if isinstance(objData, dict):
        for strKey in ("data", "list", "items", "foods", "result", "nutrition"):
            objValue = objData.get(strKey)
            if isinstance(objValue, list):
                return objValue
            if isinstance(objValue, dict):
                listNested = _extract_list(objValue)
                if listNested:
                    return listNested
    return []


def _parse_nutrition_item(objItem: dict[str, Any]) -> SNutrition | None:
    """
    解析单条营养记录，兼容多种字段命名。

    @param objItem  原始记录
    @return         营养数据；解析失败返回 None
    """
    strName = _pick(objItem, ("name", "food_name", "foodName", "餐品名称", "名称", "product_name", "title"))
    if not strName:
        return None

    objNutr = SNutrition(strName=str(strName))
    objNutr.dEnergy, objNutr.strRawUnit = _parse_energy(objItem)
    objNutr.dProtein = _parse_number(
        _pick(objItem, ("protein", "protein_g", "蛋白质", "proteinContent"))
    )
    objNutr.dFat = _parse_number(_pick(objItem, ("fat", "fat_g", "脂肪", "fatContent")))
    objNutr.dCarbohydrate = _parse_number(
        _pick(objItem, ("carbohydrate", "carbohydrates", "carbohydrate_g", "碳水化合物", "carb", "carbs"))
    )
    objNutr.dSodium = _parse_number(_pick(objItem, ("sodium", "sodium_mg", "钠", "sodiumContent")))
    return objNutr


def _parse_energy(objItem: dict[str, Any]) -> tuple[float, str]:
    """
    解析能量字段，自动识别并统一为 kcal。

    @param objItem  原始记录
    @return         (kcal 数值, 原始单位标识)
    """
    objValue = _pick(objItem, ("energy", "energy_kj", "energy_kcal", "calorie", "calories", "能量", "热量", "energyValue"))
    if objValue is None:
        return 0.0, ""

    strText = str(objValue).lower()
    dValue = _parse_number(objValue)

    if "kj" in strText or "千焦" in strText:
        return dValue / 4.184, "kJ"
    if "kcal" in strText or "千卡" in strText or "大卡" in strText:
        return dValue, "kcal"
    # 无单位标识时按国内营养表惯例判定：数值 > 1000 视为 kJ
    if dValue > 1000:
        return dValue / 4.184, "kJ(推定)"
    return dValue, "kcal(推定)"


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


def load_nutrition_table(objMcpData: Any = None, strCachePath: str = "") -> CNutritionTable:
    """
    加载营养表的便捷函数：优先使用 MCP 数据，否则回退本地缓存。

    @param objMcpData     MCP list-nutrition-foods 返回数据
    @param strCachePath   本地缓存路径
    @return              营养表实例
    """
    objTable = CNutritionTable()
    if objMcpData:
        nCount = objTable.load_from_mcp(objMcpData)
        if nCount and strCachePath:
            try:
                objTable.save_cache(strCachePath)
            except OSError:
                pass
        return objTable

    if strCachePath:
        objTable.load_from_file(strCachePath)
    if not objTable.m_listAll:
        objTable._load_aliases()
    return objTable
