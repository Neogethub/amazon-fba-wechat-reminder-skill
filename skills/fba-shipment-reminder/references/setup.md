# 连接与本机存储

## 客户准备

- 已登录且能够使用技能、工具和定时任务的 Codex 桌面应用；Python 3.9+。
- Amazon SP-API 应用具有 Amazon Fulfillment 角色，已获得该客户本人店铺授权。Skill 不会代替客户完成 Amazon 开发者注册或权限审核。
- 同一应用的 LWA Client ID、LWA Client Secret、Refresh Token。Application ID 不是 Client ID。
- 在 [Server酱](https://sct.ftqq.com/) 登录、配置微信接收通道，并取得 SendKey。通道能力及额度由该服务决定。
- 选择与店铺一致的区域：NA 北美、EU 欧洲等、FE 远东；当前每次配置一个授权账号与一个区域。

## macOS / Windows 配置页

`configure.py setup` 仅监听 `127.0.0.1` 的随机端口，打印一次性配置地址，一小时后关闭。页面校验 Host、Origin、CSRF token，不记录请求正文。用户直接填写四项凭证；保存成功后不会自动调用 Amazon 或推送消息。

- macOS：全部凭证保存在钥匙串，服务名 `io.github.neogethub.fba-shipment-reminder`。首次运行可能需要允许 Python 访问该项目。
- Windows：用当前 Windows 用户的 DPAPI 加密后保存为 `credentials.dpapi`；换电脑或 Windows 用户需要重新配置。
- 保存后先 `status`，再 `shipment_reminder.py preview`，最后按已授权的测试请求运行 `send-test`。只测试微信时用 `configure.py test-wechat`。

脚本只需 Python 标准库；北京时间采用固定 UTC+8，不依赖 Windows 是否安装时区数据库。Python 路径含空格时正确引用；PowerShell 调用带引号的路径需要前缀 `&`。

## 数据目录与升级

| 系统 | 默认数据目录 |
| --- | --- |
| macOS | `~/Library/Application Support/FBA Shipment Reminder` |
| Windows | `%LOCALAPPDATA%\FBA Shipment Reminder` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/fba-shipment-reminder` |

报告和发送记录位于目录中的 `.runtime/`；凭证不写入报告。更新技能仅更新安装目录，不删除这些记录。删除去重记录可能导致重复发送。

可用 `FBA_REMINDER_HOME` 指定数据目录；必须为后续每次运行及定时任务保留相同值。该变量不创建第二套 macOS 钥匙串凭证，不能用作多账号隔离。

默认策略位于技能的 `assets/reminder_config.json`。若需要改变检查月份数或是否包括过期货件，可在数据目录创建 `settings.json`：

```json
{"lookback_months": 3, "include_expired": true}
```

48小时阈值、北京时间及每日9点为本版本的固定约定。变更这些约定需同步修改脚本与定时任务，不能只改任务文字。

## Linux / 已有环境变量配置

Linux 支持通过运行环境传入下列值，不提供桌面凭证配置页：

| 变量 | 内容 |
| --- | --- |
| `SP_API_CLIENT_ID` | LWA Client ID |
| `SP_API_CLIENT_SECRET` | LWA Client Secret |
| `SP_API_REFRESH_TOKEN` | Refresh Token |
| `SP_API_REGION` | NA、EU 或 FE，默认 NA |
| `SERVERCHAN_SENDKEY` | 客户本人的 SendKey |

环境变量优先。只配置一部分 Amazon 环境变量会报错，不会回退到另一个本机账号。由用户在其私有运行环境或秘密管理工具中配置，别在公开仓库、对话或 shell 命令参数中填写真实值。程序不会自动加载 `.env` 文件。

## 常见问题

- Client ID / Secret 不匹配：回到同一应用的 LWA credentials 核对，不能拿 Application ID 代替。
- Refresh Token 无效：核对是否属于同一应用，以及店铺授权是否撤销。
- 403：核对区域、店铺授权、Amazon Fulfillment 角色。
- 缺少 editableUntil：保留“无法判断”，提示用户去后台核对；不要自行计算替代。
- 发送状态不确定：先核对手机与 Server酱记录，再决定是否需要一次人工重发；不自动重试。

参考：[Amazon 授权连接](https://developer-docs.amazon/sp-api/docs/connecting-to-the-selling-partner-api)、[入库计划列表](https://developer-docs.amazon/sp-api/reference/listinboundplans)、[货件详情](https://developer-docs.amazon/sp-api/reference/getshipment)、[Server酱接口](https://sct.ftqq.com/docs/integrations/python/)。
