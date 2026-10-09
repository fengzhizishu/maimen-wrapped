"""
麦当劳 MCP Server 客户端封装。

提供 streamable HTTP 连接、工具调用、并发限速与错误重试能力。

@file    mcp_client.py
@brief   麦当劳 MCP Server 调用封装（限速 / 退避 / 异常映射）
@author  陈京宇
@date    2026-10-09
@copyright Copyright (c) 2026 maimen-wrapped contributors. MIT License.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client


#! 麦当劳 MCP Server 接入地址
MCD_MCP_URL = "https://mcp.mcd.cn"

#! 官方限流阈值：每分钟 600 次请求
RATE_LIMIT_PER_MINUTE = 600

#! 默认并发数（保守取值，避免触发限流）
DEFAULT_CONCURRENCY = 5

#! 每次调用之间的最小间隔（秒）
DEFAULT_INTERVAL = 0.1

#! 单次工具调用超时（秒）
DEFAULT_CALL_TIMEOUT = 30.0


class McdMcpError(Exception):
    """麦当劳 MCP 调用异常基类。"""


class McdTokenError(McdMcpError):
    """Token 无效、过期或未提供（对应 HTTP 401）。"""


class McdRateLimitError(McdMcpError):
    """触发限流（对应 HTTP 429）。"""


class McdMcpClient:
    """
    麦当劳 MCP Server 异步客户端。

    使用 streamable HTTP 协议连接，内置并发控制与 429 指数退避。
    建议通过 async with 语句使用，以保证连接正确释放。

    @author 陈京宇
    @date   2026-10-09
    """

    def __init__(self, strToken: str, strUrl: str = MCD_MCP_URL, nConcurrency: int = DEFAULT_CONCURRENCY):
        """
        构造 MCP 客户端。

        @param strToken       麦当劳 MCP Token
        @param strUrl         MCP Server 接入地址
        @param nConcurrency   并发调用上限
        """
        if not strToken or strToken == "your_token_here":
            raise McdTokenError("未提供有效的 MCP Token，请通过 --token 参数或 MCD_MCP_TOKEN 环境变量传入。")

        self.m_strToken = strToken
        self.m_strUrl = strUrl
        self.m_nConcurrency = max(1, int(nConcurrency))
        self.m_sem = asyncio.Semaphore(self.m_nConcurrency)
        self.m_dLastCallAt = 0.0
        self.m_lock = asyncio.Lock()
        self.m_session: ClientSession | None = None
        self.m_httpClient = None
        self.m_stack = None

    async def __aenter__(self) -> "McdMcpClient":
        """建立连接并初始化会话。"""
        import contextlib

        self.m_stack = contextlib.AsyncExitStack()
        self.m_httpClient = create_mcp_http_client(
            headers={"Authorization": f"Bearer {self.m_strToken}"}
        )
        await self.m_stack.enter_async_context(self.m_httpClient)
        read, write = await self.m_stack.enter_async_context(
            streamable_http_client(self.m_strUrl, http_client=self.m_httpClient)
        )
        self.m_session = await self.m_stack.enter_async_context(ClientSession(read, write))
        await self.m_session.initialize()
        return self

    async def __aexit__(self, excType, excVal, excTb) -> None:
        """关闭会话与连接。"""
        if self.m_stack is not None:
            await self.m_stack.aclose()
        self.m_session = None
        self.m_httpClient = None
        self.m_stack = None

    async def list_tools(self) -> list[str]:
        """
        获取服务端可用工具名称列表。

        @return 工具名称列表
        """
        result = await self.m_session.list_tools()
        return [tool.name for tool in result.tools]

    async def _throttle(self) -> None:
        """全局节流：保证相邻两次调用之间不少于最小间隔。"""
        async with self.m_lock:
            loop = asyncio.get_running_loop()
            dNow = loop.time()
            dWait = DEFAULT_INTERVAL - (dNow - self.m_dLastCallAt)
            if dWait > 0:
                await asyncio.sleep(dWait)
            self.m_dLastCallAt = loop.time()

    async def call_tool(self, strName: str, dictArgs: dict[str, Any] | None = None, nMaxRetry: int = 3) -> Any:
        """
        调用指定工具，自动处理限流与瞬时错误。

        @param strName     工具名称
        @param dictArgs    工具参数
        @param nMaxRetry   最大重试次数（针对 429 与网络抖动）
        @return            工具返回的解析后数据
        @throws McdTokenError      Token 无效
        @throws McdRateLimitError  重试后仍被限流
        @throws McdMcpError        其他调用失败
        """
        dictArgs = dictArgs or {}
        dBackoff = 1.0

        async with self.m_sem:
            for nAttempt in range(nMaxRetry + 1):
                await self._throttle()
                try:
                    result = await self.m_session.call_tool(
                        strName, dictArgs, read_timeout_seconds=DEFAULT_CALL_TIMEOUT
                    )
                except Exception as exc:  # SDK 异常类型随版本变化，统一在此映射
                    strMsg = str(exc)
                    if _is_token_error(strMsg):
                        raise McdTokenError(
                            "MCP Token 无效或已过期，请前往 https://open.mcd.cn/mcp 重新申请。"
                        ) from exc
                    if _is_rate_limit_error(strMsg):
                        if nAttempt >= nMaxRetry:
                            raise McdRateLimitError("触发 MCP 服务限流（600 次/分钟），重试后仍失败。") from exc
                        await asyncio.sleep(dBackoff + random.uniform(0, 0.3))
                        dBackoff *= 2
                        continue
                    if nAttempt >= nMaxRetry:
                        raise McdMcpError(f"调用工具 {strName} 失败：{strMsg}") from exc
                    await asyncio.sleep(dBackoff * 0.5)
                    dBackoff *= 2
                    continue

                return _parse_result(result, strName)

        raise McdMcpError(f"调用工具 {strName} 失败：重试次数已耗尽。")

    async def call_tools_concurrent(
        self, strName: str, listArgs: list[dict[str, Any]], bIgnoreErrors: bool = True
    ) -> list[Any]:
        """
        并发调用同一工具多次（用于批量补全订单详情）。

        @param strName         工具名称
        @param listArgs        参数列表，每个元素对应一次调用
        @param bIgnoreErrors   单次失败是否忽略（记入警告而不中断整体流程）
        @return                结果列表，失败项为 None
        """
        async def _one(dictArg: dict[str, Any]) -> Any:
            try:
                return await self.call_tool(strName, dictArg)
            except McdTokenError:
                raise
            except McdMcpError:
                if bIgnoreErrors:
                    return None
                raise

        return await asyncio.gather(*[_one(dictArg) for dictArg in listArgs])


def _is_token_error(strMsg: str) -> bool:
    """判断异常信息是否表示 Token 问题。"""
    strLower = strMsg.lower()
    if "401" in strMsg or "unauthorized" in strLower:
        return True
    return "token" in strLower and ("invalid" in strLower or "expired" in strLower)


def _is_rate_limit_error(strMsg: str) -> bool:
    """判断异常信息是否表示限流。"""
    strLower = strMsg.lower()
    return "429" in strMsg or "rate limit" in strLower or "too many requests" in strLower


def _parse_result(result: Any, strTool: str) -> Any:
    """
    解析 MCP 工具返回结果。

    优先提取 structuredContent；其次解析文本内容中的 JSON。

    @param result    call_tool 原始返回
    @param strTool   工具名称（仅用于异常提示）
    @return          解析后的 Python 对象
    """
    dictStructured = getattr(result, "structuredContent", None)
    if dictStructured:
        return dictStructured

    listParts: list[str] = []
    for item in getattr(result, "content", None) or []:
        strText = getattr(item, "text", None)
        if strText:
            listParts.append(strText)

    strPayload = "\n".join(listParts).strip()
    if not strPayload:
        return None

    if getattr(result, "isError", False):
        raise McdMcpError(f"工具 {strTool} 返回错误：{strPayload}")

    try:
        return json.loads(strPayload)
    except json.JSONDecodeError:
        pass

    objMatched = _extract_json_block(strPayload)
    if objMatched is not None:
        return objMatched

    return strPayload


def _extract_json_block(strText: str) -> Any:
    """
    从混合文本中抽取第一个合法 JSON 块。

    @param strText  原始文本
    @return         解析结果；未找到返回 None
    """
    for match in re.finditer(r"[\[{]", strText):
        nStart = match.start()
        for strEndChar in ("]", "}"):
            nEnd = strText.rfind(strEndChar)
            if nEnd <= nStart:
                continue
            strCandidate = strText[nStart : nEnd + 1]
            try:
                return json.loads(strCandidate)
            except json.JSONDecodeError:
                continue
    return None


def resolve_token(strCliToken: str | None = None) -> str:
    """
    按优先级解析 MCP Token。

    优先级：命令行参数 > 环境变量 > .env 文件。

    @param strCliToken  命令行传入的 Token
    @return             解析到的 Token
    @throws McdTokenError  未找到任何 Token
    """
    if strCliToken and strCliToken.strip() and strCliToken != "your_token_here":
        return strCliToken.strip()

    strEnv = os.environ.get("MCD_MCP_TOKEN", "").strip()
    if strEnv and strEnv != "your_token_here":
        return strEnv

    strEnvFile = _read_env_file(".env")
    if strEnvFile:
        return strEnvFile

    raise McdTokenError(
        "未找到 MCP Token。请通过以下任一方式提供：\n"
        "  1) 命令行参数：--token <YOUR_TOKEN>\n"
        "  2) 环境变量：  MCD_MCP_TOKEN=<YOUR_TOKEN>\n"
        "  3) 配置文件：  复制 .env.example 为 .env 并填入 Token\n"
        "申请地址：https://open.mcd.cn/mcp"
    )


def _read_env_file(strPath: str) -> str:
    """
    从 .env 文件读取 MCD_MCP_TOKEN（零第三方依赖实现）。

    @param strPath  .env 文件路径
    @return        Token；未找到返回空字符串
    """
    if not os.path.isfile(strPath):
        return ""
    try:
        with open(strPath, "r", encoding="utf-8") as file:
            for strLine in file:
                strLine = strLine.strip()
                if not strLine or strLine.startswith("#") or "=" not in strLine:
                    continue
                strKey, _, strValue = strLine.partition("=")
                if strKey.strip() == "MCD_MCP_TOKEN":
                    strValue = strValue.strip().strip('"').strip("'")
                    if strValue and strValue != "your_token_here":
                        return strValue
    except OSError:
        return ""
    return ""
