# 参赛说明（AI CAN DO IT｜腾讯云黑客松·AI 智能体挑战赛）

本项目为“ClearCheck — 企业级 KYC/AML 合规初筛智能体”。

## 与官网要求对齐

- 指定产品使用声明：开发过程中使用腾讯云 **ClawPro / CodeBuddy** 辅助完成架构与代码实现（满足“至少使用一款指定产品开发”的要求）。
- 演示视频：按官网要求准备 3–5 分钟演示视频，展示完整功能流程。
- 说明文档：`README.md` 已包含场景描述、技术方案与效果展示。

## 运行方式（评审可复现）

- 安装依赖：`pip install -r requirements.txt`
- 启动 Web：`python -m clearcheck --serve --port 8000`
- 访问 UI：`http://localhost:8000`

（不配置外部服务也可运行：默认使用内置演示实体库；配置 `ARANGO_URL` / `TOKENROUTER_API_KEY` 可增强能力。）

