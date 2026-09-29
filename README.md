# Joybuy 荷兰站 → 微信 / 邮箱优惠提醒

这是可部署的第一版代码，不是已经开通的云端服务。部署需要你的 GitHub 账户，以及 Server酱 Turbo 微信通道或支持 SMTP 登录的邮件服务；不需要连接 ChatGPT 的 GitHub 插件。

## 改用邮箱

邮箱与微信二选一。将 `config.json` 中 `notification_channel` 改为 `email`，无需注册 Server酱。先按下方步骤创建仓库、上传代码，再在仓库 Settings → Secrets and variables → Actions 配置以下 Secrets：

| Secret 名称 | 填写内容 |
| --- | --- |
| `SMTP_HOST` | 邮件服务商提供的 SMTP 服务器地址 |
| `SMTP_PORT` | 465（SSL）或 587（STARTTLS），只支持加密连接 |
| `SMTP_USER` | SMTP 登录用户名，通常为完整邮箱地址 |
| `SMTP_PASSWORD` | 服务商要求的 SMTP 密码或专用授权码 |
| `MAIL_FROM` | 服务商允许使用的发件邮箱 |
| `MAIL_TO` | 你本人接收提醒的一个邮箱地址 |

无需设置 `SERVERCHAN_SENDKEY`。不要把密码或授权码发到聊天中。是否支持密码式 SMTP、如何开启以及是否需要专用授权码，以服务商当前说明为准。本版本未实现 OAuth2 邮箱登录；若账户只允许 OAuth2，需要额外适配或使用提供 SMTP 凭据的发信服务。

邮件发件箱和接收箱可以不同。默认仍限制为每天 4 封合并通知，可按需要修改 `max_pushes_per_day`，并遵守邮件服务额度。SMTP 接受邮件不等同于最终送达，应在收件箱或垃圾邮件箱验证。邮件正文为纯文本，包括可复制的活动链接。

在 Actions → **Joybuy Deal Monitor** 手动运行：先保持 `dry_run` 预览，再取消勾选验证真实发送。实际邮箱发送尚未测试，需要你配置凭据后验证。下方步骤中的微信绑定部分可跳过。

## 默认行为

- GitHub Actions 每小时第 17 分钟触发，平台繁忙时可能延迟或跳过。
- 读取公开活动页，解析商品价格、参考价、满减文案和优惠码；从已读取页面发现更多活动链接，每次最多检查 6 页。
- 商品相对网站参考价优惠至少 50% 才提醒。参考价经常是建议零售价，**不等同于真实历史降价幅度**。
- 首次发现符合条件的商品会提醒；同一商品只有价格进一步降低才再次提醒。优惠券按页面和文案去重。
- 每条最多 12 个优惠，每天最多 4 次推送（按中国日期计算，为 Server酱免费额度留余量）。超过限额的优惠会在后续重新抓取时再判断，不保证限时活动都能及时通知。
- 抓取失败会记录在运行结果，且每天最多发一次错误提示，错误提示也计入 4 次限额。
- 无第三方 Python 依赖、无需 AI API Key、无需保持电脑开机。

## 已验证与尚未验证

2026-09-29 从 Joy Days 公开活动页成功下载 HTML 并解析其中的 496 条商品记录（含重复项）。提取去重后的商品/券线索 178 条，其中 24 条符合默认提醒规则。`sample-report.md` 是本次解析预览，不是当前有效价格承诺。

已通过价格计算、库存排除、重复提醒、进一步降价、403/空页面识别及脚本文案排除测试。尚未在你的 GitHub 账户运行，也没有发送真实微信消息；需要部署后验证云端访问和微信送达。

完整抓取预览：尝试 6 页，成功 2 页，另 4 页未能读取或解析；成功页面共含 991 条商品记录（有重复），默认筛选得到 51 条商品/券线索。`sample-report.md` 包含前 12 条和失败页面清单。发现页面结构不支持时，预览与正式运行都会报告失败状态，已成功抓取部分仍会保留。

## 部署：GitHub Actions

1. 在 https://github.com/new 创建一个专用仓库，建议选择 Private，名称可用 `joybuy-monitor`。
2. 解压压缩包，把项目文件放在仓库根目录。务必包含 `.github/workflows/monitor.yml`；不要只上传 ZIP，也不要多套一层 `joybuy-monitor` 文件夹。可使用 GitHub Desktop 上传整个文件夹，或本机 Git：

   ```bash
   cd joybuy-monitor
   git init
   git add .
   git commit -m "Add Joybuy monitor"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/joybuy-monitor.git
   git push -u origin main
   ```

3. 登录 https://sct.ftqq.com/ ，选择 **Turbo 的微信服务号通道**，按指引绑定微信并获取以 `SCT` 开头的 SendKey。本版本没有配置 Server酱³ App 通道。
4. 在仓库 **Settings → Secrets and variables → Actions → New repository secret** 新建：
   - Name：`SERVERCHAN_SENDKEY`
   - Secret：你的 SendKey

   密钥只填在 Secret 中，不要写进代码、截图或聊天消息。
5. 确认仓库允许 GitHub Actions 运行，并允许该工作流写入仓库。工作流写权限仅用于保存 `state.json`（去重记录与每日发送计数）。默认分支若禁止直接提交，状态保存会失败，应使用专用仓库或调整该仓库规则。
6. 在 **Actions → Joybuy Deal Monitor → Run workflow** 保持 `dry_run` 勾选运行一次。查看日志与下载的 `scan-report`，确认有成功读取的页面。预览不会发送消息，也不会改变去重状态。
7. 再次手动运行，取消 `dry_run`，验证第一条微信。Server酱接口成功只代表接受发送，实际送达要在手机上确认。
8. 工作流位于默认分支后，定时触发自动生效。停止时在 Actions 中选择 Disable workflow。

GitHub 云端计算费用取决于账户套餐、仓库类型和每月实际耗时，不承诺免费。查看 Settings → Billing，避免未经了解启用付费超额。Server酱当前文档描述免费每天 5 条；本项目独占的每日上限为 4，其他使用同一密钥的程序也会占用额度。用官方控制台核对实际额度。

## 调整规则

编辑 `config.json`：

| 配置 | 含义 |
| --- | --- |
| `seed_urls` | 起始页面；把新活动页链接加入这里可扩大覆盖 |
| `min_discount_percent` | 50 表示便宜至少一半，即五折及以下 |
| `max_pages` | 每轮最多抓取页面数 |
| `max_deals_per_message` | 每条合并的优惠条数 |
| `max_pushes_per_day` | 每日通知上限，默认 4 |

检查时间可修改工作流中的 cron。默认每小时一次；本项目没有实时推送保证。

本地预览：`python monitor.py --dry-run`；运行测试：`python -m unittest -v`。

## 已知覆盖限制

- **并非全站商品监控**。首版只覆盖起始页和有限数量的活动链接；首页被拦截时，新活动发现能力会下降，需要补充新的活动链接。
- Joybuy 可能拒绝云端 IP、返回 403 或改变数据结构。程序不会绕过验证码或访问限制，也不会把未能解析的页面当成“零优惠”。某页失败会在报告中显示，其余页面仍尝试读取。
- 页面的内嵌数据可能与登录后或结账时价格不同；不读取用户账户、地区地址、新客身份或会员权益。仅在数据明确标记不可售/无库存时排除商品，不能保证实际可配送。
- 活动页可能过期但仍能打开。满减和优惠码是“待核实的活动线索”，不能确认有效期、适用商品或可叠加时不会编造最终到手价。首版未实现通用活动有效期验证，也未实现优惠券叠加计算。
- 图片中的满减、JavaScript 后续请求的商品、未支持的文案格式可能漏检。商品提供来源活动页与商品编号，未伪造商品详情链接。
- 推送状态保存在仓库中。如果推送成功后状态提交失败，下一次可能重复发送；如发送超时，送达状态未知，后续也可能重复。状态文件被删除会重置去重和额度计数。
- 公开仓库长期没有活动时，GitHub 的定时工作流可能被停用。定期确认最近运行时间；GitHub 的失败通知可用于排查。

## 官方参考

- Server酱通道：https://sct.ftqq.com/docs/getting-started/channels/
- Server酱 Python/API：https://sct.ftqq.com/docs/integrations/python/
- GitHub 定时任务：https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

版本：0.1，2026-09-29。
