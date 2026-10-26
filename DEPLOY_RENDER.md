# 更新现有Render站点

目标服务：`xinyue-risk-control`，公开地址 <https://xinyue-risk-control.onrender.com>。保持现有服务及域名，不必新建同名服务。

当前状态（2026年10月27日）：固定条款、本人承诺与独立RRT已发布到原网址，运行提交`7aa480c`，部署`dep-dbfoj24s728c738hbjr0`为`live`；数据库升级至`b6d208a134f0`。现有免费PostgreSQL、密钥与后台账号保持不变，到期时间仍为2026年11月25日16:58（北京时间）。

本轮发布前77项测试及新旧协议真实浏览器检查通过。公网新版TEST完成固定条款、承诺、8页29题及独立RRT；受保护导出核对旧回执、原始答案和行为明细保留。群体RRT与个人CSV分开。此项使用部署所有者签名凭证，不冒充密码表单登录或完整PostgreSQL恢复验收。详见`docs/VERIFICATION.md`。

## 发布前

1. 核对现有服务的Settings → Repository和Branch。当前仓库为<https://github.com/lzy080929-hub/xinyue-risk-control>，分支为`codex/original-8page-data-collection`；仓库已存在本轮发布提交。
2. 先保存当前线上已有数据。如果旧服务仍把数据写入应用本地JSON/CSV，重启或重新部署可能丢失这些文件。先通过现有可用导出或托管平台Shell/备份功能取回，不要仅凭本机已有一份日志就认定线上数据也已备份。
3. 新版先使用独立测试数据库或预发布服务验证；不要将测试过程写进正式数据库。
4. 托管平台登录和数据库连接串在已授权的账号内操作，不发送到聊天或源码里。配置与发布结果以本文件顶部和验证记录为准。

需要由维护工具自动操作现有Render服务时，可通过官方Render CLI的`render login`在浏览器完成授权。账号授权由研究者本人确认；工具随后核对服务、备份、数据库和部署配置。管理工具及登录状态放在被忽略的`.tools/`下，绝不打入部署包。未取得账号授权前不能自动修改Render服务。参考[官方CLI登录说明](https://render.com/docs/cli#2-log-in)。

## 环境变量

| 名称 | 设置 |
| --- | --- |
| APP_ENV | production |
| DATABASE_URL | 持久PostgreSQL连接串；同区域Render数据库优先使用内部连接串 |
| SECRET_KEY | 至少32字符随机值；正式服务保持稳定 |
| ADMIN_USERNAME | 研究者自行设置 |
| ADMIN_PASSWORD_HASH | 用本机`scripts/hash_admin_password.py`交互生成，不是明文密码 |
| ALLOW_TEST_MODE | 正式采集为0；预发布测试可临时设置1并明确测试入口 |

不要使用应用临时磁盘上的SQLite作为线上数据库。若使用有到期限制的试用数据库，必须核实期限并在到期前迁移/导出；长期采集应选择满足保留和备份需求的方案。是否购买资源由研究者在平台确认。

## 现有服务设置

- Build Command：`pip install -r requirements-render.txt`
- Start Command：`python scripts/start_production.py`
- Health Check Path：`/health`
- Python版本：仓库根目录`.python-version`指定3.14，与本轮本机验证的次版本一致。若Render服务已有`PYTHON_VERSION`变量，它优先于该文件；发布前核对并统一。旧`runtime.txt`保留供追溯，不作为Render当前版本配置依据。
- 使用单worker、多线程部署；应用内登录限流是单进程实现，多实例需另配共享限流和迁移协调。
- `render.yaml`提供相同服务配置，数据库连接串由现有资源提供。它没有创建数据库的定义；更改前先在Render预览将发生的资源变化。

启动程序先运行数据库迁移，成功才启动服务。不要使用`db.create_all`替代升级既有数据库，不要删除旧表或清空正式数据。

## 发布步骤

1. 运行本机`pytest`、`scripts/verify_browser.py`和`scripts/verify_platform.py`；生成部署包或将同一份代码提交到可审阅分支。
2. 先备份旧线上数据，确认持久PostgreSQL、管理员和密钥已配置。
3. 在现有Render服务选择正确代码仓库/分支，核对上述构建、启动和健康检查命令，再手动部署具体提交。
4. 日志中确认迁移成功，服务健康检查返回200。本轮固定条款和RRT需执行追加迁移至`b6d208a134f0`，先备份再升级，不补写历史答案。只读的`scripts/verify_deployment.py`会自动识别旧8页首页和新学习门户；识别到新门户时，额外检查`/apply`、`/assessment`及`platform.css`哈希。
5. 设置临时测试模式，在预发布环境检查新首页`/`、平台学习页、`/apply?test=1`及旧`/?test=1&source=...`跳转；完成8页填写和后台导出。测试数据应清楚标为TEST，正式采集前关闭测试模式。学习页不应产生研究API请求，学习记录只在本浏览器。
6. 用安卓、iPhone及微信内置浏览器，在移动网络下打开公开链接，检查平台首页、学习测评提交后的解释、科普阅读标记、三个工具、`/apply`的8页填写、返回、提交回执和后台结果。开发者本机无头浏览器不代替此项验收。
7. 重启服务，确认先前已保存记录和后台登录仍正常；导出CSV核对行数，确认学习平台数据未出现在研究CSV中。完成后记录真实服务版本与日期，并把README、`docs/打开网站.md`中的“未发布”状态改为实际验证结果。

## 日常备份与恢复

- 每天导出已提交正式样本的分析CSV，必要时另导出申请行为明细，保存到研究者私有位置。
- 完整PostgreSQL备份使用所选数据库服务提供的逻辑导出/恢复功能；恢复测试在独立数据库进行，核对记录数、回执和内容哈希后再制定正式恢复操作。
- 本机SQLite可以运行`scripts/backup_local.py`生成一致副本。`start_local.ps1`会在迁移前自动执行备份。
- 回退程序版本前核对数据库是否兼容，不对正在使用的正式数据库盲目执行降级迁移。

## 官方参考

- [Flask部署](https://render.com/docs/deploy-flask)
- [Blueprint配置](https://render.com/docs/blueprint-spec)
- [PostgreSQL连接](https://render.com/docs/postgresql-creating-connecting)
- [Python版本设置](https://render.com/docs/python-version)
- [临时文件系统与免费服务限制](https://render.com/docs/free)
