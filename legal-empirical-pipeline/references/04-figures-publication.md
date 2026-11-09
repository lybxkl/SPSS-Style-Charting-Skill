# 出版级图表规范

> 完整的图型目录、SPSS 高级图形对应和默认图表包见 `07-chart-atlas.md`；批量出图用 `scripts/auto_chart_pack.py`。本文件只讲“怎么把一张图做成投稿级”。

## 目标

同一篇论文里的图，应该像同一个人做的：同一宽度、同一字号、同一颜色语义、同一误差线规则。期刊不会因为一张图“好看”接收论文，但会因为图不专业而要求返修。

## 物理规格

| 项目 | 建议值 |
|---|---|
| 物理宽度 | 15.0 cm（A4 正文 15.4 cm 内） |
| 单栏图高度 | 4–9 cm |
| 双面板高度 | 6–8 cm |
| 字体 | 中文宋体（SimSun），西文 Times New Roman |
| 字号 | 轴标签/图例 7.2–8.5 pt；面板字母 9 pt |
| 线宽 | 轴线 0.6 pt；误差线 0.7–0.9 pt |
| 分辨率 | PNG/TIFF 600 dpi |
| 矢量 | PDF，字体 Type 42 嵌入 |
| TIFF 压缩 | LZW，无损 |

不要用 PowerPoint 默认配色，不要用 3D 柱状图，不要在图内加标题。图题和图注在 Word 里排。

## 统一风格

```python
from pubfig import set_style, save_fig

set_style()  # 15 cm, SimSun + Times New Roman, 600 dpi
```

`pubfig.py` 提供：

- `set_style(width_cm=15.0, font_cjk="SimSun", font_latin="Times New Roman")`
- `save_fig(fig, out_dir, name, formats=("png", "pdf", "tiff"))`
- `wilson_ci(k, n)`
- `style_axis(ax, grid_axis="y")`
- `panel_label(ax, "a")`
- `forest_plot(...)`
- `binary_array(...)`：ROC/校准的 0/1 或“是/否”标签编码；未知二值标签直接报错，不猜正类。
- `pie_chart(..., sort=False)`：环形/饼图；有序层级必须关掉按大小排序。
- `qq_plot(...)`、`control_chart(...)`：正态 Q-Q、p 图/X-bar 3σ 控制图。
- `dendrogram_plot(...)`、`classical_mds(...)`、`mds_plot(...)`：层次聚类与经典 MDS，不依赖 sklearn。
- `pr_curve(...)`、`lift_chart(...)`、`confusion_heatmap(...)`：正类较少时的诊断图。
- `kaplan_meier(...)`：无 lifelines 依赖的 KM 曲线，支持删失标记。

`auto_chart_pack.py` 会把 `variable_labels` / `value_labels` 用在轴标签和图注里；`chart_manifest.csv` 的 N 会回写到图注。连续结果自动出“结果分布 + Q-Q + 分组均值+95%CI + 均值趋势”，多分类结果自动出“结果分布 + 组内 100% 堆叠 + 构成趋势”；有 `--coef`/`--pred` 时补森林、ROC、校准、混淆矩阵、PR、Lift；有 `--survival-time/--survival-event` 时补 KM。小样本组（默认 n<10）宁可不画，也不做误导性比较。

## 颜色语义

全稿统一，不要每张图重新发明颜色：

| 语义 | 建议色 | 用途 |
|---|---|---|
| 主结果/处理组 | 深蓝 `#2F5C8A` | 核心类别 |
| 对照/参照组 | 赭橙 `#B45F3C` | 与主结果对比 |
| 第三类/补充组 | 灰绿 `#5B7F62` | 补充类别 |
| 其他/未分类 | 中灰 `#8A8A8A` | 基准/其他 |
| 强调/风险 | 深红 `#8E3324` | 负向、需警示 |
| 网格 | 浅灰 `#E4E4E4` | 辅助线 |

同一阶段在阶段图、森林图、交互图里用同一颜色；同一类别在类别结构图、落差图、对应分析里用同一颜色。

## 常见图型

### 比例 + 95% CI

- 点估计用实心点，误差线用 95% Wilson CI。
- 不要用柱状图叠误差线代替点图；柱高会误导读者把面积当比例。
- 在 n<30 的组旁标注样本量，或直接不画。

### 森林图

- OR 用对数轴；参考线 OR=1。
- 实心点 = 95%CI 不含 1；空心点 = 不显著。
- 左侧放变量标签，右侧放 OR（95%CI）文本。
- 参照组不画点，在表注说明。

### 趋势图

- 年度点估计 + 95%CI；样本量 <30 的年份不单独下结论。
- 不要用平滑曲线掩盖年度波动；需要平滑时说明方法与带宽。
- 横轴年份按等距，不按样本量。

### 交互图

- 纵轴为预测概率或组内均值，注明是哪一个。
- 两条线分别代表调节变量的两个水平；误差线为 95%CI。
- 图注写清交互模型 N、参照组、控制变量。

### 对应分析

- 只作为探索性工具，不单独据此下结论。
- 图注写清纳入的阶段/类别、排除的类别、维度解释率。
- 不要把维度 1/2 擅自命名，除非有外部验证。

## 图注模板

```text
图 2  处理阶段与结果发生率（N=1,200）
注：点为阶段内结果发生率，误差线为 95% Wilson CI；样本为研究期内的
裁判文书；阶段按裁判时点可查证的最高处理事实编码；“结果”指裁判理由
或判项中明确记载的处理结论。数据来源：裁判文书数据库。示例数值为虚构。
```

图注四要素：

1. 图号 + 标题（标题说“是什么”，不说“结论是什么”）。
2. N 与样本范围。
3. 点/线/误差线/颜色的定义。
4. 数据来源与必要的编码说明。

## 导出

```python
fig.savefig(f"{out}/{name}.png", dpi=600, facecolor="white")
fig.savefig(f"{out}/{name}.pdf", facecolor="white")  # 字体嵌入
fig.savefig(f"{out}/{name}.tiff", dpi=600, facecolor="white",
            pil_kwargs={"compression": "tiff_lzw"})
```

投稿优先级：

1. 单图矢量 PDF（字体已嵌入）。
2. 期刊要求位图时用 600 dpi TIFF。
3. PNG 用于 Word 内嵌和预览。
4. 合并 PDF 只用于预览，不要直接投稿。

## 导出后检查

- PDF 打开后放大 400%，文字不模糊、不出锯齿。
- 中文没有变成方框；负号显示正常。
- 图宽 15 cm 时，最小字号 ≥7 pt。
- 颜色在灰度打印下仍可区分（或加线型/标记）。
- 图注中的 N 与数据、表、正文一致。
- 每张图都有独立源文件，不依赖 Word 截图。

## Word 导 PDF 的陷阱

Word 导 PDF 时会把嵌入图重采样到约 200 dpi。文件看起来正常，但印刷会糊。解决：

1. Word 里保留 600 dpi PNG。
2. 导出 PDF 后用 `export_pdf_hires.py` 按图题定位并回填原图。图题 tag 有数字边界，`图1` 不会匹配 `图10`；优先匹配行首图题，避免被正文“见图1”带偏。
3. 用 PyMuPDF 检查每张内嵌图宽度 ≥3000 px（15 cm 宽时约 600 dpi）。`qa_outputs.py` 只检查图幅足够大的图，logo/公式碎片不会误报；低分辨率大图仍会报错。

不要用“另存为 PDF”后直接投稿，除非已验证内嵌图分辨率。
