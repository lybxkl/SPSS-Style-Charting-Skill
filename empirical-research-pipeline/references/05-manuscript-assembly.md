# Word / PDF 成稿组装

## 先跑脚本，再改 Word

`scripts/assemble_manuscript.py` 已经实现了下面这张表的全部排版项（三线表、行不跨页、表头重复、图题不可分页、中西文字体、按字符的首行缩进、页脚页码）。**能用脚本就用脚本**：手打一次表，表里的 N 和正文的 N 从此各有一份，`verify_numbers.py` 之后能查出来的只是"两个数字不一致"，查不出哪个对。

```bash
python scripts/assemble_manuscript.py --spec manuscript.json --out output/manuscript.docx \
  --numbers output/manuscript_numbers.csv   # 你写的 key,value 表（{key} 从这取）
```

它同时产出 `<out>_numbers.csv`（本文档实际印出的每个 N，喂给 `verify_numbers.py --numbers`）与 `figure_map.json`（给 `export_pdf_hires.py` 回填原图用）。注意区分：`--numbers` 是**输入**（你提供的 key,value 表），`<out>_numbers.csv` 是**输出**（脚本记录了实际印出的值）。下面的排版参数是**脚本的默认值**，改 `style` 段即可覆盖。

## 版式参数

| 项目 | 建议 |
|---|---|
| 页面 | A4，上下 2.54 cm，左右 3.17 cm 或按期刊 |
| 正文 | 宋体小四，1.5 倍行距，首行缩进 2 字符 |
| 标题 | 黑体/宋体加粗，层级统一 |
| 表题 | 表上方，五号/小五，居中 |
| 图题 | 图下方，五号/小五，居中 |
| 表注/图注 | 更小一号，左对齐或两端对齐 |
| 页码 | 页脚居中 |
| 图表编号 | 图 1、表 1、附图 1；正文首次引用必须同号 |

## 图表与正文同页

Word 默认会把图、图题、图注拆到不同页。设置：

- 图片段落：段前段后 6 pt，居中，`keep_with_next = True`。
- 图题段落：与下段同页，`keep_with_next = True`。
- 图注段落：允许单独留在图下方，但不要与图分离。
- 表格：标题行重复；行禁止跨页断开；表格整体尽量与表题同页。

python-docx 示例：

```python
from docx import Document
from docx.shared import Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH

doc = Document()
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.keep_with_next = True
run = p.add_run()
run.add_picture("fig1.png", width=Cm(15))

cap = doc.add_paragraph("图 1  样本类别结构（N=1,200）")
cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
cap.paragraph_format.keep_with_next = True

note = doc.add_paragraph("注：……")
note.paragraph_format.space_after = Cm(0.3)
```

如果图注必须跟图同页，而图又很高，宁可让上一页留白，也不要把图题甩到下一页。排版优先级：**图 + 图题 + 图注完整 > 页面填满**。

## 表格

- 三线表：顶线、表头下线、底线；不要竖线。
- 表头重复：`tblHeader`。
- 行不跨页：`cantSplit`——**python-docx 没有这个 API**，必须手写 OOXML：

```python
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

def no_split(row):
    trPr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:cantSplit")
    trPr.append(el)
```

- 整表不跨页更省事的做法：读代码前先想清楚——`keep_with_next` 加在**表格单元格**上 Word 会忽略（改了半天 PDF 字节不变）；真正有用的是给**表题段落**设 `keep_with_next = True`，并让短表整体不跨页（除最后一行外全部 `keep_with_next`）。长表宁可用 `cantSplit` 允许跨页，也别留下"表题+表头孤行在页底"。
- 数字右对齐/小数点对齐；文字左对齐。
- 括号里的 CI 用 en dash `–`，不用 hyphen。
- 显著性星号在表注解释：`*** p<0.001，** p<0.01，* p<0.05`。
- 每个模型单独 N；不要只写一个总 N。

## 正文数字一致性

最容易出错的地方：

- 摘要写 N=1,200，正文写 1,260，表写 1,000。
- 图注写 N=880，正文写 900。
- 百分比四舍五入后合计不等于 100%。
- 正文说“最高”，图里其实是“最低”。

做法：

1. 所有数字从同一张 `numbers.csv` 取，不手打。**现在有生成者了**：`assemble_manuscript.py` 会把文档里实际印出的每个 N 写成 `manuscript_numbers.csv`（键 `table1_n`/`fig1_n`），正文用 `{table1_n}` 这样的占位符引用它，取不到键就直接报错——`numbers.csv` 不再是"约定，自己想办法"。
2. 摘要、正文、表、图注、附录交叉核对。
3. 每个 N 后面注明口径：描述样本 / 模型样本 / 有效样本。
4. 百分比保留一位小数；合计偏差在表注说明"因四舍五入不等于 100%"。
5. 正文里的定性判断（"上升/下降/最高"）必须由数据现算，不能凭印象写；数字变了方向也会变。

## Word → PDF

推荐流程：

```bash
python scripts/export_pdf_hires.py \
  --docx "output/manuscript.docx" \
  --out-pdf "output/manuscript.pdf" \
  --figure-map "output/figure_map.json"
```

`figure_map.json`：

```json
[
  {"tag": "图1", "title": "样本类别结构", "image": "figures/fig1_category_structure.png"},
  {"tag": "图2", "title": "处理阶段与结果发生率", "image": "figures/fig2_stage_outcome.png"}
]
```

脚本会：

1. 用 Word 导出 PDF（**依赖 Windows + Microsoft Word + pywin32**：内部走 `win32com.client.DispatchEx("Word.Application")` 与 `SaveAs2(FileFormat=17)`，不需要 LibreOffice）。
2. 按“图号 + 图题”定位页面；tag 有数字边界（`图1` 不会命中 `图10`），并优先选择图题在行首的页面。
3. 用原图替换 Word 压缩后的图。
4. **替换后清理内容流**（`page.clean_contents(sanitize=True)`）并以 `garbage=4` 保存——少了这一步，旧的低分辨率位图仍挂在 `/Resources` 里：实测同一文档会从 16 张图变成 32 张、体积从 5.3 MB 涨到 9.8 MB，成品里同时存在 600 dpi 与 200 dpi 两份位图。
5. 按版面尺寸算有效 dpi 并写进 `*_export_report.json`；低于 `--min-dpi`（默认 600）返回 2，`--allow-low` 可放行。

`--no-backfill` 只导出不回填，用于对比低分辨率问题；`--raw-pdf` 可保留 Word 原始导出件，但不能与 `--out-pdf` 相同。Word 未安装或导出失败会返回 2，不会留下半成品。

要求：

- 图号与图题在 PDF 文本层可检索；如果图题是图片，脚本找不到。
- 同一页有多张图时，脚本按图注位置就近匹配图片；图题必须可检索，复杂版面仍建议一页一图。
- 导出后必须人工翻一遍，确认没有错位、遮挡、图注分离。

## 终稿检查

- 封面/标题/作者/摘要/关键词齐全。
- 目录页码与实际页码一致。
- 图、表、附录编号连续。
- 所有图有图题和图注；所有表有表题和表注。
- 没有“见图 X”但图 X 不存在。
- 参考文献格式统一。
- PDF 内嵌字体；中文没有乱码。
- PDF 内嵌图按版面尺寸折算的**有效 dpi ≥600**（15 cm 宽 = 3543 px；3000 px 只有 508 dpi）。
- 文件命名包含版本/日期，避免“最终版最终版2”。
