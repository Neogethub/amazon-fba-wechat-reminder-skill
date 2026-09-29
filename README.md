# FBA 货件微信提醒 · Codex Skill

把 Amazon FBA 送达窗口检查装进自己的 Codex。首次配置店铺凭证和微信通道后，每天北京时间上午9点检查近3个月的未完成货件，通过 Server酱推送需要处理的清单。

> [!IMPORTANT]
> **第一次使用？请先申请 Amazon SP-API，取得自己的店铺凭证。**
>
> **👉 [点击查看：SP-API 申请教程](#sp-api-申请教程)** — 从开发者注册、权限选择，到获取 Client ID、Client Secret 和 Refresh Token，按步骤完成。
>
> 已有这三项凭证，可以直接跳到 [首次使用](#首次使用)。

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

## SP-API 申请教程

**适用情况：你是亚马逊卖家，在自己的电脑上使用本 Skill，只读取自己公司的店铺数据。** 按下面的 **Private Developer（私有开发者）→ 私有卖家应用 → 自授权** 流程操作。每位客户使用自己的应用和凭证。

**流程：准备主账号 → 注册开发者并等待审核 → 创建应用 → 获取 LWA 凭证 → 自授权取得 Token → 本机配置。**

### 第 1 步：准备卖家主账号

需要 **专业销售账户（Professional selling account）**，由店铺 **主账号（Primary User）** 完成注册和自授权。提前准备企业联系信息、应用用途，以及真实的数据存储和安全措施说明。个人销售计划（Individual）目前不符合私有卖家应用的开发条件。[官方注册要求](https://developer-docs.amazon/sp-api/docs/sp-api-registration-overview)

### 第 2 步：注册私有开发者，申请货件访问权限

1. 登录自己站点的 **Seller Central（卖家平台）**，进入 **Apps and Services → Develop Apps（应用和服务 → 开发应用）**。
2. 如果账号已经迁移到 **[Solution Provider Portal（SPP）](https://solutionproviderportal.amazon.com/)**，从 **Settings → Developer Profile** 查看或填写开发者资料；已有获批资料时，先核对下面的角色权限。
3. 在开发者资料的 **Data Access** 中，选择 **Private Developer**，表示应用供自己公司使用。
4. 在 **Roles** 中申请 **Amazon Fulfillment**。本 Skill 使用它读取 FBA 入库计划和货件；单独使用本提醒功能不需要申请 Pricing、Product Listing 或 Brand Analytics。
5. 如实填写联系方式、**Use Cases（用途）** 和 **Security Controls（安全措施）**，阅读相关协议后提交，并按亚马逊的邮件或 Case 通知补充资料。

描述用途时，可以围绕“读取本公司 FBA 入库货件状态、送达窗口及可编辑截止时间，计算剩余时长，通过本公司配置的 Server酱微信通道提醒相关人员”展开。请按实际部署情况，用自己的话说明数据流向和保护措施；不要照抄不符合实际情况的安全声明。

**提交申请不等于已获批。** 等待开发者资料及所需角色通过审核，再继续配置应用；审核结果和时间以亚马逊通知为准。[私有开发者申请指南](https://developer-docs.amazon/sp-api/docs/register-as-a-private-developer) · [Fulfillment Inbound API 所需角色](https://developer-docs.amazon/sp-api/docs/fulfillment-inbound-api)

### 第 3 步：创建自己的 SP-API 应用

在 SPP 顶部选择 **Develop Apps**，进入应用列表，点击 **Add new app client**。按本 Skill 的用途填写：

| 页面字段 | 本项目如何填写 |
| --- | --- |
| App name | 自定义名称，例如 `FBA Shipment Reminder` |
| API Type | 选择 **SP API** |
| Business entities supported | 勾选 **Sellers** |
| Roles | 勾选 **Amazon Fulfillment**；开发者资料获批后，应用中也要选中该角色 |
| 是否向其他开发者的应用委托 PII 访问权限 | 本 Skill 不使用此功能；若出现该问题，选择 **No** |

保存应用。**私有应用可以在 Draft（草稿）状态下自授权，无需为了自己使用而上架应用商店。** [注册应用指南](https://developer-docs.amazon/sp-api/docs/registering-your-application) · [私有应用自授权说明](https://developer-docs.amazon/sp-api/docs/self-authorization)

### 第 4 步：取得 LWA Client ID 和 Client Secret

回到 **Develop Apps** 应用列表，找到刚创建的应用，点击 **LWA credentials** 下的 **View**；如果界面先显示 **Edit app**，按页面入口进入后查看 LWA credentials。

保存其中的 **Client ID** 和 **Client Secret**，稍后直接填入本机配置页。[查看 LWA 凭证的官方说明](https://developer-docs.amazon/sp-api/docs/viewing-your-application-information-and-credentials)

> [!WARNING]
> **Application ID 不是 LWA Client ID。**
> 如果页面只有 Application ID 和 Refresh Token，说明你正在查看授权结果；请回到应用列表，找到 **LWA credentials → View** 获取另外两项。

### 第 5 步：为自己的店铺授权，生成 Refresh Token

1. 打开该应用的授权入口，找到 **Authorize application / Manage Authorizations** 页面；不同版本的按钮位置可能不同。
2. 如果 SPP 提供 Seller Central 登录链接，通过该链接用**店铺主账号**登录。
3. 找到需要连接的店铺账号，点击 **Authorize app**。
4. 保存页面生成的 **Refresh Token**。它必须与第 4 步的 Client ID、Client Secret 属于同一个应用，并对应你要查询的店铺账号。

这里需要的是 **Refresh Token**；短期 Access Token 由脚本自动换取，不需要客户手工生成或定时填写。[官方自授权与 Token 获取步骤](https://developer-docs.amazon/sp-api/docs/self-authorization)

### 第 6 步：把三项凭证填进本机配置页

核对自己已经准备齐以下内容：

| 凭证 | 从哪里获取 |
| --- | --- |
| **LWA Client ID** | 同一应用的 **LWA credentials → View** |
| **LWA Client Secret** | 同上，与 Client ID 成对使用 |
| **Refresh Token** | 自己店铺的 **Authorize app** 授权结果 |

接着按下方 [首次使用](#首次使用) 绑定微信、取得 Server酱 SendKey，让 Codex 打开本机配置页。选择与店铺对应的区域（美国站选 **NA 北美**），保存后先测试 API 和微信，再启用每天的提醒。

**三项亚马逊凭证和 SendKey 只在自己的本机配置页填写，不要放进聊天、截图、GitHub Issue 或公开仓库。**

<details>
<summary><strong>申请或连接时卡住了？查看常见问题</strong></summary>

- **找不到 Amazon Fulfillment：** 先在 Developer Profile 中申请该角色，获批后再回应用设置勾选。
- **已有 SPP 账号，又出现引导页：** 先进入已有账号的主页，查看 Developer Profile 和 Develop Apps，避免重复创建资料。
- **只看到 Refresh Token 和 Application ID：** 回到应用列表的 LWA credentials → View，取得 Client ID 和 Client Secret。
- **应用显示 Draft：** 私有应用支持在草稿状态下自授权，继续完成第 5 步即可。
- **API 返回 403：** 检查区域、店铺自授权，以及开发者资料和应用是否都具有 Amazon Fulfillment 角色；不要只凭已生成 Token 判断权限完整。
- **提示 Client ID / Secret 或 Token 无效：** 核对三项是否来自同一应用，且授权仍有效。换应用时需要重新配置对应凭证。

</details>

教程依据亚马逊官方文档于 **2026-09-28** 核对；入口名称可能因站点、语言和 SPP 迁移状态而不同，以当前页面和官方指南为准。

## 首次使用

1. 在 [Server酱](https://sct.ftqq.com/) 登录，绑定自己的微信接收通道并取得 SendKey。
2. 按上方 **[SP-API 申请教程](#sp-api-申请教程)** 准备本人应用的 **LWA Client ID、Client Secret、Refresh Token**，应用需要 Amazon Fulfillment 角色及店铺授权。Application ID 不能替代 Client ID。
3. 让 Codex 启动技能的本机配置页，选择 NA / EU / FE 区域，在页面填写上述3项凭证和 SendKey。不要把真实密钥粘贴进聊天或 GitHub。
4. Codex 先读取真实货件生成预览，再发送一次微信测试；确认手机收到后，建立每日任务。

**安装 Skill 不会自动创建排程。** 定时任务需在 Codex 桌面应用中实际建立并启用；运行时电脑需开机、联网，Codex 需保持运行。消息在读取和计算完成后发送，不能保证手机恰好在09:00收到。

## 已安装用户：更新定时配置

> [!IMPORTANT]
> **v0.1.1 修正了跨时区排程指引。电脑使用美国等非北京时间时区的用户，请同时检查已有定时任务。**
>
> 北京时间09:00对应 **UTC 01:00**。更新Skill不会自动修改已经创建的任务；必须让Codex回读任务实际的“下一次执行时间”，确认换算到北京时间后落在预期日期的9点附近。

在自己的Codex中发送：

```text
请将已安装的 fba-shipment-reminder 更新到 Neogethub/amazon-fba-wechat-reminder-skill 的 v0.1.1，保留我的凭证、数据目录和发送记录。按新版定时说明检查并修正现有任务，仍然每天北京时间09:00运行，不要创建重复任务。请回读并告诉我实际保存的下一次执行日期和北京时间；无法读取时请说明尚未核验。
```

`schedule-info` 输出的是**计算出的目标时间**，不是客户端已经保存的实际排程。客户端可能有少量错峰延迟，查询货件和微信投递也需要时间。保持电脑唤醒、联网和Codex运行；首次自动触发仍需实际运行验证。[详细排程与核验步骤](skills/fba-shipment-reminder/references/scheduling.md)

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
