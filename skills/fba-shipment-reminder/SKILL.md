---
name: fba-shipment-reminder
description: Configure and run Amazon FBA delivery-window deadline reminders through SP-API and ServerChan WeChat notifications. Use for connecting a seller's credentials, checking recent shipments, testing WeChat delivery, or scheduling daily deadline reminders in Codex.
---

# FBA 货件微信提醒

为当前用户读取自己的 Amazon FBA 货件并发送微信提醒。使用随技能安装的 Python 脚本执行筛选，不自行重新实现截止时间计算。仅支持单账号、单区域；不会修改亚马逊货件。

## 定位与运行

以本文件所在目录为技能目录，使用其中 `scripts/` 的绝对路径。先找到实际可运行的 Python 3.9+（macOS/Linux 通常为 `python3`，Windows 可为 `py -3`），并取得其 `sys.executable`。脚本仅依赖 Python 标准库。

按用户任务选用命令；表中的路径在运行前替换为实际绝对路径：

| 任务 | 命令 |
| --- | --- |
| 检查凭证格式与数据目录，不联网 | `python scripts/configure.py status` |
| 打开本机配置页 | `python scripts/configure.py setup` |
| 仅测试微信通道 | `python scripts/configure.py test-wechat` |
| 读取真实货件并生成预览，不推送 | `python scripts/shipment_reminder.py preview` |
| 推送最近15分钟内的预览，同一快照只发一次 | `python scripts/shipment_reminder.py send-test` |
| 每日运行，上午9点前跳过，每天成功后去重 | `python scripts/shipment_reminder.py scheduled` |
| 获取实际命令和北京时间/UTC目标排程，不查询已保存任务 | `python scripts/configure.py schedule-info` |

## 首次配置

1. 阅读 [连接说明](references/setup.md)。确认用户的 Amazon SP-API 应用已获得本人店铺授权及 Amazon Fulfillment 角色，Server酱已绑定其微信。
2. 运行 `configure.py status`。配置有效时复用，不重复索取凭证；该命令只验证格式，不代表在线授权成功。
3. 未配置时，在 macOS/Windows 运行 `configure.py setup`，将其打印的随机本机网址交给用户或在可用的浏览器工具中打开。让用户亲自在页面输入凭证；不要把密钥读入对话、截图、日志或命令参数。保留服务进程到保存完成或超时。Linux 使用连接说明中的环境变量方式。
4. 用户要求配置提醒或测试时，运行 `preview` 验证真实读取；检查退出状态和快照完整性，不能将失败解释成“没有临期货件”。随后用 `send-test` 向用户已配置的本人微信发送一次结果，确认手机收件。若用户只要求安装技能，先完成安装，不执行推送。
5. 用户要求每天提醒时，按 [定时任务说明](references/scheduling.md) 创建或更新其 Codex 桌面定时任务。北京时间09:00对应UTC 01:00；先使用客户端支持的明确时区排程，再回读已保存任务的实际下一次触发时间，换算到北京时间核对。`schedule-info` 只计算目标，不能证明任务已启用或排程正确。升级技能时也应核对已有任务，不重复创建。

## 固定业务口径

- 默认检查近3个月创建的入库计划，按 `inboundPlan.createdAt`、北京时间对应日期零点计算，包含起点，月末按目标月最后一天处理。
- 分别查询 ACTIVE、SHIPPED，按创建时间倒序分页，抵达时间边界停止；读取范围内全部计划的未完成货件。不能省略状态、只取第一页或扩大为全部历史。
- 用 `selectedDeliveryWindow.editableUntil` 判断剩余时间：`0–48小时`（含边界）以及已过截止的未完成货件均列出。缺失截止时间单独标记无法判断，不用送达窗口起点猜测。
- 排除已送达、签到、接收中、关闭、取消、删除、放弃状态；只有明确“不支持 AWD 入库计划”的业务错误可作为 AWD 排除，其余错误应报告失败。
- 每票包含货件编号、仓库、最晚可编辑时间、当前送达窗口，均显示北京时间。无匹配货件也发送检查结果。

## 检查结果与异常

脚本将报告、快照、发送记录写入当前用户的数据目录，独立于技能安装目录；用 `status` 查路径。只在需要核对时读取报告，避免展示无关业务数据。

检查命令退出码：0 表示该命令正常完成或明确跳过；1 为失败；2 为另一实例占用执行锁。不能把“跳过”当成本次扫描成功。正常定时完成无需追加例行聊天消息，异常或需要用户操作时再报告。

Server酱接口接受不等于手机已送达。发送记录为 `sending` 或 `delivery_unconfirmed` 时停止自动重发，先核对微信及 Server酱日志；不要删除记录来绕过去重。只读 API 可以由脚本有限重试。不要自动改写货件窗口、撤销凭证或修改现有推送记录。

配置和凭证细节见 [连接说明](references/setup.md)，定时任务和时区处理见 [排程说明](references/scheduling.md)。
