# ClearCheck — 企业级 KYC/AML 合规初筛智能体（AI CAN DO IT 参赛作品）

ClearCheck 是一个面向 B2B 交易/商户准入（KYC/AML）的**风险初筛 Agent**：输入自然语言或结构化信息，输出 **GREEN / YELLOW / RED** 决策，并给出 3 条原因、3 个下一步动作与证据摘要。

## 比赛要求对齐

- 指定工具：本项目在开发过程中使用 **腾讯云 ClawPro / CodeBuddy** 辅助完成整体架构梳理、FastAPI 接口与前端大屏交互效果的快速迭代（满足“至少使用一款指定产品开发”的要求）。
- 演示视频：按官网要求准备 3–5 分钟演示视频，展示完整功能流程。
- 说明文档：本 README 覆盖场景描述、技术方案与效果展示（满足官网要求）。

## 场景与商业价值（Business Value）

在商户准入/供应商准入中，合规团队常面临：
- 信息不全、语言多样（中文/阿语/波斯语/英文）导致的实体名歧义与转写问题
- “高假阳性”带来大量人工复核成本
- 高风险国家/交易要素需要快速提示与标准化处置动作

ClearCheck 将“合规初筛”变成一个可复用的 API + UI 能力，用于内部系统接入与批量处理。

## 亮点与创新点

- 多语种自然语言输入 → 结构化字段抽取（可选：TokenRouter LLM），生成多种别名/转写变体用于 KG 查询
- 规则引擎可解释：所有决策来自可追溯的信号（signals），并输出可执行的下一步动作
- “无依赖演示模式”：不接入外部 KG / LLM 也可运行（内置演示实体库 + 规则兜底），便于评审现场快速复现

## 技术方案（Technical Architecture）

```
自然语言/结构化输入
  → LLM 解析与归一化（可选：TokenRouter）
  → KG 查询（可选：ArangoDB；默认内置演示实体库）
  → 三层规则引擎（实体风险/辖区与交易/数据完整性）
  → 决策 + 原因/动作（可选：LLM 增强；默认规则兜底）
```

## 快速开始（本地运行）

```bash
pip install -r requirements.txt
cp .env.example .env

# 1) 启动 Web（UI + API）
python -m clearcheck --serve --port 8000

# 2) CLI 一次性检查
python -m clearcheck --name "Parsian Bank" --country "Iran"
```

打开：`http://localhost:8000`

## API 使用

### 1) 自然语言（前端使用）
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"query":"我们要接入一家迪拜的 Golden Star Trading，20万美金的电子元器件订单"}'
```

### 2) 结构化（系统集成）
```bash
curl -X POST http://localhost:8000/triage \
  -H "Content-Type: application/json" \
  -d '{"entity_name":"Parsian Bank","country":"Iran","transaction_amount":200000,"goods_category":"financial services"}'
```

## Docker 一键部署

```bash
docker build -t clearcheck .
docker run --rm -p 8000:8000 --env-file .env clearcheck
```

## 目录结构

- `clearcheck/`：核心后端（API + CLI + 规则引擎 + KG 客户端）
- `frontend/`：静态大屏 UI（由后端挂载 `/` 与 `/static`）

## 配置项（.env）

- `TOKENROUTER_API_KEY`：可选；开启后支持更强的多语种解析与“原因/动作”生成
- `ARANGO_URL`：可选；连接真实 ArangoDB 知识图谱（不配置则使用内置演示数据）

## 免责声明

本项目输出为**风险初筛**结果，不构成法律意见；最终决策应由合规人员复核。
