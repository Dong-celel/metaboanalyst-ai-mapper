# 获取MetaboAnalyst View内容的技术方案

## 🎯 目标
获取MetaboAnalyst网站中点击"View"按钮后弹出的候选物质列表

---

## 📋 方案总结

根据技术调研，有以下几种方案：

### 方案优先级
1. **方案1: 浏览器开发者工具手动分析** ⭐⭐⭐ (推荐首先尝试)
2. **方案2: Selenium Wire拦截API请求** ⭐⭐⭐ (最佳自动化方案)
3. **方案3: Selenium + 页面解析** ⭐⭐ (备选)
4. **方案4: 直接逆向API** ⭐ (如果有公开API)

---

## 🔍 方案1: 浏览器开发者工具分析（推荐首先做）

### 操作步骤

**步骤1: 打开开发者工具**
```
1. 访问 https://www.metaboanalyst.ca
2. 上传你的CSV文件
3. 按 F12 打开开发者工具
4. 切换到 "Network" 标签
5. 勾选 "Preserve log"（保留日志）
```

**步骤2: 触发View操作**
```
6. 在 Network 中筛选 "Fetch/XHR" 或 "All"
7. 点击某个未匹配物质的 "View" 按钮
8. 观察 Network 中新出现的请求
```

**步骤3: 分析请求**
```
9. 找到返回候选列表的请求（通常是JSON格式）
10. 查看请求的：
    - URL (完整地址)
    - Method (GET/POST)
    - Headers (需要哪些头部)
    - Payload (发送了什么数据)
    - Response (返回的候选列表JSON)
```

**步骤4: 提取信息给我**
```
将以下信息截图或复制给我：
- 请求URL
- 请求方法
- 请求头（Headers）
- 请求参数（Payload）
- 响应内容（Response）的前几行
```

---

## 🔧 方案2: Selenium Wire拦截（自动化方案）

如果手动分析找到了API，可以用这个方案自动化。

### 技术原理

**Selenium Wire** 是 Selenium 的扩展，可以拦截浏览器的所有网络请求。

### 安装依赖

```bash
pip install selenium-wire selenium
```

### 实现代码

```python
from seleniumwire import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import json

class MetaboAnalystScraper:
    """使用Selenium Wire获取MetaboAnalyst的候选列表"""
    
    def __init__(self):
        # 配置Selenium Wire
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')  # 无头模式
        self.driver = webdriver.Chrome(options=options)
    
    def get_candidates(self, compound_name: str) -> list:
        """
        获取某个化合物的候选列表
        
        Args:
            compound_name: 化合物名称
            
        Returns:
            候选列表
        """
        # 1. 上传CSV或输入化合物名称
        # 这里需要根据实际网站操作
        
        # 2. 清空之前的请求记录
        del self.driver.requests
        
        # 3. 点击View按钮
        view_button = self.driver.find_element(By.LINK_TEXT, "View")
        view_button.click()
        
        # 4. 等待API请求完成
        import time
        time.sleep(2)
        
        # 5. 拦截包含候选列表的请求
        for request in self.driver.requests:
            # 根据手动分析的URL特征过滤
            if 'candidate' in request.url or 'match' in request.url:
                if request.response:
                    # 解析JSON响应
                    try:
                        candidates = json.loads(request.response.body)
                        return candidates
                    except:
                        pass
        
        return []
    
    def close(self):
        self.driver.quit()


# 使用示例
scraper = MetaboAnalystScraper()
candidates = scraper.get_candidates("Gelomulide I")
print(candidates)
scraper.close()
```

### 优点
✅ 完全自动化
✅ 可以拦截所有网络请求
✅ 不需要知道确切的API端点

### 缺点
⚠️ 需要浏览器驱动（ChromeDriver）
⚠️ 速度相对较慢
⚠️ 依赖网站结构

---

## 🌐 方案3: Selenium + 页面解析

如果API是动态生成的或找不到，直接解析弹出的DOM元素。

### 实现代码

```python
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def get_candidates_from_modal(driver, compound_name):
    """从弹出的Modal中提取候选列表"""
    
    # 1. 点击View按钮
    view_button = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.LINK_TEXT, "View"))
    )
    view_button.click()
    
    # 2. 等待Modal弹出
    modal = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CLASS_NAME, "modal-content"))
        # 实际class名称需要查看网页源码
    )
    
    # 3. 解析候选列表
    candidates = []
    
    # 假设候选在表格中
    rows = modal.find_elements(By.TAG_NAME, "tr")
    
    for row in rows[1:]:  # 跳过表头
        cells = row.find_elements(By.TAG_NAME, "td")
        if len(cells) >= 4:
            candidate = {
                'name': cells[0].text,
                'hmdb': cells[1].text,
                'pubchem': cells[2].text,
                'kegg': cells[3].text
            }
            candidates.append(candidate)
    
    return candidates
```

### 优点
✅ 不依赖API
✅ 适用于任何动态内容

### 缺点
⚠️ 需要分析页面结构
⚠️ 页面结构变化会失效
⚠️ 需要处理各种等待和异常

---

## 🔑 方案4: 直接API调用（理想情况）

如果MetaboAnalyst有公开API（通过方案1发现），可以直接调用。

### 示例代码（假设找到了API）

```python
import requests

def get_metaboanalyst_candidates(compound_name: str) -> list:
    """
    直接调用MetaboAnalyst API获取候选
    
    注意：这个URL是假设的，需要通过方案1确认实际URL
    """
    
    # 假设的API端点
    url = "https://www.metaboanalyst.ca/api/compound/match"
    
    # 请求参数
    payload = {
        "query": compound_name,
        "database": "all"  # HMDB + KEGG + PubChem
    }
    
    # 请求头
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }
    
    # 发送请求
    response = requests.post(url, json=payload, headers=headers)
    
    if response.status_code == 200:
        return response.json()
    else:
        return []


# 使用
candidates = get_metaboanalyst_candidates("Gelomulide I")
for c in candidates:
    print(f"{c['name']} - HMDB:{c['hmdb']} PubChem:{c['pubchem']}")
```

### 优点
✅ 最快速
✅ 最稳定
✅ 无需浏览器

### 缺点
⚠️ 需要找到API（可能不存在）
⚠️ 可能需要认证
⚠️ 可能有请求频率限制

---

## 📊 方案对比

| 方案 | 难度 | 速度 | 稳定性 | 推荐度 |
|------|------|------|--------|--------|
| 方案1: 手动分析 | 简单 | - | - | ⭐⭐⭐⭐⭐ (首选) |
| 方案2: Selenium Wire | 中等 | 慢 | 中 | ⭐⭐⭐⭐ |
| 方案3: Selenium解析 | 中等 | 慢 | 低 | ⭐⭐⭐ |
| 方案4: 直接API | 简单 | 快 | 高 | ⭐⭐⭐⭐⭐ (如果有) |

---

## 🎯 推荐实施步骤

### 第一步：手动分析（今天做）
1. 运行 `python 探测_metaboanalyst_api.py`（自动探测）
2. 如果自动探测失败，手动使用浏览器开发者工具
3. 将找到的信息发给我

### 第二步：选择方案（根据第一步结果）
- **如果找到API** → 实现方案4（最佳）
- **如果没有API** → 实现方案2（Selenium Wire）

### 第三步：集成到现有代码
```python
# 修改 database_client.py
class DatabaseClient:
    def __init__(self):
        self.metaboanalyst = MetaboAnalystClient()  # 新增
    
    def search_all(self, compound_name: str):
        # 优先使用MetaboAnalyst候选
        candidates = self.metaboanalyst.get_candidates(compound_name)
        
        if candidates:
            return candidates
        else:
            # 备选：使用PubChem
            return self.search_pubchem(compound_name)
```

---

## 💻 需要的依赖

```bash
# 方案2和方案3需要
pip install selenium-wire selenium webdriver-manager

# 或者只用标准Selenium（方案3）
pip install selenium webdriver-manager
```

---

## 📝 下一步行动

1. **立即运行探测脚本**：
   ```bash
   python 探测_metaboanalyst_api.py
   ```

2. **如果探测失败，手动操作**：
   - 打开MetaboAnalyst
   - 按F12
   - 点击View
   - 截图Network标签
   - 发给我分析

3. **我根据结果实现对应方案**

---

准备好了吗？我们可以立即开始测试！
# ⚠️ 历史调研

本文是实现前的 Selenium 方案比较。当前代码已经采用 Python Playwright 并通过真实 View 弹窗回归；操作方法见 [README.md](README.md)。
