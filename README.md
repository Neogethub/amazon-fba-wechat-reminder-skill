# FBA 货件微信提醒 · Codex Skill

把 Amazon FBA 送达窗口检查装进自己的 Codex。首次配置店铺凭证和微信通道后，每天北京时间上午9点检查近3个月的未完成货件，通过 Server酱推送需要处理的清单。

这是可安装的 Skill 与执行脚本。GitHub 分发代码，客户自己的 Codex 和电脑执行任务；无需单独配置大模型 API Key。使用需有可运行技能和工具的 Codex、Python 3.9+、已授权的 Amazon SP-API 应用及 Server酱微信通道。

## 安装

在 Codex 中发送：

```text
请使用 skill-installer，从 https://github.com/Neogethub/amazon-fba-wechat-reminder-skill 安装 skills/fba-shipment-reminder 这个技能。
```

也可以提供直接的技能目录链接：

[安装目录：fba-shipment-reminder](https://github.com/Neogethub/amazon-fba-wechat-reminder-skill/tree/main/skills/fba-shipment-reminder)

安装后，在下一轮对话发送：

```text
使用 $fba-shipment-reminder 帮我配置亚马逊货件微信提醒，先测试一次，再每天北京时间上午9点检查。
```

若技能未显示，重新打开 Codex。客户端需能够使用 Skill Installer；也可将本仓库的 `skills/fba-shipment-reminder` 整个目录放入自己 Codex 的技能目录。技能是自包含的，不依赖本仓库根目录的文件。

## 首次使用

1. 在 [Server酱](https://sct.ftqq.com/) 登录，绑定自己的微信接收通道并取得 SendKey。
2. 准备本人 Amazon 应用的 **LWA Client ID、Client Secret、Refresh Token**，应用需要 Amazon Fulfillment 角色及店铺授权。Application ID 不能替代 Client ID。
3. 让 Codex 启动技能的本机配置页，选择 NA / EU / FE 区域，在页面填写上述3项凭证和 SendKey。不要把真实密钥粘贴进聊天或 GitHub。
4. Codex 先读取真实货件生成预览，再发送一次微信测试；确认手机收到后，建立每日任务。

**安装 Skill 不会自动创建排程。** 定时任务需在 Codex 桌面应用中实际建立并启用；运行时电脑需开机、联网，Codex 需保持运行。消息在读取和计算完成后发送，不能保证手机恰好在09:00收到。

## 提醒规则

| 项目 | 规则 |
| --- | --- |
| 范围 | 近3个月创建的入库计划，按 Amazon `createdAt` 计算 |
| 临期提醒 | 距最晚可编辑时间0–48小时，包含边界 |
| 已过截止 | 仍未完成的货件也列出 |
| 排除 | 已到仓、接收中、关闭、取消等状态，以及明确识别出的 AWD 计划 |
| 字段缺失 | 单独提示“无法判断”，不推测截止时间 |
| 没有符合项 | 也推送当天检查结果 |
| 推送字段 | 货件编号、仓库、最晚可编辑时间、当前送达窗口 |
| 显示时区 | 北京时间 UTC+8 |
| 修改权限 | 只读 Amazon，不修改送达窗口 |

例如9月28日检查从6月28日北京时间00:00起创建的计划。ACTIVE 与 SHIPPED 分别按创建时间倒序分页，达到起点后停止；不会扫描更早计划的详情。

提醒内容示例（虚构数据）：

```text
FBA送达窗口提醒｜临期1票，已截止0票

货件编号：FBA-DEMO-ONLY
仓库：DEMO
最晚可编辑时间：2026-09-29 11:00
当前送达窗口：2026-10-01 08:00 至 2026-10-08 07:59
```

## 支持与数据保存

- **macOS**：本机配置页，凭证写入钥匙串。
- **Windows**：本机配置页，凭证通过当前用户的 DPAPI 加密保存。
- **Linux**：通过环境变量配置；运行脚本不依赖图形界面。
- 每个用户当前支持一个 Amazon 授权账号和一个区域。测试使用虚构凭证；运行真实 API 需用户自己的有效授权。
- 报告、发送状态和凭证存储独立于 Skill 安装目录，更新技能不会清空每日去重记录。
- 货件消息经 Server酱转发到用户配置的接收通道；通道可用性、额度由该服务决定。接口接受成功不等于手机已送达。

详见 [连接、平台和存储说明](skills/fba-shipment-reminder/references/setup.md) 与 [Codex 定时任务说明](skills/fba-shipment-reminder/references/scheduling.md)。

## 手动运行与维护

在本仓库根目录执行，或让 Codex 使用已安装技能的绝对路径执行：

```sh
python3 skills/fba-shipment-reminder/scripts/configure.py setup
python3 skills/fba-shipment-reminder/scripts/configure.py status
python3 skills/fba-shipment-reminder/scripts/shipment_reminder.py preview
python3 skills/fba-shipment-reminder/scripts/shipment_reminder.py send-test
python3 skills/fba-shipment-reminder/scripts/configure.py schedule-info
```

Windows 可将 `python3` 换成 `py -3`。每日任务入口是 `shipment_reminder.py scheduled`，自行检查北京时间9点门槛，并使用本机发送记录去重。

发送超时或结果不明确时不自动重试，不要删除发送记录后盲目重发。先查看手机与 Server酱控制台，再决定后续动作。

执行测试：

```sh
python3 -m unittest discover -s tests -v
```

测试不访问真实 Amazon 账号，也不发送真实微信。CI 覆盖 macOS、Windows、Linux；Windows 的 DPAPI 测试只在 Windows 上运行。推送、分页、截止边界与故障场景使用模拟接口测试。

## 开源与参考

采用 [MIT 许可证](LICENSE)。本项目为独立工具，与 Amazon、OpenAI、Server酱无隶属关系。提交问题时请移除密钥、账号和真实货件信息。

- [OpenAI：技能安装与使用](https://learn.chatgpt.com/docs/build-skills)
- [OpenAI：定时任务](https://learn.chatgpt.com/docs/automations)
- [Amazon：SP-API 连接](https://developer-docs.amazon/sp-api/docs/connecting-to-the-selling-partner-api)
- [Amazon：入库计划](https://developer-docs.amazon/sp-api/reference/listinboundplans)
- [Amazon：货件详情](https://developer-docs.amazon/sp-api/reference/getshipment)
- [Server酱：Python 接入](https://sct.ftqq.com/docs/integrations/python/)
