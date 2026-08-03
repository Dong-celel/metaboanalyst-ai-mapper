# MetaboAnalyst 自动匹配工具 - 使用说明

## 🎯 功能简介

这个工具可以**自动化MetaboAnalyst的候选选择过程**：

1. 自动打开MetaboAnalyst网站
2. 对每个未匹配物质点击"View"
3. 从弹窗中提取候选列表
4. 使用AI选择最佳候选
5. 自动点击确认

**100%兼容MetaboAnalyst**，因为候选直接来自官方网站！

---

## 📦 安装依赖

### 步骤1：安装Python包
```bash
pip install -r requirements.txt
```

### 步骤2：安装ChromeDriver

**方法A：自动安装（推荐）**
```bash
pip install webdriver-manager
```
程序会自动下载对应版本的ChromeDriver

**方法B：手动安装**
1. 查看你的Chrome版本（chrome://version）
2. 下载对应的ChromeDriver：https://chromedriver.chromium.org/
3. 放到系统PATH中

---

## 🚀 使用方法

### 基本用法

```bash
python metaboanalyst_auto_matcher.py name_map.csv
```

**流程**：
1. 程序会启动Chrome浏览器
2. 提示你手动上传CSV到MetaboAnalyst
3. 等待你按回车后，自动开始匹配
4. 完成后在MetaboAnalyst下载结果

---

### 完整流程示例

#### 步骤1：准备CSV文件
```
name_map.csv （MetaboAnalyst导出的文件）
```

#### 步骤2：运行工具
```bash
python metaboanalyst_auto_matcher.py name_map.csv --pathway "Glycolysis"
```

#### 步骤3：按提示操作
```
MetaboAnalyst 自动匹配流程
============================================================

找到 45 个未匹配物质

⚠️  重要提示:
  1. 请手动打开 https://www.metaboanalyst.ca
  2. 上传你的CSV文件
  3. 等待Name Mapping完成
  4. 准备好后，按回车继续...

按回车继续 > _
```

#### 步骤4：等待自动匹配
```
[1/45] 处理: Cryptopic Acid H
  ✓ 弹窗已打开
  ✓ 找到 5 个候选
  ✓ AI选择: Ethyl crotonate (来源: MetaboAnalyst)
  ✓ 已选择: Ethyl crotonate

[2/45] 处理: Gelomulide I
  ✓ 弹窗已打开
  ✓ 找到 3 个候选
  ✓ AI选择: Gelomulide (来源: MetaboAnalyst)
  ✓ 已选择: Gelomulide

...
```

#### 步骤5：下载结果
在MetaboAnalyst页面下载更新后的CSV

---

## 🎛️ 命令行参数

### 完整参数列表

```bash
python metaboanalyst_auto_matcher.py [-h] [--pathway PATHWAY] 
                                     [--compounds COMPOUNDS] 
                                     [--headless] 
                                     input

必需参数:
  input                 输入CSV文件路径

可选参数:
  -h, --help           显示帮助信息
  --pathway PATHWAY    代谢通路提示（提高AI选择准确性）
  --compounds COMPOUNDS 预期物质列表，逗号分隔
  --headless          无头模式（不显示浏览器窗口）
```

### 使用示例

**示例1：基本匹配**
```bash
python metaboanalyst_auto_matcher.py name_map.csv
```

**示例2：提供通路提示**
```bash
python metaboanalyst_auto_matcher.py name_map.csv --pathway "TCA Cycle"
```

**示例3：提供预期物质**
```bash
python metaboanalyst_auto_matcher.py name_map.csv \
  --pathway "Glycolysis" \
  --compounds "Glucose,Pyruvate,Lactate"
```

**示例4：无头模式（后台运行）**
```bash
python metaboanalyst_auto_matcher.py name_map.csv --headless
```

---

## 🔧 工作原理

### 技术架构

```
CSV文件
  ↓
读取未匹配物质 (Comment=0)
  ↓
Selenium打开浏览器
  ↓
用户手动上传CSV到MetaboAnalyst
  ↓
程序接管：
  对每个物质：
    1. 点击View按钮
    2. 定位弹窗元素
    3. 解析候选列表（Name, HMDB, PubChem, KEGG）
    4. 传给DeepSeek AI
    5. AI选择最佳匹配
    6. 程序点击对应单选框
    7. 程序点击OK按钮
  ↓
完成！在网页下载结果
```

### 关键模块

1. **metaboanalyst_client.py** - Selenium自动化
   - 控制浏览器
   - 定位页面元素
   - 解析弹窗内容

2. **ai_matcher.py** - AI智能选择
   - DeepSeek API调用
   - 从候选中选择最佳匹配

3. **metaboanalyst_auto_matcher.py** - 主流程
   - 整合所有模块
   - 完整自动化流程

---

## ⚠️ 注意事项

### 限制和约束

1. **需要手动上传CSV**
   - 目前需要手动上传到MetaboAnalyst
   - 未来版本会实现完全自动化

2. **需要稳定网络**
   - 访问MetaboAnalyst网站
   - 调用DeepSeek API

3. **处理速度**
   - 每个物质约5-10秒
   - 45个物质约5-8分钟

4. **浏览器要求**
   - 需要安装Chrome浏览器
   - 需要ChromeDriver

---

## 🐛 故障排除

### 问题1：找不到ChromeDriver
```
错误: 'chromedriver' executable needs to be in PATH
```

**解决**：
```bash
pip install webdriver-manager
```

---

### 问题2：弹窗定位失败
```
错误: 未找到元素: .ui-dialog
```

**原因**：MetaboAnalyst网页结构可能变化

**解决**：
1. 查看metaboanalyst_client.py
2. 更新元素选择器
3. 或截图发给我，我来修复

---

### 问题3：AI选择失败
```
错误: AI无法确定最佳匹配
```

**原因**：候选列表质量差，AI无法判断

**解决**：
- 提供 `--pathway` 参数
- 提供 `--compounds` 参数
- 人工介入处理该物质

---

## 📊 输出结果

### 控制台输出

```
==================================================================
处理完成
==================================================================
成功匹配: 38
匹配失败: 7

请在MetaboAnalyst页面上:
  1. 检查匹配结果
  2. 下载更新后的CSV
==================================================================
```

### 在MetaboAnalyst查看

1. 打开MetaboAnalyst页面
2. 查看Name Mapping结果
3. 原来 `Comment=0` 的行应该变成 `1`
4. 下载最终的CSV文件

---

## 🎯 优势总结

### vs 原来的方案（PubChem搜索）

| 特性 | 原方案 | 新方案(MetaboAnalyst) |
|------|--------|---------------------|
| 兼容性 | 不确定 | ✅ 100%兼容 |
| ID映射 | 需要复杂映射 | ✅ 自动包含 |
| 候选来源 | PubChem | ✅ MetaboAnalyst官方 |
| View可见性 | ❓ 不确定 | ✅ 保证可见 |
| 准确性 | 中等 | ✅ 高 |

---

## 🚀 下一步计划

### Phase 1 (当前)
- ✅ Selenium自动化
- ✅ 弹窗解析
- ✅ AI选择
- ✅ 自动确认

### Phase 2 (计划中)
- ⬜ 完全自动上传CSV
- ⬜ 批量处理优化
- ⬜ 错误重试机制
- ⬜ 详细日志输出

---

## 💡 使用技巧

1. **首次测试建议**：不用 `--headless`，观察浏览器操作
2. **大批量处理**：使用 `--headless` 提高速度
3. **提供通路信息**：显著提高准确性
4. **分批处理**：如果物质太多，可以分几次运行

---

准备好了吗？开始使用吧！

```bash
pip install -r requirements.txt
python metaboanalyst_auto_matcher.py name_map.csv
```
# ⚠️ 历史说明

本文记录的是旧版 Selenium 原型，不再对应当前代码。请使用 [README.md](README.md) 中的 Playwright NameMap View 流程。
