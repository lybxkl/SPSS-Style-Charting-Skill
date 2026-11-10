# 缺陷索引与修复状态

本文件对应逐文件读码审计（4 份报告），共 **132 条**（P0 4 / P1 61 / P2 67）。状态只有三档，都可验证：

| 状态 | 判定方式 |
|---|---|
| `已修·测试覆盖` | `tests/` 中存在覆盖该编号的用例（方法名或内联标记） |
| `已修·代码可见` | 本轮 `CHANGELOG.md` 点名该编号，且同族新标识在 `scripts/` 中实际出现 |
| `未单独验证` | 本轮没有专门用例、`CHANGELOG` 也未点名；可能随其他修复顺带解决，也可能仍未处理，需逐条人工确认 |

审计明细（每条的证据 `file:line`、代码原文、后果与修法）不随本仓库发布——它们含有真实语料的统计数字。本文件只保留编号与结论。

---

## Part A 语料审计 / 去重 / 抽取（35 条）

| 编号 | 严重度 | 问题 | 状态 | 证据 |
|---|---|---|---|---|
| AUD-01 | P0 | 单个文件 `getsize` 失败会让整次扫描崩溃，且已扫结果全部丢失 | 已修·测试覆盖 | `test_audit_layer.py::test_aud01_unreadable_file_does_not_kill_scan`<br>`test_audit_layer.py::test_aud01_classify_exception_is_recorded` |
| AUD-02 | P1 | `hidden` 状态在 Windows 上只认"点开头"，系统隐藏属性完全不识别 | 已修·测试覆盖 | `test_audit_layer.py::test_aud02_windows_hidden_attribute` |
| AUD-03 | P1 | `--min-chars` 比较全文字符总数，页码/页脚就足以让扫描件变成 valid | 已修·测试覆盖 | `test_audit_layer.py::test_aud03_page_numbers_do_not_count_as_text` |
| AUD-04 | P1 | `chars` 的口径把换行/页码/页脚全算进去，逐字换行的页面上约为真实字数的 2 倍 | 已修·测试覆盖 | `test_audit_layer.py::test_aud04_effective_chars_ignores_layout_newlines` |
| AUD-05 | P1 | 去重只有"字节级"一层，`references` 承诺的三层只实现了一层 | 已修·测试覆盖 | `test_audit_layer.py::test_aud05_content_dedupe_finds_reformatted_copy` |
| AUD-06 | P1 | 审计表没有任何抽样框字段，"检索词目的性抽样"被当成全样本 | 已修·测试覆盖 | `test_audit_layer.py::test_aud06_sampling_frame` |
| AUD-07 | P1 | 列名契约断裂：CSV 写 `relpath`，全 skill 无 `rel_path`，文档还漏列 5 个字段 | 已修·测试覆盖 | `test_audit_layer.py::test_aud07_rel_path_and_relpath_columns` |
| AUD-08 | P1 | `top` 对根目录文件为空，导致按目录分布静默丢数据 | 已修·测试覆盖 | `test_audit_layer.py::test_aud08_root_level_top_label` |
| AUD-09 | P1 | `_duplicates` 识别区分大小写，`_Duplicates` 目录不会被隔离 | 已修·测试覆盖 | `test_audit_layer.py::test_aud09_skip_dir_is_case_insensitive` |
| AUD-10 | P2 | `--no-hash` 时报告仍断言"重复组：0"，无任何"未检测"标记 | 已修·测试覆盖 | `test_audit_layer.py::test_aud10_no_hash_is_reported_honestly` |
| AUD-11 | P2 | `--out-dir` 落在 `--root` 内时，第二次运行会把自己的产物算成有效资料 | 已修·测试覆盖 | `test_audit_layer.py::test_aud11_out_dir_inside_root_is_not_rescanned`<br>`test_audit_layer.py::test_aud11b_out_dir_equal_root_is_not_self_audited` |
| AUD-12 | P2 | `md5` 只覆盖 4 类之外的文件，"重复组"的分母从未披露 | 已修·测试覆盖 | `test_audit_layer.py::test_aud12_md5_coverage_is_reported` |
| AUD-13 | P2 | `keeper_score` 的优先级与文档承诺的顺序不一致，"人工裁决"那一档没实现 | 已修·测试覆盖 | `test_audit_layer.py::test_aud13_keeper_rules_and_reason` |
| AUD-14 | P2 | `year_hint` 没有边界，`1920px`、`file-2000-1` 都会被当成年份 | 已修·测试覆盖 | `test_audit_layer.py::test_aud14_year_hint_boundaries` |
| AUD-15 | P2 | `iter_files` 没有 `onerror`，不可读目录静默消失 | 未单独验证 | — |
| AUD-16 | P2 | `--max-files` 截断后仍输出"完整"报告，无 `truncated` 标记 | 已修·测试覆盖 | `test_audit_layer.py::test_aud16_legacy_audit_csv_is_written`<br>`test_audit_layer.py::test_aud16_max_files_truncation_recorded` |
| AUD-17 | P2 | 页数/字符汇总在混合语料上静默少算 | 已修·测试覆盖 | `test_audit_layer.py::test_aud17_pages_missing_counter` |
| AUD-18 | P2 | `unsupported` 靠错误字符串关键词猜，语义不稳定 | 已修·测试覆盖 | `test_audit_layer.py::test_aud18_error_kinds_distinguish_unsupported_and_corrupt` |
| DED-01 | P1 | `--apply` 不校验 keeper 是否还在盘上，唯一副本会被移走，文书法外消失 | 已修·测试覆盖 | `test_audit_layer.py::test_ded01_missing_keeper_skips_whole_group` |
| DED-02 | P1 | 全部操作失败仍 `return 0` | 已修·测试覆盖 | `test_audit_layer.py::test_ded02_failures_return_nonzero` |
| DED-03 | P2 | 移动前不校验文件身份（无 md5/大小比对），审计过期会移错文件 | 已修·测试覆盖 | `test_audit_layer.py::test_ded03_changed_duplicate_is_not_moved` |
| DED-04 | P2 | 不可回滚：没有恢复清单/命令，`__dup2` 改名后计划里的目的地是假的 | 已修·测试覆盖 | `test_audit_layer.py::test_ded04_apply_logs_and_undo_restores`<br>`test_audit_layer.py::test_ded04_undo_conflict_refuses_overwrite` |
| DED-05 | P2 | dry-run 不检查源文件是否存在 | 已修·测试覆盖 | `test_audit_layer.py::test_ded05_plan_marks_existence_and_md5` |
| DED-06 | P2 | `--apply` 在移动失败时仍留下空目录 | 未单独验证 | — |
| DED-07 | P2 | `len(keep) != 1` 分支的注释说"warn"，实际一句都不打印 | 已修·测试覆盖 | `test_audit_layer.py::test_ded07_missing_keeper_row_warns` |
| DED-08 | P2 | 计划 CSV 每次都被覆盖，历史计划不可追溯 | 已修·测试覆盖 | `test_audit_layer.py::test_ded08_no_duplicate_groups_is_an_error` |
| EXT-01 | P1 | 没有 CLI、没有批量入口，`SKILL.md` 却把它列为文本抽取工具 | 已修·测试覆盖 | `test_audit_layer.py::test_ext01_cli_writes_documented_columns`<br>`test_audit_layer.py::test_ext01_cli_jsonl_and_min_chars` |
| EXT-02 | P1 | `decode_bytes` 的 `latin-1` 兜底让任何字节都"解码成功"，文本类文件的损坏永远检测不到 | 已修·测试覆盖 | `test_audit_layer.py::test_ext02_latin1_fallback_is_flagged` |
| EXT-03 | P2 | PDF 抽取无 `sort=True`、无逐页容错，一页坏则整份判损坏 | 已修·测试覆盖 | `test_audit_layer.py::test_ext03_pdf_text_extraction_still_works`<br>`test_audit_layer.py::test_ext03_partial_pdf_keeps_readable_pages` |
| EXT-04 | P2 | 只做"权限加密"的 PDF 被判 `encrypted`，已成功读出的正文被丢弃 | 已修·测试覆盖 | `test_audit_layer.py::test_ext04_permission_encrypted_pdf_with_text_is_readable` |
| EXT-05 | P2 | 加密的 Office 文件落 `corrupt`，与文档"不会混进 corrupt"相悖 | 已修·测试覆盖 | `test_audit_layer.py::test_ext05_ole_container_is_encrypted_office` |
| EXT-06 | P2 | `win_path` 只处理盘符路径，UNC 网络盘会拼出非法前缀 | 已修·测试覆盖 | `test_audit_layer.py::test_ext06_unc_long_path` |
| EXT-07 | P2 | `_inspect_text` 整文件读入内存，无上限 | 已修·测试覆盖 | `test_audit_layer.py::test_ext07_large_text_is_skipped_without_reading` |
| EXT-08 | P2 | `strip_markup` 会吃掉正文里 `<...>` 形式的内容 | 已修·测试覆盖 | `test_audit_layer.py::test_ext08_html_text_keeps_angle_bracket_content` |
| EXT-10 | P2 | `chars` 口径在 skill 内部三处不一致 | 已修·测试覆盖 | `test_audit_layer.py::test_ext10_chars_and_chars_effective` |

## Part B 编码表 / 分析工具 / SPSS（34 条）

| 编号 | 严重度 | 问题 | 状态 | 证据 |
|---|---|---|---|---|
| B1 | P1 | 案号正则只覆盖 8 种案由，`民申/执/民终字第` 全部漏抽 | 已修·测试覆盖 | `test_coding_layer.py:tag` |
| B2 | P1 | 法院名正则吞进"原审法院""该案经法院"，脱敏文书恒为"人民法院" | 已修·测试覆盖 | `test_coding_layer.py:tag` |
| B3 | P1 | `province` 把市级值当省级，`PROVINCE_SHORT` 白名单从未参与校验 | 已修·测试覆盖 | `test_coding_layer.py:tag` |
| B4 | P2 | 年份正则无边界，身份证号/金额/文号里的四位数字都会被当年份 | 已修·测试覆盖 | `test_coding_layer.py:tag` |
| B5 | P1 | 文书类型判定被正文引述的"原审判决如下"带偏，裁定书判成判决书 | 已修·测试覆盖 | `test_coding_layer.py:tag` |
| B6 | P1 | `--doc-type judgment` 实际不过滤裁定书，help 文案与行为不符 | 已修·测试覆盖 | `test_coding_layer.py:tag`<br>`test_coding_layer.py:tag` |
| B7 | P0 | `--audit`/`--dedupe-plan` 的排除早于所有 skip()，漏斗断链且全无效时静默空跑 | 已修·测试覆盖 | `test_coding_layer.py:tag`<br>`test_coding_layer.py:tag` |
| B8 | P1 | 证据句不切顿号逗号、500 字硬截断无标记、且没有位置信息 | 已修·测试覆盖 | `test_coding_layer.py:tag` |
| B9 | P1 | 否定与肯定同时命中，记录无 polarity，协议要求的"否定优先"零实现 | 已修·测试覆盖 | `test_coding_layer.py:tag` |
| B10 | P1 | 有"案由："时完全丢弃文件名命中，与协议"文件名优先"相反；legal 不给 `--keywords` 时案由恒空 | 已修·测试覆盖 | `test_coding_layer.py:tag` |
| B11 | P2 | `title` 取正文首个非空行，裁判文书下 100% 是法院名 | 已修·测试覆盖 | `test_coding_layer.py:tag` |
| B12 | P2 | 目录遍历未排序、`--max-files` 取任意子集，产物不可复现 | 已修·测试覆盖 | `test_coding_layer.py:tag`<br>`test_coding_layer.py:tag` |
| B13 | P2 | `skipped_documents.csv` 的 `doc_type` 列混用扩展名、kind 与空串 | 已修·测试覆盖 | `test_coding_layer.py:tag`<br>`test_coding_layer.py:tag` |
| B14 | P2 | JSONL 内嵌全文且无开关，`codes`/`evidence` 恒为空 | 已修·测试覆盖 | `test_coding_layer.py:tag`<br>`test_coding_layer.py:tag` |
| A1 | P1 | 多分类数值列超过 12 级直接判 `continuous`，省份码会被当连续变量跑 OLS | 已修·测试覆盖 | `test_coding_layer.py:tag`<br>`test_coding_layer.py:tag` |
| A2 | P1 | 全缺失列被判成 `binary` 并伪造 `{'0':0,'1':1}` 映射 | 已修·测试覆盖 | `test_coding_layer.py:tag`<br>`test_coding_layer.py:tag` |
| A3 | P2 | 二值映射表覆盖不全，`支持/不予支持`、`男/女`、`已发生/未发生` 全落 unsupported | 未单独验证 | — |
| A4 | P1 | 数值列只要出现一个 `NA`/`null`/`12%` 就整列降级为 categorical | 已修·代码可见 | CHANGELOG 有对应条目；`is_code_like`、`unsupported` |
| A5 | P1 | `is_id_like` 误杀证据列、放过来源列，模型因此丢 `_ev`、吃进 `_src` | 已修·代码可见 | CHANGELOG 有对应条目；`is_code_like`、`unsupported` |
| A6 | P1 | `apply_filter` 类型不匹配静默返回 0 行；默认 `in_analysis==1` 静默丢 NaN | 已修·测试覆盖 | `test_coding_layer.py:tag`<br>`test_coding_layer.py:tag` |
| A7 | P2 | `read_csv_auto` 的 big5 回退不可达，Big5 文件被读成乱码列名 | 已修·测试覆盖 | `test_coding_layer.py:tag` |
| A8 | P2 | `same_values` 有死代码与哨兵碰撞，`fmt` 会把 `nan`/`<NA>` 写进论文表格 | 未单独验证 | — |
| A9 | P2 | `encode_binary` 的 `int(v)` 未捕获异常，显式映射写非整数即崩溃 | 未单独验证 | — |
| A10 | P2 | `outcome_kind` 同一 `kind` 返回不同 dtype，调用方只能猜 | 未单独验证 | — |
| S1 | P1 | 一个千分位或一个 `NA` 哨兵就让整列变成字符串 A 格式 | 已修·测试覆盖 | `test_coding_layer.py:tag`<br>`test_coding_layer.py:tag` |
| S2 | P1 | `.sps` 固定以 UTF-8 写出但声明 `/ENCODING='GBK'`，中文变量名在中文 SPSS 里乱码 | 已修·测试覆盖 | `test_coding_layer.py:tag`<br>`test_coding_layer.py:tag` |
| S3 | P1 | 生成语法无 `MISSING VALUES`、无 `VARIABLE LEVEL`，NA 与 0 在 SPSS 侧无区分手段 | 已修·测试覆盖 | `test_coding_layer.py:tag`<br>`test_coding_layer.py:tag` |
| S4 | P1 | 分号分隔的 CSV 被按逗号读成单个变量，无任何告警 | 已修·代码可见 | CHANGELOG 有对应条目；`--spec`、`separation_report.csv` |
| S5 | P2 | 值标签沿用变量标签的 255 字节上限，超过 SPSS 的 120 字节限制 | 已修·代码可见 | CHANGELOG 有对应条目；`--spec`、`separation_report.csv` |
| S6 | P2 | 参差行（多列/少列）静默丢值，无一行告警 | 未单独验证 | — |
| S7 | P2 | `--sample-rows` 是无效参数，注释与实现自相矛盾 | 未单独验证 | — |
| S8 | P2 | 指数记数法只按尾数算宽度，`1e12` 声明成 `F8.0` 后在 SPSS 里溢出为缺失 | 未单独验证 | — |
| S9 | P2 | 变量改名只打印前 10 条，无映射产物，76 列中文表无法核对 | 已修·代码可见 | CHANGELOG 有对应条目；`--spec`、`separation_report.csv` |
| S10 | P2 | 非 BMP 汉字被清洗成下划线，`𠮷` 一类人名用字直接损坏 | 已修·代码可见 | CHANGELOG 有对应条目；`--spec`、`separation_report.csv` |

## Part C 自动统计 / 图表包（31 条）

| 编号 | 严重度 | 问题 | 状态 | 证据 |
|---|---|---|---|---|
| S-01 | P1 | 无多变量层：分离检测、聚类、协变量无处安放（P1） | 已修·测试覆盖 | `test_stats_charts.py:tag` |
| S-02 | P1 | 多分类哑变量分支无空单元格预检，准完全分离被当显著 OR（P1） | 已修·测试覆盖 | `test_stats_charts.py:tag` |
| S-03 | P1 | 参照组不声明，且字典序把零事件格选成参照组（P1） | 已修·测试覆盖 | `test_stats_charts.py:tag` |
| S-04 | P1 | `astype(str)` 把缺失值变成字面量 `"nan"` 类别送进模型（P1） | 已修·代码可见 | CHANGELOG 有对应条目；`--spec`、`separation_report.csv` |
| S-05 | P1 | 数值变量"不同值 ≤12"即被哑变量化，且与结局类型共用同一参数（P1） | 未单独验证 | — |
| S-06 | P1 | 按 p 排序取前 15 行，无多重比较校正（P1） | 已修·代码可见 | CHANGELOG 有对应条目；`--spec`、`separation_report.csv` |
| S-07 | P1 | 卡方→Fisher 替换后统计量与检验名不同源；r×c 从不查期望频数（P1） | 已修·代码可见 | CHANGELOG 有对应条目；`--spec`、`separation_report.csv` |
| S-08 | P2 | 静默样本丢失：六处 `continue` 不留痕，预测变量第 20 个截断（P2） | 已修·代码可见 | CHANGELOG 有对应条目；`--spec`、`separation_report.csv` |
| S-09 | P2 | `univariate_skipped.csv` 空表不落盘，跳过行缺关键字段（P2） | 已修·代码可见 | CHANGELOG 有对应条目；`--spec`、`separation_report.csv` |
| S-10 | P2 | `filter_query` 直接执行任意 pandas 表达式（P2） | 已修·测试覆盖 | `test_stats_charts.py:tag` |
| S-11 | P2 | 组间检验与相关表无 CI，结局描述缺 "95%CI" 字样（P2） | 已修·代码可见 | CHANGELOG 有对应条目；`--spec`、`separation_report.csv` |
| S-12 | P2 | 结局类型识别在两处重复实现（P2） | 已修·代码可见 | CHANGELOG 有对应条目；`--spec`、`separation_report.csv` |
| S-13 | P2 | docstring 承诺 Spearman，实现只有 Pearson（P2） | 已修·代码可见 | CHANGELOG 有对应条目；`--spec`、`separation_report.csv` |
| S-14 | P2 | `--max-categories` 使连续结局被误判为分类，提示指向错误修法（P2） | 未单独验证 | — |
| P-01 | P1 | 森林图 N 回退到整份数据集（P1） | 已修·测试覆盖 | `test_stats_charts.py:tag` |
| P-02 | P1 | coef CSV 无 `metric` 列时默认按 OR 画对数轴（P1） | 已修·测试覆盖 | `test_stats_charts.py:tag` |
| P-03 | P1 | `short_label` 删「罪」再截 8 字，哑变量项全部塌缩（P1） | 已修·测试覆盖 | `test_stats_charts.py:tag` |
| P-04 | P1 | 森林图对 1e9 量级离群估计无任何处理（P1） | 已修·测试覆盖 | `test_stats_charts.py:tag` |
| P-05 | P1 | `lift_chart` 十分位方向与轴标签相反（P1） | 已修·测试覆盖 | `test_stats_charts.py:tag` |
| P-06 | P1 | `stacked_bar` 图例在轴外，`save_fig` 无 tight bbox（P1） | 已修·测试覆盖 | `test_stats_charts.py:tag` |
| P-07 | P1 | 森林图对数轴只设 major formatter，minor tick 未关（P1） | 已修·测试覆盖 | `test_stats_charts.py:tag` |
| P-08 | P1 | 图数由列数决定，无"只出这几张"入口；且同数据双图（P1） | 已修·代码可见 | CHANGELOG 有对应条目；`_fix_log_ticks`、`pad` |
| P-09 | P1 | `binary_prevalence` 的 caption N 取"最小变量"（P1） | 已修·测试覆盖 | `test_chart_pack.py:tag` |
| P-10 | P2 | `note` 列永远为空（P2） | 已修·代码可见 | CHANGELOG 有对应条目；`_fix_log_ticks`、`pad` |
| P-11 | P2 | 探索性标注只在 manifest 文本里，PNG 内没有（P2） | 未单独验证 | — |
| P-12 | P2 | `--tiff` 非默认，但交付清单要求 TIFF（P2） | 已修·代码可见 | CHANGELOG 有对应条目；`_fix_log_ticks`、`pad` |
| P-13 | P2 | `top_counts` 在数据自带「其他」时语义冲突（P2） | 未单独验证 | — |
| P-14 | P2 | `correlation_heatmap` 图注"成对删除，完整案例"自相矛盾（P2） | 未单独验证 | — |
| P-15 | P2 | `bar_with_ci` 已存在却未被使用，同一原语 6 处手拼（P2） | 未单独验证 | — |
| P-16 | P2 | `set_style(width_cm)` 的宽度参数空转（P2） | 已修·代码可见 | CHANGELOG 有对应条目；`_fix_log_ticks`、`pad` |
| P-17 | P2 | PCA/聚类缺 KMO/Bartlett/平行分析/轮廓系数；校准图丢分箱 n 且漏末点（P2） | 未单独验证 | — |

## Part D 风格库 / 终检 / PDF 导出（32 条）

| 编号 | 严重度 | 问题 | 状态 | 证据 |
|---|---|---|---|---|
| D-01 | P0 | 回填后不清理内容流，旧 200 dpi 图原样留在 PDF 里，体积≈2 倍 | 已修·测试覆盖 | `test_output_layer.py:tag`<br>`test_output_layer.py:tag` |
| D-02 | P0 | 3000 px 门槛根本不等于 600 dpi（508 dpi 也放行），且只按像素宽判定 | 已修·测试覆盖 | `test_output_layer.py:tag`<br>`test_output_layer.py:tag` |
| D-03 | P1 | 只替换主刻度格式，次刻度仍用科学计数法，与主刻度混排 | 已修·代码可见 | CHANGELOG 有对应条目；`clean_contents`、`garbage=4` |
| D-04 | P1 | `save_fig` 无任何 bbox 出口，图例锚点在轴外，一旦裁切永久失去 | 已修·代码可见 | CHANGELOG 有对应条目；`clean_contents`、`garbage=4` |
| D-05 | P1 | 硬编码 6.2–6.8 pt 字号，绕过 `base_size` 且违反"最小字号 ≥7 pt" | 未单独验证 | — |
| D-06 | P1 | `forest_plot` 零标签溢出策略，14 个长中文标签在 4 cm 面板必然重叠 | 未单独验证 | — |
| D-07 | P1 | 缺文档要求的右侧 "OR（95%CI）" 数值列 | 未单独验证 | — |
| D-08 | P1 | `pubfig` 完全没有 manifest 机制 | 未单独验证 | — |
| D-09 | P1 | `n` 用 `int(float(...))` 解析，漏斗式 N 直接判死 | 已修·代码可见 | CHANGELOG 有对应条目；`clean_contents`、`garbage=4` |
| D-10 | P1 | `N_RE` 把 "N = 3 111" 读成 3、"N=1.2万" 读成 1；caption 比对又区分大小写 | 已修·代码可见 | CHANGELOG 有对应条目；`clean_contents`、`garbage=4` |
| D-11 | P1 | 没有"图注编号 vs 正文引用一致性/连续性"检查（清单承诺，代码为零） | 未单独验证 | — |
| D-12 | P1 | 没有"表格断行/表头重复"检查 | 未单独验证 | — |
| D-13 | P1 | `--figures` 只数文件个数，72 dpi 的 PNG 也能过 600 dpi 清单 | 已修·代码可见 | CHANGELOG 有对应条目；`clean_contents`、`garbage=4` |
| D-14 | P1 | 不加 `--strict` 时 error 也返回 0 | 已修·代码可见 | CHANGELOG 有对应条目；`clean_contents`、`garbage=4` |
| D-15 | P1 | "审计表仍有 N 份重复副本"这条 warning 结构上永远消不掉，且无开关 | 未单独验证 | — |
| D-16 | P1 | 只有 Word 一条路，无 soffice 回退；Word 缺失时的提示不给替代方案 | 未单独验证 | — |
| D-17 | P1 | 回填失败只 WARN 且 exit 0，report 不做"应替换数 vs 实替换数"对账 | 未单独验证 | — |
| D-18 | P1 | `scatter_fit` 在 `logx/logy` 下用原始尺度拟合、再套对数轴，回归线必然画错 | 未单独验证 | — |
| D-19 | P2 | manifest 必需 8 列（含 `question`），文档 `06:49` 只写中文"问题/变量/N/图注/路径"，`id`/`chart_type` 完全没提；缺列只报英文列名（实测 `missing columns: ['question']`） | 已修·代码可见 | CHANGELOG 有对应条目；`clean_contents`、`garbage=4` |
| D-20 | P2 | Wilson 实现本身正确（你问的"是否用 Wilson"——是，公式无误），但 `k>n`/`k<0` 静默返回 `(0.0, 1.0)` + `RuntimeWarning: invalid value in sqrt`（实测） | 未单独验证 | — |
| D-21 | P2 | `binary_array` 遇 `pd.NA` 抛 `TypeError: boolean value of NA is ambiguous`（实测），而 `:488` 只 catch `ValueError` → 整张图脚本崩 | 未单独验证 | — |
| D-22 | P2 | `heatmap` 文字对比色用数据中点而非 `vmin/vmax` 中点，给了 `vmin/vmax` 就深底黑字 | 未单独验证 | — |
| D-23 | P2 | 每次 `heatmap`/`confusion_heatmap` 都新建 colorbar 轴（`fraction=.035`），双面板各切一刀；2×2 混淆矩阵也带色标 | 未单独验证 | — |
| D-24 | P2 | `colors` 形参被同名局部变量覆盖；`totals==0→1` 让全零行画成空白条且无告警（实测 `ylim=(0,1)`、该柱 0 高） | 未单独验证 | — |
| D-25 | P2 | `plot_distribution` 的"必须 sharex"契约未声明未断言。实测澄清：默认数据两轴 xlim 恰好一致（`[-2.8, 2.63]`），不存在默认错位，但定制 xlim 后静默错位 | 未单独验证 | — |
| D-26 | P2 | `save_fig` 未知扩展名静默落 else（`jpg`/`tif` 少 f 都走错分支）；无条件 `plt.close(fig)` 让调用方无法复用；tiff 缺 Pillow 无提示 | 未单独验证 | — |
| D-27 | P2 | `font.family=[Times, SimSun]` 在 mpl 3.11 实测回退正常（墨迹量 1121 vs 纯 SimSun 1121 vs notdef 2389；chain=`times.ttf→simsun.ttc`），但 <3.6 无逐字回退会静默豆腐块，且代码不检版本/不验字体；mathtext 仍走 DejaVu 与正文不一致 | 未单独验证 | — |
| D-28 | P2 | `axes.unicode_minus=False`。这是正确的防御：实测 SimSun 无 U+2212 字形（`minus_glyph=False`），关掉后负号走 ASCII hyphen，字体顺序变化也不会出方框 | 未单独验证 | — |
| D-29 | P2 | 环心写死 `N={int(total)}`，而 `total` 是"过滤 0 之后的和"，与图注人工 N 不同源（`05:63` 点名的经典错） | 未单独验证 | — |
| D-30 | P2 | report 的 `image_widths` 跑在保存前的内存 doc；重开成品只取 `page_count`；`replace_image` 后不校验新宽度、不查长宽比（会拉伸） | 未单独验证 | — |
| D-31 | P2 | `doc.paragraphs` 不含表格单元格/文本框，表注与文本框图注漏检 → `:148` 误报"images but no captions" | 未单独验证 | — |
| D-32 | P2 | `3000`/`200_000`/`1000` 三处魔法数在 `qa_outputs.py:103,267` 与 `export_pdf_hires.py:177,190` 各抄一遍且无注释，`200_000 or 1000` 让 1000×10 横条也算"图" | 未单独验证 | — |

---

## 汇总

| 状态 | 条数 |
|---|---|
| 已修·测试覆盖 | 68 |
| 已修·代码可见 | 25 |
| 未单独验证 | 39 |
| 合计 | 132 |

测试规模：`tests/` 159 个用例（audit 44 / coding 59 / stats+charts 25 / chart-pack 18 / output 13），全部本地 fixture，不依赖网络、真实资料、SPSS 或 Word。

## 端到端回归新发现

下面三条不在上面的审计索引里——它们是拿真实项目（2 878×84 分析表 + 40 份 PDF）跑完整链路时才暴露的，单文件读码看不出来。

| 编号 | 严重度 | 问题 | 状态 | 证据 |
|---|---|---|---|---|
| E2E-01 | P0 | 对应分析第二维退化时崩溃，整包中断且不写 manifest（`auto_chart_pack.py`） | 已修·测试覆盖 | `test_single_dimension_is_skipped`、`test_healthy_table_still_plots`、`test_failed_save_is_recorded_and_does_not_raise` |
| E2E-02 | P1 | `qa_outputs.py --figures` 把 3543 px（599.9 dpi）判为低于 600 dpi（`qa_outputs.py`） | 已修·测试覆盖 | `test_figures_dir_accepts_exact_600dpi` |
| E2E-03 | P1 | 逐文件清单改名 `corpus_files.csv` 却未保留旧名 `corpus_audit.csv`，文档与 `--audit` 全部失效（`audit_corpus.py`） | 已修·测试覆盖 | `test_aud16_legacy_audit_csv_is_written` |

## 未修

| 项目 | 说明 |
|---|---|
| S-05 数值列哑变量化 | 数值列取值 ≤ 12 时仍会被当成分类变量展开成哑变量；与结局类型共用同一参数。 |
| P-17 / ref03 / ref08 的方法承诺 | KMO、Bartlett 球形检验、平行分析、轮廓系数、中介效应、多重插补、交互与简单斜率、训练/验证拆分仍未实现；文档已标注「未实现，需外部脚本」。 |
| Cohen's κ | 全库没有脚本计算 κ；`SKILL.md` 已改为「人工协议」，需要自己用 SPSS/R/`sklearn.metrics.cohen_kappa_score` 算。 |
| P-01 `--coef` 的 N | `auto_chart_pack.py` 读 `--coef` 时若无 `n` 列，仍回退 `len(self.df)`，多模型混排会显示成整表行数。 |
| D-04 轴外图例 | 只做到参数化与实测重锚（`legend_loc`/`legend_anchor`/`adjust_top`），没有在 `save_fig` 内部自动纠正所有图型。 |
| AUD-15 `iter_files` 的 `onerror` | 不可读目录仍可能静默消失（文件级异常已处理，目录级未专门覆盖）。 |

这些不是遗漏，是有意留给使用者的边界：脚本不该替你算信度、也不该假装实现了没实现的统计方法。文档已在对应位置写明「未实现，需外部脚本」。
