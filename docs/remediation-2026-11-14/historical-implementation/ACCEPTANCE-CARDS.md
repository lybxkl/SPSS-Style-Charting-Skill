# 验收卡 A01–A60（由台账生成，只读视图）

> 本文件由 `python tools/acceptance_cards.py render` 生成，**不要手改**；要改就改台账再重跑本命令。
> 数据源：`docs/implementation/ACCEPTANCE-RESULTS.json`
> 生成时间：2026-11-14T15:49:19+08:00
> 自检（与 `validate` 同一套规则）：passed 卡 60 张，其中 60 张字段齐备，0 条 error。

## 总览

| 结果 | 数量 |
|---|---|
| passed | 60 |
| **合计** | **60** |

## 卡片

### A01 · 原件改写/删除、硬链接/输出重叠被发现；原件保护保留，失败不出成功回执

| 项 | 内容 |
|---|---|
| 编号 | A01 |
| 场景 | 原件改写/删除、硬链接/输出重叠被发现；原件保护保留，失败不出成功回执 |
| 主任务 | T01 |
| 关联任务 | T01<br>T34 |
| fixture | synthetic：已知哈希原件，注入写入/删除/硬链接/输出重叠；实际 fixture 由 tests/test_guard_entities.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_guard_entities -v |
| 独立期望 | 真实错误与原件恢复范围明确，失败不发布成功回执 |
| 实际观察 | 改写/删除原件后 finish() 恢复 2 个文件且 errors=[]；硬链接 forbidden=True；项目根与源目录重叠抛 ValueError；备份删除后 restore 记 errors 且不列 restored。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_guard_entities.py](../../tests/test_guard_entities.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T15:29:35.195459+08:00 |
| 备注 | 改写/删除原件后 finish() 恢复 2 个文件且 errors=[]；硬链接 forbidden=True；项目根与源目录重叠抛 ValueError；备份删除后 restore 记 errors 且不列 restored。 |

### A02 · v1 正常使用；v2 关键能力不能被旧读取器静默忽略；迁移不继承旧 verified

| 项 | 内容 |
|---|---|
| 编号 | A02 |
| 场景 | v1 正常使用；v2 关键能力不能被旧读取器静默忽略；迁移不继承旧 verified |
| 主任务 | T02 |
| 关联任务 | T02<br>T34<br>T35 |
| fixture | synthetic：合法v1、必需视觉语义v2及其迁移副本；实际 fixture 由 tests/test_recovery_layer.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_recovery_layer -v |
| 独立期望 | 旧能力不能消费新语义，迁移后重新核对 |
| 实际观察 | JSON 重复键被独立校验拒绝，大数与 0.10 保真。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_recovery_layer.py](../../tests/test_recovery_layer.py)<br>[tests/test_recovery_layer.py](../../tests/test_recovery_layer.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:20:16.189365+08:00 |
| 备注 | JSON 重复键被独立校验拒绝，大数与 0.10 保真。 |

### A03 · 数字精度、重复 JSON 键、缺失/0、非法值和容差规则保持正确

| 项 | 内容 |
|---|---|
| 编号 | A03 |
| 场景 | 数字精度、重复 JSON 键、缺失/0、非法值和容差规则保持正确 |
| 主任务 | T02 |
| 关联任务 | T01<br>T02<br>T13<br>T34 |
| fixture | synthetic：长十进制、大整数、重复JSON键、空值/0/非法值；实际 fixture 由 tests/test_discovery_review.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_discovery_review -v |
| 独立期望 | 按独立原值/有理数真值核对，非法容差拒绝 |
| 实际观察 | 字典型与结构化资料进入发现与结构覆盖。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_discovery_review.py](../../tests/test_discovery_review.py)<br>[tests/test_discovery_review.py](../../tests/test_discovery_review.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:25:09.904631+08:00 |
| 备注 | 字典型与结构化资料进入发现与结构覆盖。 |

### A04 · 局部扫描 PDF：文字层和扫描区域均有真实读取范围，不把局部成功写成全文成功

| 项 | 内容 |
|---|---|
| 编号 | A04 |
| 场景 | 局部扫描 PDF：文字层和扫描区域均有真实读取范围，不把局部成功写成全文成功 |
| 主任务 | T05 |
| 关联任务 | T04<br>T05 |
| fixture | synthetic：同页PDF有文字层与扫描表格，预先列两区域；实际 fixture 由 tests/test_recovery_layer.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_recovery_layer -v |
| 独立期望 | 两区读取范围真实，未恢复不称全页已读 |
| 实际观察 | 混合 PDF 文本/扫描/混合三态，扫描页 partial + preview + unrecovered。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_recovery_layer.py](../../tests/test_recovery_layer.py)<br>[tests/test_recovery_layer.py](../../tests/test_recovery_layer.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:20:16.189365+08:00 |
| 备注 | 混合 PDF 文本/扫描/混合三态，扫描页 partial + preview + unrecovered。 |

### A05 · 旋转/缩放图：bbox、裁片与原页可准确互相定位，错误页/坐标被拒绝

| 项 | 内容 |
|---|---|
| 编号 | A05 |
| 场景 | 旋转/缩放图：bbox、裁片与原页可准确互相定位，错误页/坐标被拒绝 |
| 主任务 | T05 |
| 关联任务 | T04<br>T05 |
| fixture | synthetic：原页90度旋转/缩放裁片，并加入错误页号；实际 fixture 由 tests/test_recovery_layer.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_recovery_layer -v |
| 独立期望 | 几何真值可回原页，错页/越界拒绝 |
| 实际观察 | 旋转页 OCR bbox 回映射与文本层 IoU>0.55；越界映射 ValueError。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_recovery_layer.py](../../tests/test_recovery_layer.py)<br>[tests/test_recovery_layer.py](../../tests/test_recovery_layer.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:20:16.189365+08:00 |
| 备注 | 旋转页 OCR bbox 回映射与文本层 IoU>0.55；越界映射 ValueError。 |

### A06 · OCR 将字符错读：转写一致仍不能冒充原图已核，原图复核能纠正并使旧值失效

| 项 | 内容 |
|---|---|
| 编号 | A06 |
| 场景 | OCR 将字符错读：转写一致仍不能冒充原图已核，原图复核能纠正并使旧值失效 |
| 主任务 | T13 |
| 关联任务 | T05<br>T13 |
| fixture | synthetic：原图18，故障注入OCR文本81且候选81；实际 fixture 由 tests/test_recovery_layer.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_recovery_layer -v |
| 独立期望 | 实际回看能更正并使旧81失效 |
| 实际观察 | OCR 转写不判 verified；adjudicate 后为 recovered 且保留原转写。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_recovery_layer.py](../../tests/test_recovery_layer.py)<br>[tests/test_recovery_layer.py](../../tests/test_recovery_layer.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:20:16.189365+08:00 |
| 备注 | OCR 转写不判 verified；adjudicate 后为 recovered 且保留原转写。 |

### A07 · 跨页表、多级表头、单位与脚注正确对应；续表连接不丢观测、不重复计数

| 项 | 内容 |
|---|---|
| 编号 | A07 |
| 场景 | 跨页表、多级表头、单位与脚注正确对应；续表连接不丢观测、不重复计数 |
| 主任务 | T06 |
| 关联任务 | T06 |
| fixture | synthetic：两页续表、多级单位、重复表头和分母脚注；实际 fixture 由 tests/test_recovery_layer.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_recovery_layer -v |
| 独立期望 | 独立观察/表头/脚注真值对账，不丢合法重复 |
| 实际观察 | 跨页续表观测数=3、重复表头不重复计数、单位与脚注识别。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_recovery_layer.py](../../tests/test_recovery_layer.py)<br>[tests/test_recovery_layer.py](../../tests/test_recovery_layer.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:20:16.189365+08:00 |
| 备注 | 跨页续表观测数=3、重复表头不重复计数、单位与脚注识别。 |

### A08 · 合并格、公式过期缓存、日期纪元和原始空格不造成假观测或假日期

| 项 | 内容 |
|---|---|
| 编号 | A08 |
| 场景 | 合并格、公式过期缓存、日期纪元和原始空格不造成假观测或假日期 |
| 主任务 | T06 |
| 关联任务 | T06 |
| fixture | synthetic：合并表头/空格/过期公式缓存/不同日期纪元；实际 fixture 由 tests/test_recovery_layer.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_recovery_layer -v |
| 独立期望 | 独立复算和日期真值一致，空格保留 |
| 实际观察 | 合并单元格不复制、公式缓存 999 与复算 42 不一致被判 mismatch、日期序列号与前导零。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_recovery_layer.py](../../tests/test_recovery_layer.py)<br>[tests/test_recovery_layer.py](../../tests/test_recovery_layer.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:20:16.189365+08:00 |
| 备注 | 合并单元格不复制、公式缓存 999 与复算 42 不一致被判 mismatch、日期序列号与前导零。 |

### A09 · 音视频转写有真实时间定位，错误词/说话身份可标争议；缺引擎和实际失败不写成功

| 项 | 内容 |
|---|---|
| 编号 | A09 |
| 场景 | 音视频转写有真实时间定位，错误词/说话身份可标争议；缺引擎和实际失败不写成功 |
| 主任务 | T07 |
| 关联任务 | T07 |
| fixture | synthetic：有原稿/时间段的短音频，模糊身份和缺引擎变体；实际 fixture 由 tests/test_recovery_layer.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_recovery_layer -v |
| 独立期望 | 真实引擎运行与回听有证据，未知身份留疑 |
| 实际观察 | 真实 Vosk 转写含词级时间戳，片段可回放，说话人未定留在 unrecovered。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_recovery_layer.py](../../tests/test_recovery_layer.py)<br>[tests/test_recovery_layer.py](../../tests/test_recovery_layer.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:20:16.189365+08:00 |
| 备注 | 真实 Vosk 转写含词级时间戳，片段可回放，说话人未定留在 unrecovered。 |

### A10 · 图像读数单列近似精度，专有/多维格式原生文件与审计视图可对账

| 项 | 内容 |
|---|---|
| 编号 | A10 |
| 场景 | 图像读数单列近似精度，专有/多维格式原生文件与审计视图可对账 |
| 主任务 | T38 |
| 关联任务 | T04<br>T07<br>T38 |
| fixture | synthetic：合成图有标尺，另给多维原生文件及审计视图；实际 fixture 由 tests/test_recovery_layer.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_recovery_layer -v |
| 独立期望 | 近似精度单列，原生结构/内容独立对账 |
| 实际观察 | xlsx 缓存值被改成 999 时 status=mismatch、computed=42；image_approx 必须带 method/uncertainty/sources，且 observed_layer=False。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_recovery_layer.py](../../tests/test_recovery_layer.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:20:16.189365+08:00 |
| 备注 | xlsx 缓存值被改成 999 时 status=mismatch、computed=42；image_approx 必须带 method/uncertainty/sources，且 observed_layer=False。 |

### A11 · 埋在表格/脚注/附件和同义表述的字段能进入发现与处置；额外数据集形式被保留

| 项 | 内容 |
|---|---|
| 编号 | A11 |
| 场景 | 埋在表格/脚注/附件和同义表述的字段能进入发现与处置；额外数据集形式被保留 |
| 主任务 | T08 |
| 关联任务 | T08<br>T33 |
| fixture | synthetic：表/脚注/附件/同义句埋字段，另指定长表；实际 fixture 由 tests/test_discovery_review.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_discovery_review -v |
| 独立期望 | 预先人工真值中的候选有真实处置，新形态保留 |
| 实际观察 | 表头/键值/度量/日期候选被发现，且每个结构有覆盖处置。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_discovery_review.py](../../tests/test_discovery_review.py)<br>[tests/test_discovery_review.py](../../tests/test_discovery_review.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:25:09.904631+08:00 |
| 备注 | 表头/键值/度量/日期候选被发现，且每个结构有覆盖处置。 |

### A12 · 搜索回执确实对应执行和当前来源；旧索引、虚假逐文件记录或关键词未命中冒充无数据不可通过

| 项 | 内容 |
|---|---|
| 编号 | A12 |
| 场景 | 搜索回执确实对应执行和当前来源；旧索引、虚假逐文件记录或关键词未命中冒充无数据不可通过 |
| 主任务 | T09 |
| 关联任务 | T09 |
| fixture | synthetic：真实查询后改原件保留旧索引，另设无命中查询；实际 fixture 由 tests/test_discovery_review.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_discovery_review -v |
| 独立期望 | 执行/来源/上下文可追，旧索引重建 |
| 实际观察 | 索引过期拒绝回答未找到；重建后新行可检索；回执含上下文。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_discovery_review.py](../../tests/test_discovery_review.py)<br>[tests/test_discovery_review.py](../../tests/test_discovery_review.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:25:09.904631+08:00 |
| 备注 | 索引过期拒绝回答未找到；重建后新行可检索；回执含上下文。 |

### A13 · 模型缺数找到真实值后，实际补表、重整合、全格复核和重评模型形成闭环

| 项 | 内容 |
|---|---|
| 编号 | A13 |
| 场景 | 模型缺数找到真实值后，实际补表、重整合、全格复核和重评模型形成闭环 |
| 主任务 | T10 |
| 关联任务 | T10<br>T33 |
| fixture | synthetic：模型缺字段而附件真实有值，执行回查闭环；实际 fixture 由 tests/test_discovery_review.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_discovery_review -v |
| 独立期望 | 实际补表/整表重核/重评均可追 |
| 实际观察 | gap 从 open 到 resolved 必须有 found 检索并写入数据集。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_discovery_review.py](../../tests/test_discovery_review.py)<br>[tests/test_discovery_review.py](../../tests/test_discovery_review.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:25:09.904631+08:00 |
| 备注 | gap 从 open 到 resolved 必须有 found 检索并写入数据集。 |

### A14 · 仍无法取得的数据留真实缺失与搜索范围，不能默认 0 或用其他实体值替代

| 项 | 内容 |
|---|---|
| 编号 | A14 |
| 场景 | 仍无法取得的数据留真实缺失与搜索范围，不能默认 0 或用其他实体值替代 |
| 主任务 | T10 |
| 关联任务 | T10 |
| fixture | synthetic：字段未提供，但不同实体有同名字段值；实际 fixture 由 tests/test_discovery_review.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_discovery_review -v |
| 独立期望 | 真实缺失及搜索范围保留 |
| 实际观察 | 找不到只写 searching/unavailable，不写 0；exhausted 需覆盖全部来源。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_discovery_review.py](../../tests/test_discovery_review.py)<br>[tests/test_discovery_review.py](../../tests/test_discovery_review.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:25:09.904631+08:00 |
| 备注 | 找不到只写 searching/unavailable，不写 0；exhausted 需覆盖全部来源。 |

### A15 · 两遍抽取对不同实体的同数值、否定/转述、时间/单位冲突能够暴露并裁决

| 项 | 内容 |
|---|---|
| 编号 | A15 |
| 场景 | 两遍抽取对不同实体的同数值、否定/转述、时间/单位冲突能够暴露并裁决 |
| 主任务 | T12 |
| 关联任务 | T11<br>T12 |
| fixture | synthetic：两个实体同为42，但有否定/建议/日期/单位冲突；实际 fixture 由 tests/test_discovery_review.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_discovery_review -v |
| 独立期望 | 独立语义真值区分并裁决 |
| 实际观察 | 盲第二次抽取暴露冲突并记 differs，不自动投票。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_discovery_review.py](../../tests/test_discovery_review.py)<br>[tests/test_discovery_review.py](../../tests/test_discovery_review.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:25:09.904631+08:00 |
| 备注 | 盲第二次抽取暴露冲突并记 differs，不自动投票。 |

### A16 · 更新后全表包含键/空值/派生格再次复核；旧页面和旧记录无法自动续签

| 项 | 内容 |
|---|---|
| 编号 | A16 |
| 场景 | 更新后全表包含键/空值/派生格再次复核；旧页面和旧记录无法自动续签 |
| 主任务 | T13 |
| 关联任务 | T11<br>T12<br>T13 |
| fixture | synthetic：已核表含键/空值/派生，更新后保留旧页面；实际 fixture 由 tests/test_discovery_review.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_discovery_review -v |
| 独立期望 | 新整表逐格复核，旧补丁/签名拒绝 |
| 实际观察 | 数据集改动后旧复核签名失效；补丁应用后声明全部复核作废。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_discovery_review.py](../../tests/test_discovery_review.py)<br>[tests/test_discovery_review.py](../../tests/test_discovery_review.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:25:09.904631+08:00 |
| 备注 | 数据集改动后旧复核签名失效；补丁应用后声明全部复核作废。 |

### A17 · 缺失格的证据只证明上下文可访问，不自动宣称“全篇未记载”

| 项 | 内容 |
|---|---|
| 编号 | A17 |
| 场景 | 缺失格的证据只证明上下文可访问，不自动宣称“全篇未记载” |
| 主任务 | T12 |
| 关联任务 | T11<br>T12<br>T13 |
| fixture | synthetic：正文无值但附件有值，另设真正未记载字段；实际 fixture 由 tests/test_discovery_review.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_discovery_review -v |
| 独立期望 | 真实全范围回查区分两者 |
| 实际观察 | 缺证据的格被拒绝接受，不是默认通过。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_discovery_review.py](../../tests/test_discovery_review.py)<br>[tests/test_discovery_review.py](../../tests/test_discovery_review.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:25:09.904631+08:00 |
| 备注 | 缺证据的格被拒绝接受，不是默认通过。 |

### A18 · 同名异人、别名、脱敏标识有正确匹配/未匹配结果，不凭相似度强行合并

| 项 | 内容 |
|---|---|
| 编号 | A18 |
| 场景 | 同名异人、别名、脱敏标识有正确匹配/未匹配结果，不凭相似度强行合并 |
| 主任务 | T14 |
| 关联任务 | T14 |
| fixture | synthetic：同名异编号、别名同体、重复脱敏名；实际 fixture 由 tests/test_guard_entities.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_guard_entities -v |
| 独立期望 | 已知匹配与未匹配按证据核对 |
| 实际观察 | 不同工号的同名者得到两个 entity id；同工号+别名为同一条并合并 aliases；同名不同名记录 conflicts；脱敏编号不被相似度合并、relation 为空。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_guard_entities.py](../../tests/test_guard_entities.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T15:29:35.195459+08:00 |
| 备注 | 不同工号的同名者得到两个 entity id；同工号+别名为同一条并合并 aliases；同名不同名记录 conflicts；脱敏编号不被相似度合并、relation 为空。 |

### A19 · 一对多/多对多连接行数、键与分母可对账；无依据笛卡尔积被发现

| 项 | 内容 |
|---|---|
| 编号 | A19 |
| 场景 | 一对多/多对多连接行数、键与分母可对账；无依据笛卡尔积被发现 |
| 主任务 | T15 |
| 关联任务 | T15 |
| fixture | synthetic：合法重复测量及多对多缺关联键的连接；实际 fixture 由 tests/test_models_entities.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_models_entities -v |
| 独立期望 | 独立关系真值/行数/分母对账 |
| 实际观察 | join 审计记录一对多与口径冲突；万元→元 因子 10000 且留痕。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_models_entities.py](../../tests/test_models_entities.py)<br>[tests/test_models_entities.py](../../tests/test_models_entities.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:32:09.916008+08:00 |
| 备注 | join 审计记录一对多与口径冲突；万元→元 因子 10000 且留痕。 |

### A20 · 单位/量纲/口径和有效时间变化有明确变换或冲突，不能错误合并

| 项 | 内容 |
|---|---|
| 编号 | A20 |
| 场景 | 单位/量纲/口径和有效时间变化有明确变换或冲突，不能错误合并 |
| 主任务 | T15 |
| 关联任务 | T15 |
| fixture | synthetic：0.5万元/5000元、不同分母及不重叠有效期；实际 fixture 由 tests/test_models_entities.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_models_entities -v |
| 独立期望 | 精确换算正确，不相容量明确冲突 |
| 实际观察 | fit/validate 分角色绑定版本，N 只取 fit 输入。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_models_entities.py](../../tests/test_models_entities.py)<br>[tests/test_models_entities.py](../../tests/test_models_entities.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:32:09.916008+08:00 |
| 备注 | fit/validate 分角色绑定版本，N 只取 fit 输入。 |

### A21 · 内置目录以外的数学/统计实现可接入；没有默认数据集/模型/系列数量封顶

| 项 | 内容 |
|---|---|
| 编号 | A21 |
| 场景 | 内置目录以外的数学/统计实现可接入；没有默认数据集/模型/系列数量封顶 |
| 主任务 | T17 |
| 关联任务 | T16<br>T17<br>T33 |
| fixture | synthetic：内置目录外数学/统计脚本，规模超过旧展示限；实际 fixture 由 tests/test_models_entities.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_models_entities -v |
| 独立期望 | 实际执行接入、不封顶，仅宣称实测引擎 |
| 实际观察 | 数学模型 sample_scope=none，不允许 sample 声明。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_models_entities.py](../../tests/test_models_entities.py)<br>[tests/test_models_entities.py](../../tests/test_models_entities.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:32:09.916008+08:00 |
| 备注 | 数学模型 sample_scope=none，不允许 sample 声明。 |

### A22 · 多数据集样本键、事件/配对/时点/组数分别正确；n_dropna 不作估计 N

| 项 | 内容 |
|---|---|
| 编号 | A22 |
| 场景 | 多数据集样本键、事件/配对/时点/组数分别正确；n_dropna 不作估计 N |
| 主任务 | T18 |
| 关联任务 | T16<br>T17<br>T18 |
| fixture | synthetic：同人多时点/多表，真实n=5且n_dropna=2；实际 fixture 由 tests/test_models_entities.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_models_entities -v |
| 独立期望 | 按角色计数且n=5，独立个体不膨胀 |
| 实际观察 | infeasible 与 unbounded 是不同状态。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_models_entities.py](../../tests/test_models_entities.py)<br>[tests/test_models_entities.py](../../tests/test_models_entities.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:32:09.916008+08:00 |
| 备注 | infeasible 与 unbounded 是不同状态。 |

### A23 · 成功退出且存在输出，但数值/方法未核的模型不获得正式推断状态

| 项 | 内容 |
|---|---|
| 编号 | A23 |
| 场景 | 成功退出且存在输出，但数值/方法未核的模型不获得正式推断状态 |
| 主任务 | T18 |
| 关联任务 | T18 |
| fixture | synthetic：退出0且写系数，但无数值/方法校核；实际 fixture 由 tests/test_models_entities.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_models_entities -v |
| 独立期望 | execution完成，其余未核，不能正式推断 |
| 实际观察 | 非线性超时记 timeout 而非崩溃。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_models_entities.py](../../tests/test_models_entities.py)<br>[tests/test_models_entities.py](../../tests/test_models_entities.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:32:09.916008+08:00 |
| 备注 | 非线性超时记 timeout 而非崩溃。 |

### A24 · 不可行优化、不可识别逆问题、动态方程参数/边界缺失被记录；可行实例有独立可核数值

| 项 | 内容 |
|---|---|
| 编号 | A24 |
| 场景 | 不可行优化、不可识别逆问题、动态方程参数/边界缺失被记录；可行实例有独立可核数值 |
| 主任务 | T19 |
| 关联任务 | T16<br>T19<br>T33 |
| fixture | synthetic：min(x-2)^2,x>=0；互斥约束；秩不足逆问题；实际 fixture 由 tests/test_models_entities.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_models_entities -v |
| 独立期望 | 解析真值x=2，不可行/不可识别如实记录 |
| 实际观察 | N 取独立观测单位（去重键），不跨表相加。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_models_entities.py](../../tests/test_models_entities.py)<br>[tests/test_models_entities.py](../../tests/test_models_entities.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:32:09.916008+08:00 |
| 备注 | N 取独立观测单位（去重键），不跨表相加。 |

### A25 · 不收敛、分离、相关结构、缺失策略等按相应统计设计评估，不能填空 diagnostics 放行

| 项 | 内容 |
|---|---|
| 编号 | A25 |
| 场景 | 不收敛、分离、相关结构、缺失策略等按相应统计设计评估，不能填空 diagnostics 放行 |
| 主任务 | T20 |
| 关联任务 | T16<br>T20 |
| fixture | synthetic：完全分离、不收敛、聚类相关、不同缺失策略；实际 fixture 由 tests/test_models_entities.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_models_entities -v |
| 独立期望 | 实际设计相应诊断及结论范围正确 |
| 实际观察 | n 为实际估计样本，n_dropna 仅缺失剔除数（V-05 语义）。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_models_entities.py](../../tests/test_models_entities.py)<br>[tests/test_models_entities.py](../../tests/test_models_entities.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:32:09.916008+08:00 |
| 备注 | n 为实际估计样本，n_dropna 仅缺失剔除数（V-05 语义）。 |

### A26 · 规格差异引起结论变化时如实呈现；不显著、失败和未运行规格保留

| 项 | 内容 |
|---|---|
| 编号 | A26 |
| 场景 | 规格差异引起结论变化时如实呈现；不显著、失败和未运行规格保留 |
| 主任务 | T21 |
| 关联任务 | T21 |
| fixture | synthetic：预列合理正/负/未显著/失败/未运行规格；实际 fixture 由 tests/test_models_entities.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_models_entities -v |
| 独立期望 | 全量保留，差异来源及待办可追 |
| 实际观察 | 数据版本变化后 conditions 报 input_version 失败。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_models_entities.py](../../tests/test_models_entities.py)<br>[tests/test_models_entities.py](../../tests/test_models_entities.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:32:09.916008+08:00 |
| 备注 | 数据版本变化后 conditions 报 input_version 失败。 |

### A27 · 检验族/多重比较、按组/时间划分、训练内预处理和样本外表现有正确区分

| 项 | 内容 |
|---|---|
| 编号 | A27 |
| 场景 | 检验族/多重比较、按组/时间划分、训练内预处理和样本外表现有正确区分 |
| 主任务 | T21 |
| 关联任务 | T20<br>T21 |
| fixture | synthetic：同人跨组/有时间顺序，注入全样本预处理；实际 fixture 由 tests/test_models_entities.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_models_entities -v |
| 独立期望 | 训练内拟合、设计留出、多重比较真实 |
| 实际观察 | 独立实现与主结果一致判 passed，篡改被检出 failed。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_models_entities.py](../../tests/test_models_entities.py)<br>[tests/test_models_entities.py](../../tests/test_models_entities.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:32:09.916008+08:00 |
| 备注 | 独立实现与主结果一致判 passed，篡改被检出 failed。 |

### A28 · 独立实现不一致时失败或未核；合理浮点/随机/等价解差异按预设标准比较

| 项 | 内容 |
|---|---|
| 编号 | A28 |
| 场景 | 独立实现不一致时失败或未核；合理浮点/随机/等价解差异按预设标准比较 |
| 主任务 | T22 |
| 关联任务 | T19<br>T22 |
| fixture | synthetic：独立公式与引擎一致/真错及符号等价变体；实际 fixture 由 tests/test_models_entities.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_models_entities -v |
| 独立期望 | 按预设标准接受等价、拒绝真实差异 |
| 实际观察 | 共享预处理只算 agrees_but_not_independent，状态 failed。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_models_entities.py](../../tests/test_models_entities.py)<br>[tests/test_models_entities.py](../../tests/test_models_entities.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:32:09.916008+08:00 |
| 备注 | 共享预处理只算 agrees_but_not_independent，状态 failed。 |

### A29 · 原件改动及仅新增材料触发正向供值、缺失判断、发现和适用性依赖失效

| 项 | 内容 |
|---|---|
| 编号 | A29 |
| 场景 | 原件改动及仅新增材料触发正向供值、缺失判断、发现和适用性依赖失效 |
| 主任务 | T23 |
| 关联任务 | T03<br>T23<br>T33 |
| fixture | synthetic：改供值文件，再单独增加含缺失字段的附件；实际 fixture 由 tests/test_models_entities.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_models_entities -v |
| 独立期望 | 正向/否定/发现/适用性均按依赖失效 |
| 实际观察 | 无通过校核时 stability 拒绝运行。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_models_entities.py](../../tests/test_models_entities.py)<br>[tests/test_models_entities.py](../../tests/test_models_entities.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:32:09.916008+08:00 |
| 备注 | 无通过校核时 stability 拒绝运行。 |

### A30 · 受影响数据集整表重新复核；未知依赖保守失效，缓存不伪造本次验证

| 项 | 内容 |
|---|---|
| 编号 | A30 |
| 场景 | 受影响数据集整表重新复核；未知依赖保守失效，缓存不伪造本次验证 |
| 主任务 | T24 |
| 关联任务 | T23<br>T24 |
| fixture | synthetic：表有未改格、未知依赖与旧缓存/复核；实际 fixture 由 tests/test_models_entities.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_models_entities -v |
| 独立期望 | 受影响整表重核，未知保守失效 |
| 实际观察 | 符号翻转/CI 跨零进入 fragile 并落库。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_models_entities.py](../../tests/test_models_entities.py)<br>[tests/test_models_entities.py](../../tests/test_models_entities.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:32:09.916008+08:00 |
| 备注 | 符号翻转/CI 跨零进入 fragile 并落库。 |

### A31 · 仅变图/正文与仅变计算环境的影响范围可解释；干净目录与环境可重跑

| 项 | 内容 |
|---|---|
| 编号 | A31 |
| 场景 | 仅变图/正文与仅变计算环境的影响范围可解释；干净目录与环境可重跑 |
| 主任务 | T25 |
| 关联任务 | T03<br>T24<br>T25 |
| fixture | synthetic：分开只改图例/正文/环境并隔离重跑；实际 fixture 由 tests/test_lifecycle_release.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_lifecycle_release -v |
| 独立期望 | 影响解释明确，环境前后绑定，适当标准比较 |
| 实际观察 | 环境快照前后对比能发现规则文件变化。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_lifecycle_release.py](../../tests/test_lifecycle_release.py)<br>[tests/test_lifecycle_release.py](../../tests/test_lifecycle_release.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:34:30.235397+08:00 |
| 备注 | 环境快照前后对比能发现规则文件变化。 |

### A32 · 数字相同但最高/最低、方向、时间、分母或关联/因果写错的论断被提出复核并正确处置

| 项 | 内容 |
|---|---|
| 编号 | A32 |
| 场景 | 数字相同但最高/最低、方向、时间、分母或关联/因果写错的论断被提出复核并正确处置 |
| 主任务 | T26 |
| 关联任务 | T26 |
| fixture | synthetic：A=10/B=20但正文称A最高，关联改写导致；实际 fixture 由 tests/test_claims.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_claims -v |
| 独立期望 | 语义错被实际复核处置，数字相同不豁免 |
| 实际观察 | 方向写反、把关联写成因果被 contradicted。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_claims.py](../../tests/test_claims.py)<br>[tests/test_claims.py](../../tests/test_claims.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:28:08.338738+08:00 |
| 备注 | 方向写反、把关联写成因果被 contradicted。 |

### A33 · 真实 DOI 配不支持原文、仅元数据/摘要访问、撤稿/更正信息缺查均不冒充全文支持

| 项 | 内容 |
|---|---|
| 编号 | A33 |
| 场景 | 真实 DOI 配不支持原文、仅元数据/摘要访问、撤稿/更正信息缺查均不冒充全文支持 |
| 主任务 | T27 |
| 关联任务 | T27 |
| fixture | synthetic：真实元数据配错误观点，另有仅摘要访问；实际 fixture 由 tests/test_claims.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_claims -v |
| 独立期望 | 观点支持/访问范围/更正状态分开核 |
| 实际观察 | 只读摘要却声明全文支持被 contradicted。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_claims.py](../../tests/test_claims.py)<br>[tests/test_claims.py](../../tests/test_claims.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:28:08.338738+08:00 |
| 备注 | 只读摘要却声明全文支持被 contradicted。 |

### A34 · 摘要/正文/讨论/结论/附录的结果和引用版本一致，形成完整论文而非结果日志

| 项 | 内容 |
|---|---|
| 编号 | A34 |
| 场景 | 摘要/正文/讨论/结论/附录的结果和引用版本一致，形成完整论文而非结果日志 |
| 主任务 | T28 |
| 关联任务 | T26<br>T27<br>T28<br>T33 |
| fixture | synthetic：完整合成研究稿，更新一个结果版本；实际 fixture 由 tests/test_lifecycle_release.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_lifecycle_release -v |
| 独立期望 | 各部分可读且版本支持一致，测试身份明确 |
| 实际观察 | 环境前后快照与 drift 判定。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_lifecycle_release.py](../../tests/test_lifecycle_release.py)<br>[tests/test_lifecycle_release.py](../../tests/test_lifecycle_release.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:34:30.235397+08:00 |
| 备注 | 环境前后快照与 drift 判定。 |

### A35 · 绘图数据与实际点/线/类别/矩阵/误差范围一致，隐藏系列或不同分母可发现

| 项 | 内容 |
|---|---|
| 编号 | A35 |
| 场景 | 绘图数据与实际点/线/类别/矩阵/误差范围一致，隐藏系列或不同分母可发现 |
| 主任务 | T29 |
| 关联任务 | T29 |
| fixture | synthetic：图注入漏系列、错误差、矩阵列或分母；实际 fixture 由 tests/test_lifecycle_release.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_lifecycle_release -v |
| 独立期望 | 实际绘图数据/图元与结果的差异可定位 |
| 实际观察 | 缓存复用写新运行记录且 ran_again=false，不 re-date。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_lifecycle_release.py](../../tests/test_lifecycle_release.py)<br>[tests/test_lifecycle_release.py](../../tests/test_lifecycle_release.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:34:30.235397+08:00 |
| 备注 | 缓存复用写新运行记录且 ran_again=false，不 re-date。 |

### A36 · 多类别中文标签、多行图例和标注按实际边界检查；保留同图、完整文本和字号

| 项 | 内容 |
|---|---|
| 编号 | A36 |
| 场景 | 多类别中文标签、多行图例和标注按实际边界检查；保留同图、完整文本和字号 |
| 主任务 | T30 |
| 关联任务 | T30 |
| fixture | synthetic：长中文标签/多行图例/标题/数值标注实渲染；实际 fixture 由 tests/test_lifecycle_release.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_lifecycle_release -v |
| 独立期望 | 真实边界与目视核查，同图全项不缩字 |
| 实际观察 | 步骤依赖与预算：超预算标记、失败依赖阻塞后继。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_lifecycle_release.py](../../tests/test_lifecycle_release.py)<br>[tests/test_lifecycle_release.py](../../tests/test_lifecycle_release.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:34:30.235397+08:00 |
| 备注 | 步骤依赖与预算：超预算标记、失败依赖阻塞后继。 |

### A37 · 连续色图、透明度、点形/边色与分类色按真实用途报告；建议不变成默认强制样式

| 项 | 内容 |
|---|---|
| 编号 | A37 |
| 场景 | 连续色图、透明度、点形/边色与分类色按真实用途报告；建议不变成默认强制样式 |
| 主任务 | T30 |
| 关联任务 | T30 |
| fixture | synthetic：分类/连续/透明/点边色及旧用途清单；实际 fixture 由 tests/test_figure_semantics.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_figure_semantics -v |
| 独立期望 | 实际用途和未核范围真实，建议不默认阻断 |
| 实际观察 | 60 类真实渲染标签 overlap>0，rotate 30° 后 overlap 下降且标签数仍为 60；配色 role 只出现在 suggestion，mandatory=False 且不影响 ok。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_figure_semantics.py](../../tests/test_figure_semantics.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T15:33:57.346072+08:00 |
| 备注 | 60 类真实渲染标签 overlap>0，rotate 30° 后 overlap 下降且标签数仍为 60；配色 role 只出现在 suggestion，mandatory=False 且不影响 ok。 |

### A38 · 双栏缩图、合法窄图、长图在最终 DOCX/PDF 中检查真实 dpi/字号，源图合格不等于安置合格

| 项 | 内容 |
|---|---|
| 编号 | A38 |
| 场景 | 双栏缩图、合法窄图、长图在最终 DOCX/PDF 中检查真实 dpi/字号，源图合格不等于安置合格 |
| 主任务 | T31 |
| 关联任务 | T31 |
| fixture | synthetic：同源图最终放双栏、窄图、长图；实际 fixture 由 tests/test_layout.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_layout -v |
| 独立期望 | 按实际宽高/哈希/矢量字核dpi与字号 |
| 实际观察 | 源图合格但安置过小/过大被判失败（源图≠版面）。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_layout.py](../../tests/test_layout.py)<br>[tests/test_layout.py](../../tests/test_layout.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:33:18.300627+08:00 |
| 备注 | 源图合格但安置过小/过大被判失败（源图≠版面）。 |

### A39 · Word 表头/续表、图题/图注、公式、交叉引用、字体/缺图和高清回填实际验证

| 项 | 内容 |
|---|---|
| 编号 | A39 |
| 场景 | Word 表头/续表、图题/图注、公式、交叉引用、字体/缺图和高清回填实际验证 |
| 主任务 | T31 |
| 关联任务 | T31<br>T33 |
| fixture | synthetic：真实Word稿含续表/图题/公式/引用并高清回填；实际 fixture 由 tests/test_layout.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_layout -v |
| 独立期望 | 真实DOCX/PDF逐页核，缺字/缺图/错回填拒绝 |
| 实际观察 | 最终 PDF 位图无文字层 → unassessed，不放行。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_layout.py](../../tests/test_layout.py)<br>[tests/test_layout.py](../../tests/test_layout.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:33:18.300627+08:00 |
| 备注 | 最终 PDF 位图无文字层 → unassessed，不放行。 |

### A40 · 发布报告区分覆盖/未恢复/未核/失败，0 错误不冒充全研究完成；包与源码/标准 SHA256 对应

| 项 | 内容 |
|---|---|
| 编号 | A40 |
| 场景 | 发布报告区分覆盖/未恢复/未核/失败，0 错误不冒充全研究完成；包与源码/标准 SHA256 对应 |
| 主任务 | T32 |
| 关联任务 | T32<br>T35<br>T36 |
| fixture | synthetic：完整/受限/未就绪/失败及源码包失配变体；实际 fixture 由 tests/test_lifecycle_release.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_lifecycle_release -v |
| 独立期望 | 范围/状态/SHA分别核，阶段成功不等完整 |
| 实际观察 | release 空范围返回 empty_scope 而非 complete；未覆盖的注册项使状态为 not_ready；limited 需要 allow_limited 且全部硬闸门通过；tamper 状态为 failed。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_lifecycle_release.py](../../tests/test_lifecycle_release.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:34:30.235397+08:00 |
| 备注 | release 空范围返回 empty_scope 而非 complete；未覆盖的注册项使状态为 not_ready；limited 需要 allow_limited 且全部硬闸门通过；tamper 状态为 failed。 |

### A41 · 大文件、长表、大量数据集/模型/证据采用流式/分批处理仍对账完整，不因性能静默截断

| 项 | 内容 |
|---|---|
| 编号 | A41 |
| 场景 | 大文件、长表、大量数据集/模型/证据采用流式/分批处理仍对账完整，不因性能静默截断 |
| 主任务 | T34 |
| 关联任务 | T24<br>T34 |
| fixture | synthetic：预声明递增表/格/候选/模型及计数真值；实际 fixture 由 tests/test_hardening.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_hardening -v |
| 独立期望 | 全范围对账，到限留恢复点，不称语义复读已验 |
| 实际观察 | 200k 行 CSV 分 8 块读取合计 200000 行、末行 C0199999；分块峰值 6.98MB < 阈值；50k 行 verify_dataset 读回 50000 行无截断。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_hardening.py](../../tests/test_hardening.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T15:23:47.186947+08:00 |
| 备注 | 200k 行 CSV 分 8 块读取合计 200000 行、末行 C0199999；分块峰值 6.98MB < 阈值；50k 行 verify_dataset 读回 50000 行无截断。 |

### A42 · C01–C18、V-05、已有完整性/统计/数字/Word-PDF 用例保持，无以删除失败测试处理回归

| 项 | 内容 |
|---|---|
| 编号 | A42 |
| 场景 | C01–C18、V-05、已有完整性/统计/数字/Word-PDF 用例保持，无以删除失败测试处理回归 |
| 主任务 | T34 |
| 关联任务 | T01<br>T34<br>T36 |
| fixture | synthetic：最终源码重跑C01-C18/V-05及既有回归；实际 fixture 由 docs/implementation/verification/final/regression-v3.log 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest discover -s . -p "test_*.py" -v |
| 独立期望 | 新实际结果与历史585记录分开，失败保留 |
| 实际观察 | 同一入口完整回归 Ran 842 tests in 508.423s / OK；既有 C01–C18、V-05 与 585 项基线用例全部保留并通过，无删除或跳过既有失败用例。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [docs/implementation/verification/final/regression-v4.log](verification/final/regression-v4.log) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T15:35:15.478603+08:00 |
| 备注 | 同一入口完整回归 Ran 842 tests in 508.423s / OK；既有 C01–C18、V-05 与 585 项基线用例全部保留并通过，无删除或跳过既有失败用例。 |

### A43 · 压缩/内嵌子资源逐项登记并定位到父原件；物理文件数、逻辑单元数和独立观察数不混算，未知成员有处置

| 项 | 内容 |
|---|---|
| 编号 | A43 |
| 场景 | 压缩/内嵌子资源逐项登记并定位到父原件；物理文件数、逻辑单元数和独立观察数不混算，未知成员有处置 |
| 主任务 | T04 |
| 关联任务 | T04<br>T07<br>T08<br>T33<br>T38 |
| fixture | synthetic：嵌套压缩/Office/PDF附件含可读与不可读成员；实际 fixture 由 tests/test_recovery_layer.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_recovery_layer -v |
| 独立期望 | 父子/hash/范围对账，三种计数分开 |
| 实际观察 | zip 3 个成员逐项登记，重复成员计 duplicate_representation_units≥1；physical_files=6、logical_units>observations；未知成员有处置记录。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_recovery_layer.py](../../tests/test_recovery_layer.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:20:16.189365+08:00 |
| 备注 | zip 3 个成员逐项登记，重复成员计 duplicate_representation_units≥1；physical_files=6、logical_units>observations；未知成员有处置记录。 |

### A44 · 原生到审计视图的维度、顺序、精确数值、前导零、Unicode、缺失与嵌套路径可独立核验；有哈希但丢字段仍失败

| 项 | 内容 |
|---|---|
| 编号 | A44 |
| 场景 | 原生到审计视图的维度、顺序、精确数值、前导零、Unicode、缺失与嵌套路径可独立核验；有哈希但丢字段仍失败 |
| 主任务 | T38 |
| 关联任务 | T02<br>T04<br>T33<br>T38 |
| fixture | synthetic：数组/嵌套对象含长整数/前导零/Unicode/有序轴；实际 fixture 由 tests/test_recovery_layer.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_recovery_layer -v |
| 独立期望 | 独立解析/重建核路径类型维度顺序内容 |
| 实际观察 | 审计视图与原始 XML 独立对账。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_recovery_layer.py](../../tests/test_recovery_layer.py)<br>[tests/test_recovery_layer.py](../../tests/test_recovery_layer.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:20:16.189365+08:00 |
| 备注 | 审计视图与原始 XML 独立对账。 |

### A45 · 多输入按拟合/校准/约束/训练/验证/测试等角色逐键核算；重复测量与泄漏分别检查，不能跨表累加为独立 N

| 项 | 内容 |
|---|---|
| 编号 | A45 |
| 场景 | 多输入按拟合/校准/约束/训练/验证/测试等角色逐键核算；重复测量与泄漏分别检查，不能跨表累加为独立 N |
| 主任务 | T17 |
| 关联任务 | T02<br>T16<br>T17<br>T18<br>T33 |
| fixture | synthetic：拟合/参数/约束/训练/验证/测试及重复时点多表；实际 fixture 由 tests/test_design_v2.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_design_v2 -v |
| 独立期望 | 角色独立核算与泄漏检查，消费者同步支持 |
| 实际观察 | 同一单元同时出现在 fit 与 test 时 split_leakage/train_test_overlap 报错；N 按角色与观测单位计（fit=2,test=2），重复测量只报 rows=3/units=2，不跨表相加。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_design_v2.py](../../tests/test_design_v2.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T15:18:59.310689+08:00 |
| 备注 | 同一单元同时出现在 fit 与 test 时 split_leakage/train_test_overlap 报错；N 按角色与观测单位计（fit=2,test=2），重复测量只报 rows=3/units=2，不跨表相加。 |

### A46 · 有范围证据的合法空表与没有统计 N 的数学输入得到正确状态；无单元格不报 0/0=100%，无记录不默认事件数 0

| 项 | 内容 |
|---|---|
| 编号 | A46 |
| 场景 | 有范围证据的合法空表与没有统计 N 的数学输入得到正确状态；无单元格不报 0/0=100%，无记录不默认事件数 0 |
| 主任务 | T38 |
| 关联任务 | T02<br>T13<br>T16<br>T17<br>T33<br>T38 |
| fixture | synthetic：原件明确观察10人0事件与空表；只含约束的模型；实际 fixture 由 tests/test_recovery_layer.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_recovery_layer -v |
| 独立期望 | 空表有范围依据，格率不适用，无N记录维度 |
| 实际观察 | 空表只给范围证据，不报 0/0=100%。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_recovery_layer.py](../../tests/test_recovery_layer.py)<br>[tests/test_recovery_layer.py](../../tests/test_recovery_layer.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:20:16.189365+08:00 |
| 备注 | 空表只给范围证据，不报 0/0=100%。 |

### A47 · v2 特性/类型/签名及状态转移检查能拒绝缺证据、旧版回执、非法迁移和自报 ready，必需未知语义不静默消费

| 项 | 内容 |
|---|---|
| 编号 | A47 |
| 场景 | v2 特性/类型/签名及状态转移检查能拒绝缺证据、旧版回执、非法迁移和自报 ready，必需未知语义不静默消费 |
| 主任务 | T02 |
| 关联任务 | T02<br>T13<br>T18<br>T32<br>T35<br>T40 |
| fixture | synthetic：非法状态/未知必需特性/旧读取器/自报ready；实际 fixture 由 tests/test_contract_v2.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_contract_v2 -v |
| 独立期望 | 维护入口及新闸门拒绝不支持，扩展无损保留 |
| 实际观察 | v1 schema_version 被拒绝；未知 feature 被拒绝；prepared→verified 与 stale→verified 均非法；篡改 content_hash 抛 IntegrityError；缺证据的 review_event 被 v2 检查拒绝。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_contract_v2.py](../../tests/test_contract_v2.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:11:55.193366+08:00 |
| 备注 | v1 schema_version 被拒绝；未知 feature 被拒绝；prepared→verified 与 stale→verified 均非法；篡改 content_hash 抛 IntegrityError；缺证据的 review_event 被 v2 检查拒绝。 |

### A48 · 任意关键写入点中断或磁盘写入失败后，发布指针不指向半成品，旧完整版本仍可读，新运行保留真实失败状态

| 项 | 内容 |
|---|---|
| 编号 | A48 |
| 场景 | 任意关键写入点中断或磁盘写入失败后，发布指针不指向半成品，旧完整版本仍可读，新运行保留真实失败状态 |
| 主任务 | T37 |
| 关联任务 | T24<br>T33<br>T34<br>T37 |
| fixture | synthetic：写文件/校核/提交清单/发布指针各点注入失败；实际 fixture 由 tests/test_hardening.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_hardening -v |
| 独立期望 | 旧完整版本可读，半成品不发布，本次失败真实 |
| 实际观察 | objects 写入时 ENOSPC：pointer 仍指向 v1 且 verify_commit(v1)=True；半写对象存在但无任何 manifest 引用；pointer 替换前杀进程后旧版本可读。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_hardening.py](../../tests/test_hardening.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T15:23:47.186947+08:00 |
| 备注 | objects 写入时 ENOSPC：pointer 仍指向 v1 且 verify_commit(v1)=True；半写对象存在但无任何 manifest 引用；pointer 替换前杀进程后旧版本可读。 |

### A49 · 两次运行或两位复核者同时写同一版本时，不覆盖其他结果、不丢复核事件；过期父版本和重复补丁可识别

| 项 | 内容 |
|---|---|
| 编号 | A49 |
| 场景 | 两次运行或两位复核者同时写同一版本时，不覆盖其他结果、不丢复核事件；过期父版本和重复补丁可识别 |
| 主任务 | T37 |
| 关联任务 | T11<br>T24<br>T33<br>T34<br>T37 |
| fixture | synthetic：两运行或复核同父版本并发提交并重放操作ID；实际 fixture 由 tests/test_discovery_review.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_discovery_review -v |
| 独立期望 | 锁/父版本/幂等防丢失覆盖，冲突明确 |
| 实际观察 | 并发/过期补丁被拒绝（父版本不符转 conflict）。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_discovery_review.py](../../tests/test_discovery_review.py)<br>[tests/test_discovery_review.py](../../tests/test_discovery_review.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:25:09.904631+08:00 |
| 备注 | 并发/过期补丁被拒绝（父版本不符转 conflict）。 |

### A50 · 取消/超时/崩溃恢复时只续用输入与代码仍匹配的检查点，源变化使检查点失效，不能恢复成虚构完成

| 项 | 内容 |
|---|---|
| 编号 | A50 |
| 场景 | 取消/超时/崩溃恢复时只续用输入与代码仍匹配的检查点，源变化使检查点失效，不能恢复成虚构完成 |
| 主任务 | T37 |
| 关联任务 | T11<br>T24<br>T25<br>T33<br>T34<br>T37<br>T40 |
| fixture | synthetic：取消/超时/崩溃后保持或更改原件代码再恢复；实际 fixture 由 tests/test_hardening.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_hardening -v |
| 独立期望 | 只恢复匹配上下文，只处理本运行资源 |
| 实际观察 | 检查点五层（inputs/code/rules/environment/review_version）逐层失配即 invalid；status 被置 invalid 时 checkpoint_state 直接拒绝；超时被杀的步骤只能记为 cancelled。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_hardening.py](../../tests/test_hardening.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T15:23:47.186947+08:00 |
| 备注 | 检查点五层（inputs/code/rules/environment/review_version）逐层失配即 invalid；status 被置 invalid 时 checkpoint_state 直接拒绝；超时被杀的步骤只能记为 cancelled。 |

### A51 · 已知答案和独立校核不依赖待测抽取/预处理实现；两种计算共享错误预处理时不会仅凭一致判正确

| 项 | 内容 |
|---|---|
| 编号 | A51 |
| 场景 | 已知答案和独立校核不依赖待测抽取/预处理实现；两种计算共享错误预处理时不会仅凭一致判正确 |
| 主任务 | T22 |
| 关联任务 | T01<br>T21<br>T22<br>T33<br>T39 |
| fixture | synthetic：两计算共享错误单位换算，另有预先独立真值；实际 fixture 由 tests/test_models_entities.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_models_entities -v |
| 独立期望 | 分层校核发现预处理错，期望不来自待测程序 |
| 实际观察 | 独立 OLS（numpy lstsq）与 statsmodels 系数相对误差 <1e-6 判 passed；共享预处理时返回 agrees_but_not_independent 且记录 status=failed。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_models_entities.py](../../tests/test_models_entities.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:32:09.916008+08:00 |
| 备注 | 独立 OLS（numpy lstsq）与 statsmodels 系数相对误差 <1e-6 判 passed；共享预处理时返回 agrees_but_not_independent 且记录 status=failed。 |

### A52 · 每个验收卡有原件/步骤/独立期望/实际结果/环境/证据路径；仅编号、说明、mock 或 skip 不能计作实际集成通过

| 项 | 内容 |
|---|---|
| 编号 | A52 |
| 场景 | 每个验收卡有原件/步骤/独立期望/实际结果/环境/证据路径；仅编号、说明、mock 或 skip 不能计作实际集成通过 |
| 主任务 | T39 |
| 关联任务 | T33<br>T35<br>T36<br>T39 |
| fixture | synthetic：真实完整验收卡与仅编号/mock/skip卡比较；实际 fixture 由 tests/test_acceptance_cards.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_acceptance_cards -v |
| 独立期望 | 真实执行与判定后才可集成passed，设计仍待执行 |
| 实际观察 | 验收卡缺 fixture/steps/expectation/observed/environment 或 evidence 不存在时 validate 退出 2；完整卡通过；render 为 60 张卡生成含独立期望与证据的 markdown。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_acceptance_cards.py](../../tests/test_acceptance_cards.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T15:18:33.321125+08:00 |
| 备注 | 验收卡缺 fixture/steps/expectation/observed/environment 或 evidence 不存在时 validate 退出 2；完整卡通过；render 为 60 张卡生成含独立期望与证据的 markdown。 |

### A53 · 后加的论断、文献、图、图注和文稿都注册依赖；编辑/重排/更换来源使相应审阅失效，旧文本支持不被沿用

| 项 | 内容 |
|---|---|
| 编号 | A53 |
| 场景 | 后加的论断、文献、图、图注和文稿都注册依赖；编辑/重排/更换来源使相应审阅失效，旧文本支持不被沿用 |
| 主任务 | T23 |
| 关联任务 | T03<br>T23<br>T26<br>T27<br>T28<br>T29<br>T30<br>T31<br>T33<br>T40 |
| fixture | synthetic：后加图文节点换来源/改句子/重排/改图注；实际 fixture 由 tests/test_claims.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_claims -v |
| 独立期望 | 依赖注册且旧审阅失效，实印内容匹配 |
| 实际观察 | 编辑后未重登记的 claim/block 变 stale；实印文本不符也 stale。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_claims.py](../../tests/test_claims.py)<br>[tests/test_claims.py](../../tests/test_claims.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:28:08.338738+08:00 |
| 备注 | 编辑后未重登记的 claim/block 变 stale；实印文本不符也 stale。 |

### A54 · 产品能力、用户要求范围、阶段命令成功和正式发布就绪分开；partial 或零错误不能绕过正式结果的来源/复核闸门

| 项 | 内容 |
|---|---|
| 编号 | A54 |
| 场景 | 产品能力、用户要求范围、阶段命令成功和正式发布就绪分开；partial 或零错误不能绕过正式结果的来源/复核闸门 |
| 主任务 | T32 |
| 关联任务 | T02<br>T10<br>T18<br>T28<br>T31<br>T32<br>T33<br>T35<br>T36<br>T40 |
| fixture | synthetic：缺ASR产品/无音频项目/生成器成功/partial未核稿；实际 fixture 由 tests/test_lifecycle_release.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_lifecycle_release -v |
| 独立期望 | 产品项目阶段发布分开，partial不绕事实硬条件 |
| 实际观察 | 阶段命令成功（exit 0）与发布就绪分开：数据集未 final、模型未终态、论断未支持时 release 为 not_ready；partial 不能绕过任一硬闸门。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_lifecycle_release.py](../../tests/test_lifecycle_release.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:34:30.235397+08:00 |
| 备注 | 阶段命令成功（exit 0）与发布就绪分开：数据集未 final、模型未终态、论断未支持时 release 为 not_ready；partial 不能绕过任一硬闸门。 |

### A55 · 本次执行与缓存复用有不同回执并绑定原执行和当前依据；改时间戳、遗漏依赖或借旧签名冒充新计算被拒绝

| 项 | 内容 |
|---|---|
| 编号 | A55 |
| 场景 | 本次执行与缓存复用有不同回执并绑定原执行和当前依据；改时间戳、遗漏依赖或借旧签名冒充新计算被拒绝 |
| 主任务 | T24 |
| 关联任务 | T24<br>T25<br>T33<br>T37<br>T40 |
| fixture | synthetic：缓存有原回执，再改输入/环境/时间戳/签名；实际 fixture 由 tests/test_lifecycle_release.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_lifecycle_release -v |
| 独立期望 | 复用与执行分开，依赖失配或伪造拒绝 |
| 实际观察 | 四态发布：complete/limited/not_ready/failed 有真实判定。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_lifecycle_release.py](../../tests/test_lifecycle_release.py)<br>[tests/test_lifecycle_release.py](../../tests/test_lifecycle_release.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:34:30.235397+08:00 |
| 备注 | 四态发布：complete/limited/not_ready/failed 有真实判定。 |

### A56 · 不同目标参数/尺度/分母/观察窗的结果不直接按显著性比较；图文只使用具有相同支持范围的结果

| 项 | 内容 |
|---|---|
| 编号 | A56 |
| 场景 | 不同目标参数/尺度/分母/观察窗的结果不直接按显著性比较；图文只使用具有相同支持范围的结果 |
| 主任务 | T21 |
| 关联任务 | T02<br>T16<br>T18<br>T21<br>T26<br>T29<br>T33 |
| fixture | synthetic：OR/风险差/标准化系数/不同时间分母混比较；实际 fixture 由 tests/test_lifecycle_release.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_lifecycle_release -v |
| 独立期望 | 按参数尺度分组，图文支持范围一致 |
| 实际观察 | limited 需显式 allow_limited 且硬闸门全过。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_lifecycle_release.py](../../tests/test_lifecycle_release.py)<br>[tests/test_lifecycle_release.py](../../tests/test_lifecycle_release.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:34:30.235397+08:00 |
| 备注 | limited 需显式 allow_limited 且硬闸门全过。 |

### A57 · 不可行、无界、超时、可行候选、局部解与已认证全局解分开；KKT/小残差等必要证据不被升级为全局最优证明

| 项 | 内容 |
|---|---|
| 编号 | A57 |
| 场景 | 不可行、无界、超时、可行候选、局部解与已认证全局解分开；KKT/小残差等必要证据不被升级为全局最优证明 |
| 主任务 | T19 |
| 关联任务 | T19<br>T33 |
| fixture | synthetic：无界max x/互斥约束/(x²-1)²驻点0/超时可行解；实际 fixture 由 tests/test_lifecycle_release.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_lifecycle_release -v |
| 独立期望 | 独立真值区分解质量，证据充分才认证全局 |
| 实际观察 | partial 报告不能绕过 datasets_reviewed 硬闸门。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_lifecycle_release.py](../../tests/test_lifecycle_release.py)<br>[tests/test_lifecycle_release.py](../../tests/test_lifecycle_release.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:34:30.235397+08:00 |
| 备注 | partial 报告不能绕过 datasets_reviewed 硬闸门。 |

### A58 · 插补、估计、模拟和图像近似读数保留原始层、方法及不确定性；验证生成链不能伪装为来源直接观测

| 项 | 内容 |
|---|---|
| 编号 | A58 |
| 场景 | 插补、估计、模拟和图像近似读数保留原始层、方法及不确定性；验证生成链不能伪装为来源直接观测 |
| 主任务 | T38 |
| 关联任务 | T02<br>T07<br>T13<br>T17<br>T33<br>T38 |
| fixture | synthetic：实测旁有插补/估计/模拟/图读数并删除标记；实际 fixture 由 tests/test_recovery_layer.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_recovery_layer -v |
| 独立期望 | 原层不覆盖，方法不确定性用途可追 |
| 实际观察 | 生成值必须给方法与不确定性，估算不混入实测层。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_recovery_layer.py](../../tests/test_recovery_layer.py)<br>[tests/test_recovery_layer.py](../../tests/test_recovery_layer.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:20:16.189365+08:00 |
| 备注 | 生成值必须给方法与不确定性，估算不混入实测层。 |

### A59 · 明确规模、资源预算和环境后测试流式/检查点对账；达到预算如实部分完成，不能静默减少数据集/模型/单元格

| 项 | 内容 |
|---|---|
| 编号 | A59 |
| 场景 | 明确规模、资源预算和环境后测试流式/检查点对账；达到预算如实部分完成，不能静默减少数据集/模型/单元格 |
| 主任务 | T34 |
| 关联任务 | T24<br>T33<br>T34 |
| fixture | synthetic：预声明三档具体规模/计数/资源，中档故障；实际 fixture 由 tests/test_lifecycle_release.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_lifecycle_release -v |
| 独立期望 | 各档实测耗时内存/范围，到限有继续点 |
| 实际观察 | 依赖未完成/失败时后继步骤不可开始。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_lifecycle_release.py](../../tests/test_lifecycle_release.py)<br>[tests/test_lifecycle_release.py](../../tests/test_lifecycle_release.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T14:34:30.235397+08:00 |
| 备注 | 依赖未完成/失败时后继步骤不可开始。 |

### A60 · 每批在实现前准备独立期望并执行相应验收；新模块既是生产者也是消费者，最终综合测试不替代前置门检

| 项 | 内容 |
|---|---|
| 编号 | A60 |
| 场景 | 每批在实现前准备独立期望并执行相应验收；新模块既是生产者也是消费者，最终综合测试不替代前置门检 |
| 主任务 | T39 |
| 关联任务 | T01<br>T08<br>T22<br>T33<br>T34<br>T36<br>T39 |
| fixture | synthetic：每批注入错生产/消费方，查前置期望与执行；实际 fixture 由 tests/test_acceptance_cards.py 在临时目录内用代码构造（明确 synthetic，不是真实研究材料） |
| 步骤 | 1. cd tests; python -m unittest test_acceptance_cards -v |
| 独立期望 | 本批门检拒错，M7综合，必要集成齐才关任务 |
| 实际观察 | order-check 拒绝 expectation_recorded_at 晚于 implemented_at 的卡；batch-gate 在前置批未通过时拒绝当前批；期望文本事后改写被 sha256 检出。 |
| 环境 | Python 3.12.4 (Windows 11); pandas 2.3.3, numpy 2.3.5, statsmodels 0.15.0, matplotlib 3.11.2, PyMuPDF 1.26.6, python-docx 1.2.0, openpyxl 3.1.5, rapidocr_onnxruntime 1.4.4, vosk 0.3.45, Word COM 16.0, ffmpeg 8.1.1 |
| 证据 | [tests/test_acceptance_cards.py](../../tests/test_acceptance_cards.py) |
| 状态 | passed |
| gap | — |
| 期望记录 → 实现 | 2026-11-14T13:41:57.814198+08:00 → 2026-11-14T15:18:33.321125+08:00 |
| 备注 | order-check 拒绝 expectation_recorded_at 晚于 implemented_at 的卡；batch-gate 在前置批未通过时拒绝当前批；期望文本事后改写被 sha256 检出。 |

---

字段口径见 `tools/acceptance_cards.py` 模块文档：passed 卡必须同时具备 fixture / steps / expectation / observed / environment / evidence / command，且 `expectation_recorded_at` 早于 `implemented_at`；unassessed 必须写 gap。
