# 信跃：金融素养与模拟信贷研究站点

这是“信跃”大学生创新训练项目的数据采集网站。当前完成**阶段二：29 题量表接入与提交计分**：

知情同意 → 创建参与会话 → 填写模拟申请 → 完成 29 题 1—7 分量表 → 自动保存草稿 →
服务端校验并计分 → 表单、原始答案和提交状态在同一事务中保存 → 返回数据库回执 →
管理员查看原始答案与 ATR、SN、PBC、LRI 四个分量表结果。

> **部署状态：尚未公网部署。**
> 目前只有本机开发地址 `http://127.0.0.1:5000`，不能转发给同学作为正式采集链接。
> 本机与无头浏览器验证产生的 `TEST-` 记录不是正式样本。固定公网链接、持久 PostgreSQL
> 和真实手机/微信验收仍属于后续部署阶段。

## 阶段二已经实现

- 将固定 29 题量表接入模拟申请流程，保持题项原文和顺序，移动端分三步填写：
  申请信息 → 29 题看法 → 检查提交。
- 每题明确展示 1—7 分含义（非常不同意到非常同意），同时显示整表图例。
- 量表答案与申请信息关联到同一个参与会话；草稿同时保存表单和 29 题答案。
- 自动保存之后可返回上一步修改；刷新当前标签页时从 `sessionStorage` 恢复表单、答案、
  当前步骤、客户端序号和提交键。写令牌只存在当前标签页，不写入长期本地存储。
- 服务端对最终提交做严格校验：必须完成必填申请信息、29 题全部作答（1—7 整数）、
  最终确认和合法提交键；未知字段与越界值会被拒绝。
- 最终提交把 `Submission`、29 条 `ScaleAnswer`、会话提交状态、回执和同事务的行为摘要
  一起提交；数据库写入失败会整体回滚，不返回成功页，不留下部分提交。
- 原始答案单独保存，不因计分而被覆盖。7 道反向题（7、8、15、16、23、24、29）
  按 `8 - 原始分` 转换。
- 分别计算并保存 ATR、SN、PBC、LRI 的总分、均分、有效题数和应有题数。
  缺失值保持 `null`，不计为 0；阶段二最终提交必须 29 题完整。
- 计分结果只在管理员详情页展示；参与者在提交前后都看不到 ATR、SN、PBC、LRI 分数，
  也不会看到个人信用等级、违约概率或授信结论。
- 管理员详情页显示 29 题原文、原始分、计分后分数、正/反向标记和四个分量表结果；
  草稿只展示原始答案，不在服务端补算分量表分数。
- 阶段一已有提交记录保持原样：新增字段允许为空，历史记录不补造答案、分数或计分版本。
- 旧版本会话不能写入当前研究协议：实验版本或量表版本不一致时返回
  `409 protocol_version_mismatch`，避免阶段一进行中的会话混入阶段二数据。
- 保留阶段一能力：服务器回执、失败重试、同一提交键幂等、重复提交返回原回执、
  已提交会话拒绝迟到草稿和行为批次、正式/测试记录分开标记。

## 已验证内容

验证日期：2026-10-22。以下均为本机实际执行结果，不代表公网部署或正式样本。

### 自动化测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

实际结果：**48 passed**。覆盖：

- 29 题题库固定、题项顺序、1—7 标签；
- 正反向计分、缺失值保持 `null`、全局题号、分量表总分/均分/有效题数；
- 草稿保存量表答案、返回修改、旧客户端序号拒绝、33 单元进度；
- 最终提交漏答返回 `400 incomplete_scale` 且不写入任何提交或答案；
- 非法分值、未知题号拒绝；
- 完整提交写入 29 条原始答案和不可变计分快照；
- 反向题在数据库中的原始分、计分后分数和标记；
- 重复提交返回同一回执且不重复写 29 条答案；
- 模拟数据库提交失败后，提交、答案、会话状态和回执全部回滚；
- 旧协议会话不能写入阶段二；
- 管理员详情显示原始答案与四个分量表结果；阶段一历史记录不回填；
- 全新数据库迁移、阶段一旧库升级后历史记录保留；
- 生产环境失败关闭、管理员鉴权、CSRF、重启持久化等阶段一回归项。

测试使用临时 SQLite 数据库，不读取也不修改 `instance/` 中的开发数据。

### 浏览器流程验证

使用 Playwright + 本机 Chrome，移动视口 390×844（并检查 360、320 宽度下无横向页面滚动），
实际完成了：

1. 知情同意、创建 `TEST-` 会话；
2. 填完申请信息，验证漏填必填项会被阻止；
3. 只回答前 10 题时点击继续，验证提示“还有 19 题未作答”、19 题高亮且不能进入复核页；
4. 完成 29 题后等待草稿保存，刷新页面，确认表单、29 个选项和第二步状态全部恢复；
5. 返回申请页修改贷款金额，再返回量表修改一题，确认答案不丢失；
6. 复核页确认不显示任何 ATR、SN、PBC、LRI 或总分；
7. 人为让第一次最终提交请求断网，确认不出现成功页、答案保留，再用同一提交键重试成功；
8. 成功后再次发送同一最终请求，返回同一回执，数据库仍只有 29 条量表答案；
9. 管理员登录后看到 4 个分量表卡片、29 题逐题表格和 7 个反向题标记；
10. 打开从阶段一数据库复制并迁移得到的旧记录，确认显示“阶段一历史记录，未采集量表答案”，
    页面没有补造分数或答案。

本次验证的测试记录为 `TEST-E11CCC3494F6`，回执为
`dfd775c6-99c0-48f2-860e-a3e87a399137`；四个分量表总分为 ATR 36、SN 32、PBC 29、LRI 22。
这是验证数据，**不是正式样本**。

截图位于 `verification_artifacts/stage2/`：

- `01_mobile_consent.png`
- `02_mobile_survey_mobile.png`
- `03_mobile_missing_answers_blocked.png`
- `04_mobile_refresh_restored.png`
- `05_mobile_review_no_scores.png`
- `06_mobile_submit_failure_preserved.png`
- `07_mobile_success_receipt.png`
- `08_admin_dashboard.png`
- `09_admin_detail_scores_and_answers.png`
- `10_admin_stage1_history_no_backfill.png`

### 迁移验证

- 全新数据库执行 `flask --app app db upgrade` 成功，版本为 `7a1d9f4c2b10`。
- 另将一个阶段一 SQLite 副本升级到同一版本，原 `TEST-5903D398385E` 提交记录、
  表单载荷、回执和内容哈希均保留；新增的 `scale_version`、`scoring_version`、
  `scale_scores` 保持 `NULL`，`scale_answers` 仍为 0 条。
- 原始阶段一数据库 `instance/stage1-live-test.sqlite3` 未被本阶段修改；
  浏览器验证使用的是副本 `verification_artifacts/stage2/stage2-verification.sqlite3`。

**尚未完成真实手机、微信内置浏览器、公网 HTTPS 和 PostgreSQL 实库验收。**

## 本地运行（Windows PowerShell）

在项目根目录执行：

```powershell
Set-Location E:\lzy\Documents\credit_loan

# 已有 .venv 可跳过创建和安装
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt

# 首次配置：复制模板后用编辑器填写，不要提交真实 .env
Copy-Item .env.example .env
notepad .env
```

`.env` 至少需要填写：

1. `SECRET_KEY`：运行
   `python -c "import secrets; print(secrets.token_urlsafe(48))"` 生成。
2. `ADMIN_USERNAME`：自行设置一个不易猜中的管理员用户名。
3. `ADMIN_PASSWORD_HASH`：运行 `python scripts/hash_admin_password.py`，
   把输出的哈希行填入 `.env`。不要把管理员明文密码写进 `.env`。

开发环境可以不设置 `DATABASE_URL`，此时使用 `instance/xinyue-dev.sqlite3`。
首次运行、拉取新版本或迁移变更后执行：

```powershell
# 升级已有数据库前先备份 instance/xinyue-dev.sqlite3
flask --app app db upgrade
python app.py
```

打开：

- 参与者页面：<http://127.0.0.1:5000/>
- 测试会话页面：<http://127.0.0.1:5000/?test=1>（开发环境默认允许）
- 管理员后台：<http://127.0.0.1:5000/admin/login>
- 健康检查：<http://127.0.0.1:5000/health>

本机数据库只适合开发验证。关闭电脑后本机地址和 SQLite 数据不构成公网服务；
正式采集仍需配置持久 PostgreSQL 和公网部署平台，并完成后续阶段验收。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

测试使用临时 SQLite 数据库，覆盖单元、API、后台和迁移路径；浏览器流程由
`verification_artifacts/stage2/verify_stage2_browser.py` 单独执行，不属于 pytest。
该脚本要求本机 Chrome、Playwright 和一个已配置管理员凭据的本地验证服务器；
Playwright 只用于本机验收，不是 Web 运行依赖。

## 数据模型

| 表 | 用途 |
| --- | --- |
| `participant_sessions` | 会话、同意与版本、状态、进度、回执号 |
| `form_drafts` | 每会话最新草稿；`payload` 存表单，`scale_payload` 存 29 题草稿 |
| `submissions` | 最终不可变表单快照、提交键、回执号、内容哈希和计分快照 |
| `scale_answers` | 29 题原始分、计分后分数、反向标记，唯一约束为会话 + 题号 |
| `behavior_batches` | 增量行为事件批次及双重唯一约束 |
| `behavior_summaries` | 服务端统计的已接收批次/事件数，不宣称采集完整 |
| `alembic_version` | 数据库迁移版本 |

计分规则：

- 题项固定为 29 题，版本 `repayment-29-v1`；分值为 1—7。
- 反向题：7、8、15、16、23、24、29，计分后为 `8 - raw`。
- ATR：1—8 题；SN：9—16 题；PBC：17—24 题；LRI：25—29 题。
- 每个分量表分别保存总分、均分、有效题数、应有题数和缺失题号。
- 缺失值遵守 `null`，不按 0 分处理；阶段二最终提交要求全部 29 题。
- `all_29_compatibility` 只是兼容性汇总，不解释为“真实还款意愿”。
- 系统不生成个人违约概率、信用等级或授信结果。

阶段一会话的 `Submission.scale_version`、`scoring_version` 和 `scale_scores` 为 `NULL`。
这表示历史记录确实没有量表数据，不是缺失待补；后台不会自动补算。

## 安全与隐私边界

- 不采集姓名、身份证、银行卡、通讯录、剪贴板或键入正文。
- 公开参与编号不是写权限；写入需要同一会话的 Bearer 写令牌，数据库只保存其 SHA-256 哈希。
- 写令牌只保存在当前标签页的 `sessionStorage`，成功提交后清除。
- 管理员密码只以 Werkzeug 哈希形式配置；正式环境缺少数据库、密钥或管理员配置时拒绝启动。
- 正式环境要求 `DATABASE_URL` 为 PostgreSQL，`SECRET_KEY` 至少 32 字符，
  Cookie 使用 Secure/HttpOnly/SameSite=Lax。
- 响应带 CSP、`X-Frame-Options: DENY`、`Referrer-Policy: no-referrer` 等安全头。
- 失败写入不会返回伪造回执；数据库异常返回 503，并保留页面答案供重试。
- 参与者页面不展示量表得分；管理员页面的研究分数也不构成个人信用评价。

## 当前未完成

| 阶段 | 内容 |
| --- | --- |
| 阶段三 | 前端行为采集、分批上传、暂停/隐藏计时与管理员行为摘要扩展 |
| 阶段四 | 后台轮询刷新、CSV 导出、正式/测试筛选与数据完整性检查 |
| 阶段五 | PostgreSQL 实库迁移、Render/同类平台公网部署、真实手机浏览器与微信内验收 |
| 阶段六 | 版本固定、研究文档、数据字典和交付包整理 |
| 阶段七（可选） | RRT 群体估计模块；只做群体估计，不做个人推断 |

阶段二仍有的验证边界：

- 浏览器验证使用本机无头 Chrome 的移动视口，不是实体手机，也不是微信内置浏览器。
- 未进行公网 HTTPS、真实网络切换和 PostgreSQL 实库测试。
- 未生成或分析正式样本；所有 `TEST-` 记录都不能计入研究样本。
- 后台 CSV 导出、自动轮询和行为事件采集仍未实现。
- `run_public.py` 只是本机临时隧道工具，不是正式部署方案。
- 根目录 `render.yaml` 故意暂不定义任何服务，避免把旧原型蓝图误当正式部署。

## 仓库文件说明

- 当前 Web 运行时：`app.py`、`config.py`、`models.py`、`extensions.py`、`security.py`、
  `validation.py`、`participant_routes.py`、`admin_routes.py`、`survey.py`。
- 当前页面与静态资源：`templates/base.html`、`templates/participant.html`、
  `templates/admin_*.html`、`static/participant.js`、`static/styles.css`。
- 阶段二迁移：`migrations/versions/7a1d9f4c2b10_stage2_scale_drafts_and_scores.py`。
- Web 依赖：`requirements-web.txt`；Render 额外使用 `requirements-render.txt`。
  根目录 `requirements.txt` 是早期机器学习分析依赖，不是 Web 服务启动依赖。
- 旧原型页面和 `behavior.js` 已移到 `legacy/stage0/`，不再被当前应用引用。
- `train.csv`、`test.csv`、`behavior_logs.json`、`data/behavior_logs.csv` 是历史研究资料，
  不参与当前运行时，也不应进入正式部署包。

## 停止本地服务

在启动 `python app.py` 的终端按 `Ctrl+C`。本地开发数据库位于
`instance/xinyue-dev.sqlite3`；不要把它上传到公开仓库或作为正式研究数据的唯一副本。
