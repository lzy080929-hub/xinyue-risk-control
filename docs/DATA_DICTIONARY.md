# 信跃数据字典

## 版本和数据单位

实验`xinyue-original-v3`；表单`original-eight-page-v1`；行为`behavior-original-v2`；29题量表仍为`repayment-29-v1`。旧版本答案保留原版本，不回填或混称新样本。

一行分析CSV代表一次参与会话。公开参与编号不是身份认证凭证，不能保证一个自然人只有一次参与。测试记录以`TEST-`开头，并有`is_test=1`。

时间戳以UTC带Z导出，后台按北京时间显示。所有`*_ms`单位为毫秒。空白通常表示未作答、未观察或历史版本未采集；不要统一替换为0。`is_test`和确认字段导出为0/1。

## 申请字段

| 字段 | 含义与范围 |
| --- | --- |
| nickname | 可选称呼，最多40字，不要求真实姓名 |
| age | 年龄，18—80整数 |
| education | high_school/college/bachelor/master_plus |
| occupation | 职业或身份，最多50字 |
| monthly_income | 可选月可支配收入，含生活费/兼职等估算，单位元；0与未答不同 |
| total_debt | 可选当前总负债，单位元，不是每月还款额 |
| debt_ratio | total_debt/monthly_income×100，由服务器计算；可超过100%，收入0或缺失时空白 |
| loan_amount | 模拟贷款金额，100—100000元整数 |
| loan_term | 模拟期限，1—60个月整数 |
| loan_purpose | 模拟用途，最多100字 |
| interest_rate | 模拟年化百分数，8.5/10.5/12.5 |
| interest_rate_confirmed | 是否确认模拟条款 |
| form_layout | 新版固定original-eight-page-v1 |
| grade/monthly_debt/loan_term_months | 阶段二兼容字段。monthly_debt是每月需还金额，不能填入total_debt或将二者合并分析 |

## 量表

`rs_q01`至`rs_q29`保存原始1—7分。反向题7、8、15、16、23、24、29，转换为8减原分。ATR题1—8、SN题9—16、PBC题17—24、LRI题25—29，分别导出`*_total`、`*_mean`、`*_valid_count`。最终提交要求29题齐全。

LRI是自报还款意向分量表，不是真实违约标签。四种构念不混为一个真实意愿总分。历史记录没有量表数据时保持空白。

## 行为特征

| 字段 | 定义 |
| --- | --- |
| application_visible_ms | 页面1—6在同意后处于可见状态的累计时间；定时、切页、隐藏和提交时结算 |
| survey_visible_ms | 页面7—8同口径累计可见时间，分开保存，不混入申请行为X |
| total_elapsed_ms | 已收到事件的最大客户端相对时间，含切后台和等待；不等于聚焦时间 |
| hidden_duration_ms | 已观察到的页面隐藏区间，恢复可见时结算；强制关闭的尾段可能未观察 |
| page_1_dwell_ms…page_8_dwell_ms | 已收到事件覆盖的各页可见时间；同意前不记录第1页浏览时间 |
| back_navigation_count | 申请阶段点击上一页的次数；量表阶段的返回不混入该申请特征 |
| non_sequential_fill_count | 申请阶段首次聚焦时跳过预先字段顺序的次数；选填项未填写也可能产生跳跃，不能解释为诚信指标 |
| related_field_switch_count | 申请阶段收入与总负债两个关联字段之间的焦点切换次数 |
| resume_count | 当前标签页刷新恢复后新启动的采集段次数；提示可能存在未同步的尾段 |
| submit_attempt_count | 进入最终提交并结算采集的次数，重试可增加 |

字段级特征以`字段名_指标`导出，仅含申请阶段：

- `focus_ms`：字段可见聚焦区间累计时长。
- `focus_count`：进入字段次数。
- `input_count`：输入事件数，包含删除；输入法组合中的中间事件不累计，组合完成计一次。
- `delete_count`：浏览器提供的删除类型输入事件数；不是删除字符数。
- `delete_after_input_count`：同次聚焦内先输入再删除的事件数，保留原型指标含义。
- `paste_count`：粘贴事件次数，不读取粘贴内容。
- `revisit_count`：第一次以外再次进入该字段次数。
- `return_edit_count`：再次进入后确实发生编辑的访问次数，每次访问至多计一次。
- `first_input_latency_ms`：首次输入前该字段累计可见聚焦时长；不是从进入网页开始的时间。

可见不代表注意力集中，聚焦或修改不能直接推断诚信、违约或因果机制。

## 同步完整性与缺失

- `received_batches/received_events`为服务端真实收到的批次/事件数。
- `expected_batches/expected_events`为最终提交时客户端声明的应有数量，不存在则为历史或未完成记录。
- `behavior_status=complete`要求批次从1连续、批次数和事件数匹配、无缓冲溢出；仅代表已声明事件运输完整，不保证外部观测无缺失。
- `incomplete`为数量不符、缺批次或缓冲丢弃；申请仍可独立保存，分析时需筛选或敏感性分析。
- `received/not_started`表示尚未声明完整性，不能自动当完整。
- `dropped_events`为缓冲达到上限时未排入队列的事件计数；不默默隐藏。
- `quality_flags`中`page_resumed`表示恢复过，`input_type_unsupported`表示浏览器不提供删除类型（删除相关字段为缺失），`event_buffer_overflow`表示事件被丢弃。

粗粒度设备类型、浏览器类别、视口尺寸用于解释设备差异，不生成设备指纹。来源`source`为招募渠道标签，不能包含个人信息。所有前端计时和自报信息都可能有误差，应保留原始事件与版本。

## CSV与研究分析

分析导出默认正式且已提交，可主动选测试或草稿。单次最多10000条参与记录，超过需按日期/版本缩小范围。文本中的电子表格公式前缀会加单引号，保护导出后打开时的安全。

事件明细仅导出application阶段的事件，无键入正文和问卷答案。量表原始题项及分数可用于Y或机制分析，不得在预测同一量表Y时无意作为输入特征。不同表单、设备和协议版本应分层核验。
