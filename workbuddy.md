# workbuddy.md — WorkBuddy 开发上下文记录

> 本文件记录「麦门画像 · maimen-wrapped」项目使用腾讯 WorkBuddy 智能体开发的过程上下文，
> 用于「2026 麦当劳程序员创意开发大赛」WorkBuddy 专项奖励核验。

## 项目信息

| 项 | 内容 |
| --- | --- |
| 项目名 | 麦门画像 · maimen-wrapped |
| 仓库 | https://github.com/fengzhizishu/maimen-wrapped |
| 开发时间 | 2026-10-09（大赛 Day 1）17:39 起 |
| 开发工具 | 腾讯 WorkBuddy（Agent 模式，全程人机协作） |
| MCP | 麦当劳中国官方 MCP Server（https://mcp.mcd.cn，实测 35 tools） |
| 技术栈 | Python 3.13 + 官方 mcp SDK 2.3.0（唯一第三方依赖，其余全标准库） |

## 开发过程时间线

### Phase 0：创意收敛与赛事情报（10-09 17:39 - 18:10）

1. **创意头脑风暴**：WorkBuddy 结合麦当劳 MCP 能力清单，提出多个方向；经多轮筛选，
   用户选定「麦门年度画像」——对标 Spotify Wrapped 的个人消费报告。
2. **形态升级**：用户反馈「不够有吸引力，要更讨喜更具备传播度」→ WorkBuddy 将方案从
   「单个长页报告」重构为 **10 张 9:16 全屏卡片流**（CSS scroll-snap，每张可独立截图）。
3. **BGM 合规决策**：用户原希望使用麦当劳官方歌曲 → WorkBuddy 做了版权与活动条款风险分析，
   说明官方音乐素材存在侵权风险且活动规则禁止暗示官方背书 → 用户确认改用
   **Web Audio 原创合成**（triangle 波 + ADSR 包络 + C 大调五声音阶，约 100 行 JS，零音频文件）。
4. **赛事情报调研**：抓取官方活动仓库 README + activityGuidelines.md 全文，
   确认排名规则（纯公开 Star 数）、5 项必备文件、Issue 报名格式与 1000 字限制。

### Phase 1：项目骨架与离线可跑（10-09 18:03 - 18:12）

WorkBuddy 一次性交付完整可运行项目（首次提交 23 文件 / 6494 行）：

- `mcp_client.py`：MCP 客户端封装，信号量并发 5 + 调用间隔 100ms + 429 指数退避
- `probe.py`：`--probe` 探查模式，一键核对账号字段完整度并生成 `SCHEMA_REPORT.md`
- `nutrition.py`：餐品名三级匹配（归一化精确 → difflib ≥0.65 → aliases.json 兜底）
- `aggregate.py`：统计聚合 + 麦门称号规则引擎（纯函数，无 IO，便于测试）
- `render.py` + `templates/report.html`：卡片流渲染与动画/BGM
- `examples/`：全虚构示例数据生成器（`random.seed` 固定可复现）+ 示例报告

**关键设计**：`--from-json` 离线模式让项目**无需 Token 即可跑通全流程**，降低评审与试用门槛。

### Phase 2：真实数据适配（10-09 22:17 - 22:30）

用户提供真实 MCP Token 后执行 `--probe`，WorkBuddy 分析探测结果并修复了 **8 个问题**：

**数据层三项核心缺陷**

1. **紧凑表格式解析**：`list-nutrition-foods` 返回的不是 JSON，而是
   `[160]{productName,energyKj,energyKcal,...}:` + 缩进 CSV 的自定义文本格式。
   → 新增 `_load_compact_text()` / `_parse_compact_row()`，解析表头得到列名后逐行 zip，
   优先取 `energyKcal` 避免单位换算误差，同名去重 → 成功加载 **158 条**。

2. **套餐拆解**：10 单中有 9 单是套餐，`productName` 全是「精选超值随心配」等套餐名。
   → 重写 `_extract_meal_quantities()`，统计口径下沉到 `comboItemList` 单品。
   **效果对比**：拆解前「本命餐品 TOP1 = 精选超值随心配」（无传播力）；
   拆解后「麦香鱼 x6」（真实且有分享欲）。

3. **取消单 / 零元单混杂**：`orderStatus` 含「订单已取消」，`realTotalAmount` 有 3 单为 `"0"`
   （券/积分兑换）。
   → 取消单过滤并独立计数（边界卡展示）；零元单**保留**并标记 `bFreeOrder`
   —— 直接丢弃会损失约 30% 样本。

**顺手修复的 5 个问题**

4. `available-coupons` / `query-my-coupons` 返回 Markdown 文本（非数组），券计数失效
   → 新增 `_count_markdown_coupons()` 分别按 `## 券名` 与 `- 优惠券标题：` 计数。
5. `campaign-calendar` 返回 Markdown，原始 `###` 标记泄漏到卡片 → 新增 `_parse_campaign_markdown()`。
6. 积分取错字段（显示「可用积分 214」）→ 改为三元组解析，优先展示累计积分 2390（更具故事性）。
7. 称号卡金额格式化 bug：`¥146.8` 被显示成「¥0.1k」→ 按阈值切换整数元展示。
8. `mall-order-list` 服务端 JSON Schema 缺陷（`type` 字段被声明为数组）导致超长报错刷屏
   → 移出调用范围并截断异常文本。

### Phase 3：产品定位修正（10-09 22:26）

WorkBuddy 核查官方 MCP 仓库 README 后确认：**`order-list` 未定义任何入参**，
实测 14 种分页参数组合均只返回相同 10 单 —— 这是**平台固有约束**。

据此建议并实施定位修正：**放弃「年度」表述**（10 单撑不起年度），
标题改为「麦门画像」，并在卡片流末尾**新增第 11 张「数据边界说明卡」**，
如实列出样本订单数 / 覆盖区间 / 已剔除取消单 / 券积分兑换单。

> 这是本项目与同类方案的关键差异：**不回避数据边界，而是把它作为产品诚实度的一部分**。

### Phase 4：发布与报名（10-09 22:28 - 22:38）

1. **推送前安全自检**：`.gitignore` 覆盖验证、全仓正则搜索 `sk-*`/`gho_`/`ghp_`/`Bearer` 零命中、
   远端 tree 核查无敏感文件、`CONTEST_DECLARATION.md` 与官方**字节级比对一致**（1522 bytes）。
2. **创建公开仓库**：`fengzhizishu/maimen-wrapped`，默认分支 `main`，配置 topics。
3. **必备文件补漏**：WorkBuddy 比对 README 与 activityGuidelines.md 时发现**两份文档清单不一致**
   —— 正式规则额外要求 `mcp-config.example.json`（README 漏列）。
   已补建该文件（仅含 `${MCD_MCP_TOKEN}` 环境变量占位符，无真实凭据），避免报名失败。
4. **报名 Issue 起草**：控制在 **987 字符**（限制 1000）、无图片无外链，已提交 Issue #138。

## 使用的 WorkBuddy 能力

- **Agent 模式文件读写**：项目全部代码由 WorkBuddy 编写（5 个模块 + 模板 + 文档）
- **Bash 工具**：执行 Python 调试、git 操作、MCP 协议级调用、字节级文件比对
- **WebFetch / WebSearch**：MCP 官方文档核实、赛事规则调研、导出方案检索
- **内置依赖隔离环境**：在托管 venv 中安装 mcp SDK，不污染系统环境
- **多轮交互确认**：Token 配置、产品定位、BGM 方案、执行优先级等关键决策均与用户确认后实施

## 数据与安全声明

- MCP Token 仅存于 `.env`（已 gitignore）与环境变量，**未出现在任何提交文件中**
- 推送前已做全仓密钥正则自检，远端确认无 `.env` / `data/` / `output/` / `.workbuddy`
- **只读原则**：全程仅调用查询类工具，未调用 `create-order` / `cancel-order` /
  `draw-lottery` / `mall-create-order` 等任何写操作工具
- 示例数据（`examples/`）为 `random.seed(20261009)` 生成的全虚构数据，不含真实用户信息
- 真实探针数据存放于 `data/probe/`，已被 gitignore 排除，不进入仓库

## 开发结果

- **11 张卡片**（含数据边界说明卡），真实数据端到端跑通
- 营养匹配率 **100%**（158 条营养表）
- 降级验证：完整 11 张 / 无金额无营养 7 张 / 无时刻 7 张，页码动态重排全部正确
- 报名 Issue #138 已提交
