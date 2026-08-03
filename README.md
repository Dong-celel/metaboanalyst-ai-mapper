# MetaboAnalyst NameMap View 自动化

这是一个供内部人员在 Windows 本机运行的 Python 工具。它优先接收
MetaboAnalyst 导出的 `name_map.csv`，只把 `Comment=0` 的 Query 上传到
Pathway Analysis，然后逐行打开正确的 `View`、读取网站候选并按客户研究目标自动选择。

网站 Name check 是最终判据。程序不会因为某个名称能在 PubChem 查到，就直接把
橙色行改成已匹配；只有网站 View 中实际存在该候选、选择后对应行确实更新，才记为
验证成功。

## 安装

建议使用 Python 3.11 或更新版本：

```powershell
python -m pip install -r requirements.txt
```

默认打开电脑中已经安装的可见 Chrome。若电脑没有 Chrome，可安装 Playwright 自带
Chromium：

```powershell
python -m playwright install chromium
```

DeepSeek 是可选项。不要把密钥写进代码或配置文件；只在当前终端设置环境变量：

```powershell
$env:DEEPSEEK_API_KEY="新生成的密钥"
```

默认模型为 `deepseek-v4-pro`，并启用 `reasoning_effort=high` 和 thinking。需要临时切换时可设置
`DEEPSEEK_MODEL`、`DEEPSEEK_REASONING_EFFORT` 或 `DEEPSEEK_THINKING_ENABLED` 环境变量。

也可以让程序在每次运行开始时隐藏输入，密钥只存在于本次 Python 进程中：

```powershell
python main.py run name_map.csv --ask-deepseek-key --no-preflight --max-items 20 --browser-network direct
```

如果旧版本代码中使用过硬编码密钥，应先在 DeepSeek 控制台撤销并重新生成。没有设置
密钥时程序仍可正常工作，但非精确匹配只会写入内部复核清单，不会自动提交。

## 推荐用法：直接处理 name_map.csv

最简单的文件夹用法：

1. 把唯一一个待处理 CSV/TXT 放进 `input/`。
2. 双击 `input/开始处理.bat`。
3. 从 `output/<run_id>/` 取走处理后的 CSV 和 `review_queue.csv`。

脚本会一次性询问目标物质、物质类别、目标通路和客户偏好尺度。多个目标使用英文或中文
分号分隔；化学名称中的逗号会被保留。默认尺度是 `80/100`，随后自动处理并直接生成
结果，不再逐项停下来询问。

也可以在项目根目录不带输入路径运行，程序会自动选择 `input/` 中唯一的 CSV/TXT：

```powershell
python main.py run --no-preflight --max-items 20 --browser-network direct --ask-deepseek-key
```

先验证文件：

```powershell
python main.py validate name_map.csv
```

先抽样 50 项，仅扫描并生成审核队列：

```powershell
python main.py run name_map.csv --no-preflight --no-review --max-items 50 --browser-network direct
```

确认抽样结果后，运行完整流程并在终端集中审核：

```powershell
python main.py run name_map.csv --no-preflight --browser-network direct
```

程序在审核阶段显示 Query、候选名称、HMDB/KEGG/PubChem ID、本地分数和 AI
理由。输入候选序号后，程序会重新打开该 Query 自己的 View，重新定位候选、勾选、
点击 OK，并验证网站行更新；输入 `s` 跳过。

发生中断后使用运行目录名继续：

```powershell
python main.py run --resume 20260723-003621-9bd71541 --no-preflight --browser-network direct
```

每项处理后都会立即写入检查点。恢复时会重新上传 `Comment=0` 的 Query，重放已经验证
的选择，但不会再次调用 AI 判断已有记录。

## 浓度表输入（兼容路径）

也可以直接传入浓度表：

```powershell
python main.py run Metabolite_data.csv --no-preflight --browser-network direct
```

该表必须满足：第一列为唯一代谢物名称，第二行为分组标签，样本列名称唯一且全部为有限
数值。程序按 `Concentration Table / Compound Name / Discrete / Samples in columns`
上传。当前更稳定、更快的路线仍是先取得 `name_map.csv`，再只处理 View。

## 输出

每次新运行在 `runs/<run_id>/` 下生成：

- `mapping_before.csv`：本次上传后的网站初始映射。
- `mapping_final.csv`：合并回原始 `name_map.csv` 的最终映射；原有 `Comment=1`
  行保持不变。
- `mapping_website_final.csv`：仅包含本次上传 Query 的网站最终状态（map list 输入时）。
- `review_queue.csv`：待人工处理、跳过或无候选项目及其候选。
- `goal_coverage.csv`：目标覆盖情况、AI置信度、身份可信度、目标符合度和综合分。
- `audit.jsonl`：候选、评分、AI 判断、人工决定和验证事件。
- `state.json`：断点恢复状态，不含 API 密钥。
- `Metabolite_data_standardized.csv`：浓度表输入时生成，只替换网站已确认的首列名称。

原始输入文件始终只读。DeepSeek 只接收 Query、网站候选名称和数据库 ID，不接收浓度、
样本名或分组信息。

另外，用户需要取走的结果会复制到 `output/<run_id>/`：

- `<原文件名>_processed.csv`：NameMap 最终结果。
- `<原文件名>_standardized.csv`：浓度表标准化结果。
- `review_queue.csv`：待复核项目。
- `goal_coverage.csv`：客户目标覆盖及解释性评分。
- `matching_explanation.txt`：客户可读的偏好尺度和置信度说明。

## 研究目标与偏好尺度

交互式运行会询问三类目标。命令行也可以直接指定，同一参数可重复使用：

```powershell
python main.py run name_map.csv --target-compound "Glucose" `
  --target-class "Carbohydrates" --target-pathway "Glycolysis" `
  --preference-strength 80 --no-review --close-browser
```

- `0`：只采用原有严格身份匹配规则。
- `50`：名称身份和客户研究目标并重。
- `80`：默认，明显偏向目标并自动完成大部分可判断项目。
- `100`：最大程度按照客户目标自动选择；明确结构警告也不再强制阻止自动提交。

无论尺度如何，程序只会从 MetaboAnalyst 当前 Query 的 `View` 候选中选择，不会让 AI
凭空创造物质。目标设置和尺度保存在运行状态中，恢复运行时不能中途改变。

商业服务默认只使用 MetaboAnalyst 返回的 KEGG ID，报告中标为 `id_only`。KEGG REST API
官方注明仅供符合条件的学术用户使用；只有已经取得适当授权时才应增加
`--enable-kegg-api`，此时程序会查询具体参考通路并标为 `linked`。

## 常用参数

- `--no-preflight`：跳过官方 `mapcompounds` 预检，直接处理网站 View。
- `--no-review`：扫描后写审核队列，不在本次运行中询问选择。
- `--ask-deepseek-key`：在终端隐藏输入 DeepSeek 密钥；不写入文件或命令历史。
- `--ask-research-goal`：运行开始时一次性询问目标物质、类别、通路和偏好尺度。
- `--target-compound/--target-class/--target-pathway`：非交互式提供客户研究目标。
- `--preference-strength 0-100`：调整严格身份与客户目标之间的权重，默认 `80`。
- `--enable-kegg-api`：在线验证 KEGG 具体通路；仅在相应用途已取得许可时启用。
- `--max-items N`：本次最多检查 N 个尚未处理的橙色项目。
- `--close-browser`：完成后立即关闭浏览器；默认停留在 Name check 等待操作者。
- `--browser-network direct`：Chrome 不继承系统代理，适合当前 VPN 会导致网站超时的环境。
- `--browser-network system`：使用系统网络设置。
- `--browser-timeout 180`：把单次页面等待改为 180 秒。

## 安全策略

未填写研究目标或尺度为 `0` 时，继续使用原有严格阈值。填写目标后，程序根据 `0-100`
尺度连续调整名称、AI身份、目标符合度和 KEGG 通路证据的权重。无候选、AI无效或网站
失败仍会写入内部复核清单。流程不会点击 Proceed，也不会自动运行后续通路分析。

运行测试：

```powershell
python -m pytest
```

真实网站回归默认跳过，避免测试时无意上传；需要时显式设置：

```powershell
$env:RUN_LIVE_METABOANALYST="1"
python -m pytest -m live
```
