# 验收卡 A01–A60（由台账生成，只读视图）

> 本文件由 `python tools/acceptance_cards.py render` 生成，**不要手改**；要改就改台账再重跑本命令。
> 数据源：`docs/implementation/ACCEPTANCE-RESULTS.json`
> 生成时间：2026-11-15T01:27:16+08:00
> 自检（与 `validate` 同一套规则）：passed 卡 59 张，其中 59 张字段齐备，0 条 error。

## 总览

| 结果 | 数量 |
|---|---|
| passed | 59 |
| unassessed | 1 |
| **合计** | **60** |

## 卡片

### A01 · 原件改写/删除、硬链接/输出重叠被发现；原件保护保留，失败不出成功回执

| 项 | 内容 |
|---|---|
| 编号 | A01 |
| 场景 | 原件改写/删除、硬链接/输出重叠被发现；原件保护保留，失败不出成功回执 |
| 主任务 | T01 |
| 关联任务 | T01<br>T34 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 真实错误与原件恢复范围明确，失败不发布成功回执 |
| 实际观察 | Current execution: 7 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A02 · v1 正常使用；v2 关键能力不能被旧读取器静默忽略；迁移不继承旧 verified

| 项 | 内容 |
|---|---|
| 编号 | A02 |
| 场景 | v1 正常使用；v2 关键能力不能被旧读取器静默忽略；迁移不继承旧 verified |
| 主任务 | T02 |
| 关联任务 | T02<br>T34<br>T35 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 旧能力不能消费新语义，迁移后重新核对 |
| 实际观察 | Current execution: 53 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A03 · 数字精度、重复 JSON 键、缺失/0、非法值和容差规则保持正确

| 项 | 内容 |
|---|---|
| 编号 | A03 |
| 场景 | 数字精度、重复 JSON 键、缺失/0、非法值和容差规则保持正确 |
| 主任务 | T02 |
| 关联任务 | T01<br>T02<br>T13<br>T34 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 按独立原值/有理数真值核对，非法容差拒绝 |
| 实际观察 | Current execution: 58 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A04 · 局部扫描 PDF：文字层和扫描区域均有真实读取范围，不把局部成功写成全文成功

| 项 | 内容 |
|---|---|
| 编号 | A04 |
| 场景 | 局部扫描 PDF：文字层和扫描区域均有真实读取范围，不把局部成功写成全文成功 |
| 主任务 | T05 |
| 关联任务 | T04<br>T05 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 两区读取范围真实，未恢复不称全页已读 |
| 实际观察 | Current execution: 3 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A05 · 旋转/缩放图：bbox、裁片与原页可准确互相定位，错误页/坐标被拒绝

| 项 | 内容 |
|---|---|
| 编号 | A05 |
| 场景 | 旋转/缩放图：bbox、裁片与原页可准确互相定位，错误页/坐标被拒绝 |
| 主任务 | T05 |
| 关联任务 | T04<br>T05 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 几何真值可回原页，错页/越界拒绝 |
| 实际观察 | Current execution: 2 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A06 · OCR 将字符错读：转写一致仍不能冒充原图已核，原图复核能纠正并使旧值失效

| 项 | 内容 |
|---|---|
| 编号 | A06 |
| 场景 | OCR 将字符错读：转写一致仍不能冒充原图已核，原图复核能纠正并使旧值失效 |
| 主任务 | T13 |
| 关联任务 | T05<br>T13 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 实际回看能更正并使旧81失效 |
| 实际观察 | Current execution: 5 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A07 · 跨页表、多级表头、单位与脚注正确对应；续表连接不丢观测、不重复计数

| 项 | 内容 |
|---|---|
| 编号 | A07 |
| 场景 | 跨页表、多级表头、单位与脚注正确对应；续表连接不丢观测、不重复计数 |
| 主任务 | T06 |
| 关联任务 | T06 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 独立观察/表头/脚注真值对账，不丢合法重复 |
| 实际观察 | Current execution: 7 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A08 · 合并格、公式过期缓存、日期纪元和原始空格不造成假观测或假日期

| 项 | 内容 |
|---|---|
| 编号 | A08 |
| 场景 | 合并格、公式过期缓存、日期纪元和原始空格不造成假观测或假日期 |
| 主任务 | T06 |
| 关联任务 | T06 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 独立复算和日期真值一致，空格保留 |
| 实际观察 | Current execution: 12 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A09 · 音视频转写有真实时间定位，错误词/说话身份可标争议；缺引擎和实际失败不写成功

| 项 | 内容 |
|---|---|
| 编号 | A09 |
| 场景 | 音视频转写有真实时间定位，错误词/说话身份可标争议；缺引擎和实际失败不写成功 |
| 主任务 | T07 |
| 关联任务 | T07 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 真实引擎运行与回听有证据，未知身份留疑 |
| 实际观察 | Current execution: 4 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A10 · 图像读数单列近似精度，专有/多维格式原生文件与审计视图可对账

| 项 | 内容 |
|---|---|
| 编号 | A10 |
| 场景 | 图像读数单列近似精度，专有/多维格式原生文件与审计视图可对账 |
| 主任务 | T38 |
| 关联任务 | T04<br>T07<br>T38 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 近似精度单列，原生结构/内容独立对账 |
| 实际观察 | Current execution: 2 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A11 · 埋在表格/脚注/附件和同义表述的字段能进入发现与处置；额外数据集形式被保留

| 项 | 内容 |
|---|---|
| 编号 | A11 |
| 场景 | 埋在表格/脚注/附件和同义表述的字段能进入发现与处置；额外数据集形式被保留 |
| 主任务 | T08 |
| 关联任务 | T08<br>T33 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 预先人工真值中的候选有真实处置，新形态保留 |
| 实际观察 | Current execution: 11 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A12 · 搜索回执确实对应执行和当前来源；旧索引、虚假逐文件记录或关键词未命中冒充无数据不可通过

| 项 | 内容 |
|---|---|
| 编号 | A12 |
| 场景 | 搜索回执确实对应执行和当前来源；旧索引、虚假逐文件记录或关键词未命中冒充无数据不可通过 |
| 主任务 | T09 |
| 关联任务 | T09 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 执行/来源/上下文可追，旧索引重建 |
| 实际观察 | Current execution: 8 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A13 · 模型缺数找到真实值后，实际补表、重整合、全格复核和重评模型形成闭环

| 项 | 内容 |
|---|---|
| 编号 | A13 |
| 场景 | 模型缺数找到真实值后，实际补表、重整合、全格复核和重评模型形成闭环 |
| 主任务 | T10 |
| 关联任务 | T10<br>T33 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 实际补表/整表重核/重评均可追 |
| 实际观察 | Current execution: 4 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A14 · 仍无法取得的数据留真实缺失与搜索范围，不能默认 0 或用其他实体值替代

| 项 | 内容 |
|---|---|
| 编号 | A14 |
| 场景 | 仍无法取得的数据留真实缺失与搜索范围，不能默认 0 或用其他实体值替代 |
| 主任务 | T10 |
| 关联任务 | T10 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 真实缺失及搜索范围保留 |
| 实际观察 | Current execution: 4 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A15 · 两遍抽取对不同实体的同数值、否定/转述、时间/单位冲突能够暴露并裁决

| 项 | 内容 |
|---|---|
| 编号 | A15 |
| 场景 | 两遍抽取对不同实体的同数值、否定/转述、时间/单位冲突能够暴露并裁决 |
| 主任务 | T12 |
| 关联任务 | T11<br>T12 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 独立语义真值区分并裁决 |
| 实际观察 | Current execution: 5 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A16 · 更新后全表包含键/空值/派生格再次复核；旧页面和旧记录无法自动续签

| 项 | 内容 |
|---|---|
| 编号 | A16 |
| 场景 | 更新后全表包含键/空值/派生格再次复核；旧页面和旧记录无法自动续签 |
| 主任务 | T13 |
| 关联任务 | T11<br>T12<br>T13 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 新整表逐格复核，旧补丁/签名拒绝 |
| 实际观察 | Current execution: 12 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A17 · 缺失格的证据只证明上下文可访问，不自动宣称“全篇未记载”

| 项 | 内容 |
|---|---|
| 编号 | A17 |
| 场景 | 缺失格的证据只证明上下文可访问，不自动宣称“全篇未记载” |
| 主任务 | T12 |
| 关联任务 | T11<br>T12<br>T13 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 真实全范围回查区分两者 |
| 实际观察 | Current execution: 4 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A18 · 同名异人、别名、脱敏标识有正确匹配/未匹配结果，不凭相似度强行合并

| 项 | 内容 |
|---|---|
| 编号 | A18 |
| 场景 | 同名异人、别名、脱敏标识有正确匹配/未匹配结果，不凭相似度强行合并 |
| 主任务 | T14 |
| 关联任务 | T14 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 已知匹配与未匹配按证据核对 |
| 实际观察 | Current execution: 4 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A19 · 一对多/多对多连接行数、键与分母可对账；无依据笛卡尔积被发现

| 项 | 内容 |
|---|---|
| 编号 | A19 |
| 场景 | 一对多/多对多连接行数、键与分母可对账；无依据笛卡尔积被发现 |
| 主任务 | T15 |
| 关联任务 | T15 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 独立关系真值/行数/分母对账 |
| 实际观察 | Current execution: 1 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A20 · 单位/量纲/口径和有效时间变化有明确变换或冲突，不能错误合并

| 项 | 内容 |
|---|---|
| 编号 | A20 |
| 场景 | 单位/量纲/口径和有效时间变化有明确变换或冲突，不能错误合并 |
| 主任务 | T15 |
| 关联任务 | T15 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 精确换算正确，不相容量明确冲突 |
| 实际观察 | Current execution: 1 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A21 · 内置目录以外的数学/统计实现可接入；没有默认数据集/模型/系列数量封顶

| 项 | 内容 |
|---|---|
| 编号 | A21 |
| 场景 | 内置目录以外的数学/统计实现可接入；没有默认数据集/模型/系列数量封顶 |
| 主任务 | T17 |
| 关联任务 | T16<br>T17<br>T33 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 实际执行接入、不封顶，仅宣称实测引擎 |
| 实际观察 | Current execution: 6 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A22 · 多数据集样本键、事件/配对/时点/组数分别正确；n_dropna 不作估计 N

| 项 | 内容 |
|---|---|
| 编号 | A22 |
| 场景 | 多数据集样本键、事件/配对/时点/组数分别正确；n_dropna 不作估计 N |
| 主任务 | T18 |
| 关联任务 | T16<br>T17<br>T18 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 按角色计数且n=5，独立个体不膨胀 |
| 实际观察 | Current execution: 69 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A23 · 成功退出且存在输出，但数值/方法未核的模型不获得正式推断状态

| 项 | 内容 |
|---|---|
| 编号 | A23 |
| 场景 | 成功退出且存在输出，但数值/方法未核的模型不获得正式推断状态 |
| 主任务 | T18 |
| 关联任务 | T18 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | execution完成，其余未核，不能正式推断 |
| 实际观察 | Current execution: 11 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A24 · 不可行优化、不可识别逆问题、动态方程参数/边界缺失被记录；可行实例有独立可核数值

| 项 | 内容 |
|---|---|
| 编号 | A24 |
| 场景 | 不可行优化、不可识别逆问题、动态方程参数/边界缺失被记录；可行实例有独立可核数值 |
| 主任务 | T19 |
| 关联任务 | T16<br>T19<br>T33 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 解析真值x=2，不可行/不可识别如实记录 |
| 实际观察 | Current execution: 4 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A25 · 不收敛、分离、相关结构、缺失策略等按相应统计设计评估，不能填空 diagnostics 放行

| 项 | 内容 |
|---|---|
| 编号 | A25 |
| 场景 | 不收敛、分离、相关结构、缺失策略等按相应统计设计评估，不能填空 diagnostics 放行 |
| 主任务 | T20 |
| 关联任务 | T16<br>T20 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 实际设计相应诊断及结论范围正确 |
| 实际观察 | Current execution: 7 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A26 · 规格差异引起结论变化时如实呈现；不显著、失败和未运行规格保留

| 项 | 内容 |
|---|---|
| 编号 | A26 |
| 场景 | 规格差异引起结论变化时如实呈现；不显著、失败和未运行规格保留 |
| 主任务 | T21 |
| 关联任务 | T21 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 全量保留，差异来源及待办可追 |
| 实际观察 | Current execution: 6 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A27 · 检验族/多重比较、按组/时间划分、训练内预处理和样本外表现有正确区分

| 项 | 内容 |
|---|---|
| 编号 | A27 |
| 场景 | 检验族/多重比较、按组/时间划分、训练内预处理和样本外表现有正确区分 |
| 主任务 | T21 |
| 关联任务 | T20<br>T21 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 训练内拟合、设计留出、多重比较真实 |
| 实际观察 | Current execution: 5 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A28 · 独立实现不一致时失败或未核；合理浮点/随机/等价解差异按预设标准比较

| 项 | 内容 |
|---|---|
| 编号 | A28 |
| 场景 | 独立实现不一致时失败或未核；合理浮点/随机/等价解差异按预设标准比较 |
| 主任务 | T22 |
| 关联任务 | T19<br>T22 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 按预设标准接受等价、拒绝真实差异 |
| 实际观察 | Current execution: 9 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A29 · 原件改动及仅新增材料触发正向供值、缺失判断、发现和适用性依赖失效

| 项 | 内容 |
|---|---|
| 编号 | A29 |
| 场景 | 原件改动及仅新增材料触发正向供值、缺失判断、发现和适用性依赖失效 |
| 主任务 | T23 |
| 关联任务 | T03<br>T23<br>T33 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 正向/否定/发现/适用性均按依赖失效 |
| 实际观察 | Current execution: 17 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A30 · 受影响数据集整表重新复核；未知依赖保守失效，缓存不伪造本次验证

| 项 | 内容 |
|---|---|
| 编号 | A30 |
| 场景 | 受影响数据集整表重新复核；未知依赖保守失效，缓存不伪造本次验证 |
| 主任务 | T24 |
| 关联任务 | T23<br>T24 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 受影响整表重核，未知保守失效 |
| 实际观察 | Current execution: 21 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A31 · 仅变图/正文与仅变计算环境的影响范围可解释；干净目录与环境可重跑

| 项 | 内容 |
|---|---|
| 编号 | A31 |
| 场景 | 仅变图/正文与仅变计算环境的影响范围可解释；干净目录与环境可重跑 |
| 主任务 | T25 |
| 关联任务 | T03<br>T24<br>T25 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 影响解释明确，环境前后绑定，适当标准比较 |
| 实际观察 | Current execution: 16 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A32 · 数字相同但最高/最低、方向、时间、分母或关联/因果写错的论断被提出复核并正确处置

| 项 | 内容 |
|---|---|
| 编号 | A32 |
| 场景 | 数字相同但最高/最低、方向、时间、分母或关联/因果写错的论断被提出复核并正确处置 |
| 主任务 | T26 |
| 关联任务 | T26 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 语义错被实际复核处置，数字相同不豁免 |
| 实际观察 | Current execution: 18 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A33 · 真实 DOI 配不支持原文、仅元数据/摘要访问、撤稿/更正信息缺查均不冒充全文支持

| 项 | 内容 |
|---|---|
| 编号 | A33 |
| 场景 | 真实 DOI 配不支持原文、仅元数据/摘要访问、撤稿/更正信息缺查均不冒充全文支持 |
| 主任务 | T27 |
| 关联任务 | T27 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 观点支持/访问范围/更正状态分开核 |
| 实际观察 | Current execution: 9 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A34 · 摘要/正文/讨论/结论/附录的结果和引用版本一致，形成完整论文而非结果日志

| 项 | 内容 |
|---|---|
| 编号 | A34 |
| 场景 | 摘要/正文/讨论/结论/附录的结果和引用版本一致，形成完整论文而非结果日志 |
| 主任务 | T28 |
| 关联任务 | T26<br>T27<br>T28<br>T33 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 各部分可读且版本支持一致，测试身份明确 |
| 实际观察 | Current execution: 11 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json)<br>[docs/remediation-2026-11-14/validation-example-v3/visual-review.json](../remediation-2026-11-14/validation-example-v3/visual-review.json)<br>[docs/remediation-2026-11-14/validation-example-v3/example-summary.json](../remediation-2026-11-14/validation-example-v3/example-summary.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A35 · 绘图数据与实际点/线/类别/矩阵/误差范围一致，隐藏系列或不同分母可发现

| 项 | 内容 |
|---|---|
| 编号 | A35 |
| 场景 | 绘图数据与实际点/线/类别/矩阵/误差范围一致，隐藏系列或不同分母可发现 |
| 主任务 | T29 |
| 关联任务 | T29 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 实际绘图数据/图元与结果的差异可定位 |
| 实际观察 | Current execution: 10 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A36 · 多类别中文标签、多行图例和标注按实际边界检查；保留同图、完整文本和字号

| 项 | 内容 |
|---|---|
| 编号 | A36 |
| 场景 | 多类别中文标签、多行图例和标注按实际边界检查；保留同图、完整文本和字号 |
| 主任务 | T30 |
| 关联任务 | T30 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 真实边界与目视核查，同图全项不缩字 |
| 实际观察 | Current execution: 23 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json)<br>[docs/remediation-2026-11-14/validation-example-v3/visual-review.json](../remediation-2026-11-14/validation-example-v3/visual-review.json)<br>[docs/remediation-2026-11-14/validation-example-v3/example-summary.json](../remediation-2026-11-14/validation-example-v3/example-summary.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A37 · 连续色图、透明度、点形/边色与分类色按真实用途报告；建议不变成默认强制样式

| 项 | 内容 |
|---|---|
| 编号 | A37 |
| 场景 | 连续色图、透明度、点形/边色与分类色按真实用途报告；建议不变成默认强制样式 |
| 主任务 | T30 |
| 关联任务 | T30 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 实际用途和未核范围真实，建议不默认阻断 |
| 实际观察 | Current execution: 2 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A38 · 双栏缩图、合法窄图、长图在最终 DOCX/PDF 中检查真实 dpi/字号，源图合格不等于安置合格

| 项 | 内容 |
|---|---|
| 编号 | A38 |
| 场景 | 双栏缩图、合法窄图、长图在最终 DOCX/PDF 中检查真实 dpi/字号，源图合格不等于安置合格 |
| 主任务 | T31 |
| 关联任务 | T31 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 按实际宽高/哈希/矢量字核dpi与字号 |
| 实际观察 | Current execution: 7 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json)<br>[docs/remediation-2026-11-14/validation-example-v3/visual-review.json](../remediation-2026-11-14/validation-example-v3/visual-review.json)<br>[docs/remediation-2026-11-14/validation-example-v3/example-summary.json](../remediation-2026-11-14/validation-example-v3/example-summary.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A39 · Word 表头/续表、图题/图注、公式、交叉引用、字体/缺图和高清回填实际验证

| 项 | 内容 |
|---|---|
| 编号 | A39 |
| 场景 | Word 表头/续表、图题/图注、公式、交叉引用、字体/缺图和高清回填实际验证 |
| 主任务 | T31 |
| 关联任务 | T31<br>T33 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 真实DOCX/PDF逐页核，缺字/缺图/错回填拒绝 |
| 实际观察 | Current execution: 27 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json)<br>[docs/remediation-2026-11-14/validation-example-v3/visual-review.json](../remediation-2026-11-14/validation-example-v3/visual-review.json)<br>[docs/remediation-2026-11-14/validation-example-v3/example-summary.json](../remediation-2026-11-14/validation-example-v3/example-summary.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A40 · 发布报告区分覆盖/未恢复/未核/失败，0 错误不冒充全研究完成；包与源码/标准 SHA256 对应

| 项 | 内容 |
|---|---|
| 编号 | A40 |
| 场景 | 发布报告区分覆盖/未恢复/未核/失败，0 错误不冒充全研究完成；包与源码/标准 SHA256 对应 |
| 主任务 | T32 |
| 关联任务 | T32<br>T35<br>T36 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 范围/状态/SHA分别核，阶段成功不等完整 |
| 实际观察 | Current execution: 10 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A41 · 大文件、长表、大量数据集/模型/证据采用流式/分批处理仍对账完整，不因性能静默截断

| 项 | 内容 |
|---|---|
| 编号 | A41 |
| 场景 | 大文件、长表、大量数据集/模型/证据采用流式/分批处理仍对账完整，不因性能静默截断 |
| 主任务 | T34 |
| 关联任务 | T24<br>T34 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 全范围对账，到限留恢复点，不称语义复读已验 |
| 实际观察 | Current execution: 3 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A42 · C01–C18、V-05、已有完整性/统计/数字/Word-PDF 用例保持，无以删除失败测试处理回归

| 项 | 内容 |
|---|---|
| 编号 | A42 |
| 场景 | C01–C18、V-05、已有完整性/统计/数字/Word-PDF 用例保持，无以删除失败测试处理回归 |
| 主任务 | T34 |
| 关联任务 | T01<br>T34<br>T36 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 新实际结果与历史585记录分开，失败保留 |
| 实际观察 | Current execution: 182 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A43 · 压缩/内嵌子资源逐项登记并定位到父原件；物理文件数、逻辑单元数和独立观察数不混算，未知成员有处置

| 项 | 内容 |
|---|---|
| 编号 | A43 |
| 场景 | 压缩/内嵌子资源逐项登记并定位到父原件；物理文件数、逻辑单元数和独立观察数不混算，未知成员有处置 |
| 主任务 | T04 |
| 关联任务 | T04<br>T07<br>T08<br>T33<br>T38 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 父子/hash/范围对账，三种计数分开 |
| 实际观察 | Current execution: 3 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A44 · 原生到审计视图的维度、顺序、精确数值、前导零、Unicode、缺失与嵌套路径可独立核验；有哈希但丢字段仍失败

| 项 | 内容 |
|---|---|
| 编号 | A44 |
| 场景 | 原生到审计视图的维度、顺序、精确数值、前导零、Unicode、缺失与嵌套路径可独立核验；有哈希但丢字段仍失败 |
| 主任务 | T38 |
| 关联任务 | T02<br>T04<br>T33<br>T38 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 独立解析/重建核路径类型维度顺序内容 |
| 实际观察 | Current execution: 9 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A45 · 多输入按拟合/校准/约束/训练/验证/测试等角色逐键核算；重复测量与泄漏分别检查，不能跨表累加为独立 N

| 项 | 内容 |
|---|---|
| 编号 | A45 |
| 场景 | 多输入按拟合/校准/约束/训练/验证/测试等角色逐键核算；重复测量与泄漏分别检查，不能跨表累加为独立 N |
| 主任务 | T17 |
| 关联任务 | T02<br>T16<br>T17<br>T18<br>T33 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 角色独立核算与泄漏检查，消费者同步支持 |
| 实际观察 | Current execution: 12 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A46 · 有范围证据的合法空表与没有统计 N 的数学输入得到正确状态；无单元格不报 0/0=100%，无记录不默认事件数 0

| 项 | 内容 |
|---|---|
| 编号 | A46 |
| 场景 | 有范围证据的合法空表与没有统计 N 的数学输入得到正确状态；无单元格不报 0/0=100%，无记录不默认事件数 0 |
| 主任务 | T38 |
| 关联任务 | T02<br>T13<br>T16<br>T17<br>T33<br>T38 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 空表有范围依据，格率不适用，无N记录维度 |
| 实际观察 | Current execution: 3 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A47 · v2 特性/类型/签名及状态转移检查能拒绝缺证据、旧版回执、非法迁移和自报 ready，必需未知语义不静默消费

| 项 | 内容 |
|---|---|
| 编号 | A47 |
| 场景 | v2 特性/类型/签名及状态转移检查能拒绝缺证据、旧版回执、非法迁移和自报 ready，必需未知语义不静默消费 |
| 主任务 | T02 |
| 关联任务 | T02<br>T13<br>T18<br>T32<br>T35<br>T40 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 维护入口及新闸门拒绝不支持，扩展无损保留 |
| 实际观察 | Current execution: 24 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A48 · 任意关键写入点中断或磁盘写入失败后，发布指针不指向半成品，旧完整版本仍可读，新运行保留真实失败状态

| 项 | 内容 |
|---|---|
| 编号 | A48 |
| 场景 | 任意关键写入点中断或磁盘写入失败后，发布指针不指向半成品，旧完整版本仍可读，新运行保留真实失败状态 |
| 主任务 | T37 |
| 关联任务 | T24<br>T33<br>T34<br>T37 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 旧完整版本可读，半成品不发布，本次失败真实 |
| 实际观察 | Current execution: 4 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A49 · 两次运行或两位复核者同时写同一版本时，不覆盖其他结果、不丢复核事件；过期父版本和重复补丁可识别

| 项 | 内容 |
|---|---|
| 编号 | A49 |
| 场景 | 两次运行或两位复核者同时写同一版本时，不覆盖其他结果、不丢复核事件；过期父版本和重复补丁可识别 |
| 主任务 | T37 |
| 关联任务 | T11<br>T24<br>T33<br>T34<br>T37 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 锁/父版本/幂等防丢失覆盖，冲突明确 |
| 实际观察 | Current execution: 8 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A50 · 取消/超时/崩溃恢复时只续用输入与代码仍匹配的检查点，源变化使检查点失效，不能恢复成虚构完成

| 项 | 内容 |
|---|---|
| 编号 | A50 |
| 场景 | 取消/超时/崩溃恢复时只续用输入与代码仍匹配的检查点，源变化使检查点失效，不能恢复成虚构完成 |
| 主任务 | T37 |
| 关联任务 | T11<br>T24<br>T25<br>T33<br>T34<br>T37<br>T40 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 只恢复匹配上下文，只处理本运行资源 |
| 实际观察 | Current execution: 3 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A51 · 已知答案和独立校核不依赖待测抽取/预处理实现；两种计算共享错误预处理时不会仅凭一致判正确

| 项 | 内容 |
|---|---|
| 编号 | A51 |
| 场景 | 已知答案和独立校核不依赖待测抽取/预处理实现；两种计算共享错误预处理时不会仅凭一致判正确 |
| 主任务 | T22 |
| 关联任务 | T01<br>T21<br>T22<br>T33<br>T39 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 分层校核发现预处理错，期望不来自待测程序 |
| 实际观察 | Current execution: 3 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A52 · 每个验收卡有原件/步骤/独立期望/实际结果/环境/证据路径；仅编号、说明、mock 或 skip 不能计作实际集成通过

| 项 | 内容 |
|---|---|
| 编号 | A52 |
| 场景 | 每个验收卡有原件/步骤/独立期望/实际结果/环境/证据路径；仅编号、说明、mock 或 skip 不能计作实际集成通过 |
| 主任务 | T39 |
| 关联任务 | T33<br>T35<br>T36<br>T39 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 真实执行与判定后才可集成passed，设计仍待执行 |
| 实际观察 | Current execution: 14 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A53 · 后加的论断、文献、图、图注和文稿都注册依赖；编辑/重排/更换来源使相应审阅失效，旧文本支持不被沿用

| 项 | 内容 |
|---|---|
| 编号 | A53 |
| 场景 | 后加的论断、文献、图、图注和文稿都注册依赖；编辑/重排/更换来源使相应审阅失效，旧文本支持不被沿用 |
| 主任务 | T23 |
| 关联任务 | T03<br>T23<br>T26<br>T27<br>T28<br>T29<br>T30<br>T31<br>T33<br>T40 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 依赖注册且旧审阅失效，实印内容匹配 |
| 实际观察 | Current execution: 10 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A54 · 产品能力、用户要求范围、阶段命令成功和正式发布就绪分开；partial 或零错误不能绕过正式结果的来源/复核闸门

| 项 | 内容 |
|---|---|
| 编号 | A54 |
| 场景 | 产品能力、用户要求范围、阶段命令成功和正式发布就绪分开；partial 或零错误不能绕过正式结果的来源/复核闸门 |
| 主任务 | T32 |
| 关联任务 | T02<br>T10<br>T18<br>T28<br>T31<br>T32<br>T33<br>T35<br>T36<br>T40 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 产品项目阶段发布分开，partial不绕事实硬条件 |
| 实际观察 | Current execution: 13 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A55 · 本次执行与缓存复用有不同回执并绑定原执行和当前依据；改时间戳、遗漏依赖或借旧签名冒充新计算被拒绝

| 项 | 内容 |
|---|---|
| 编号 | A55 |
| 场景 | 本次执行与缓存复用有不同回执并绑定原执行和当前依据；改时间戳、遗漏依赖或借旧签名冒充新计算被拒绝 |
| 主任务 | T24 |
| 关联任务 | T24<br>T25<br>T33<br>T37<br>T40 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 复用与执行分开，依赖失配或伪造拒绝 |
| 实际观察 | Current execution: 7 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A56 · 不同目标参数/尺度/分母/观察窗的结果不直接按显著性比较；图文只使用具有相同支持范围的结果

| 项 | 内容 |
|---|---|
| 编号 | A56 |
| 场景 | 不同目标参数/尺度/分母/观察窗的结果不直接按显著性比较；图文只使用具有相同支持范围的结果 |
| 主任务 | T21 |
| 关联任务 | T02<br>T16<br>T18<br>T21<br>T26<br>T29<br>T33 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 按参数尺度分组，图文支持范围一致 |
| 实际观察 | Current execution: 5 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A57 · 不可行、无界、超时、可行候选、局部解与已认证全局解分开；KKT/小残差等必要证据不被升级为全局最优证明

| 项 | 内容 |
|---|---|
| 编号 | A57 |
| 场景 | 不可行、无界、超时、可行候选、局部解与已认证全局解分开；KKT/小残差等必要证据不被升级为全局最优证明 |
| 主任务 | T19 |
| 关联任务 | T19<br>T33 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 独立真值区分解质量，证据充分才认证全局 |
| 实际观察 | Current execution: 6 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A58 · 插补、估计、模拟和图像近似读数保留原始层、方法及不确定性；验证生成链不能伪装为来源直接观测

| 项 | 内容 |
|---|---|
| 编号 | A58 |
| 场景 | 插补、估计、模拟和图像近似读数保留原始层、方法及不确定性；验证生成链不能伪装为来源直接观测 |
| 主任务 | T38 |
| 关联任务 | T02<br>T07<br>T13<br>T17<br>T33<br>T38 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 原层不覆盖，方法不确定性用途可追 |
| 实际观察 | Current execution: 9 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A59 · 明确规模、资源预算和环境后测试流式/检查点对账；达到预算如实部分完成，不能静默减少数据集/模型/单元格

| 项 | 内容 |
|---|---|
| 编号 | A59 |
| 场景 | 明确规模、资源预算和环境后测试流式/检查点对账；达到预算如实部分完成，不能静默减少数据集/模型/单元格 |
| 主任务 | T34 |
| 关联任务 | T24<br>T33<br>T34 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 各档实测耗时内存/范围，到限有继续点 |
| 实际观察 | Current execution: 8 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | Retrospective repair regression over the stated synthetic scope and actual local engines. Read the mapped assertions and limitation notes; this is not a universal semantic-correctness proof. |

### A60 · 每批在实现前准备独立期望并执行相应验收；新模块既是生产者也是消费者，最终综合测试不替代前置门检

| 项 | 内容 |
|---|---|
| 编号 | A60 |
| 场景 | 每批在实现前准备独立期望并执行相应验收；新模块既是生产者也是消费者，最终综合测试不替代前置门检 |
| 主任务 | T39 |
| 关联任务 | T01<br>T08<br>T22<br>T33<br>T34<br>T36<br>T39 |
| fixture | synthetic known-answer originals constructed by the frozen test code; actual OCR/ASR and Word are invoked where named; no real empirical data claimed |
| 步骤 | 1. D:\python\python.exe F:\测试文件\SPSS-Style-Charting-Skill\tools\run_acceptance.py --map docs/comprehensive-audit-2026-11-14/acceptance-test-map.json --out docs/comprehensive-audit-2026-11-14/accepted-final |
| 独立期望 | 本批门检拒错，M7综合，必要集成齐才关任务 |
| 实际观察 | Current execution: 18 mapped tests passed; actual values, comparisons, states, elapsed time and process memory counters are in execution.json under these exact test IDs. |
| 环境 | python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.1940 64 bit (AMD64)]<br>executable: D:\python\python.exe<br>platform: Windows-11-10.0.26200-SP0 |
| 证据 | [docs/comprehensive-audit-2026-11-14/accepted-final/execution.json](../comprehensive-audit-2026-11-14/accepted-final/execution.json)<br>[docs/comprehensive-audit-2026-11-14/accepted-final/execution.log](../comprehensive-audit-2026-11-14/accepted-final/execution.log)<br>[docs/comprehensive-audit-2026-11-14/acceptance-test-map.json](../comprehensive-audit-2026-11-14/acceptance-test-map.json) |
| 状态 | unassessed |
| gap | Original implementation's per-batch pre-implementation gates have no independently verifiable historical execution chain. Current guard tests and integrated tests passed, but cannot retroactively establish that history. |
| 期望记录 → 实现 | 2026-11-14T08:33:22.474160+00:00 → 2026-11-14T17:09:44.977259+00:00 |
| 备注 | The original all-passed claim is withdrawn for this historical component. The current executable gate and its negative controls are implemented and tested. |

---

字段口径见 `tools/acceptance_cards.py` 模块文档：passed 卡必须同时具备 fixture / steps / expectation / observed / environment / evidence / command，且 `expectation_recorded_at` 早于 `implemented_at`；unassessed 必须写 gap。
