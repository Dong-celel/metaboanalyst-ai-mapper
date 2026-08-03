"""
MetaboAnalyst 网站自动化客户端
使用Selenium获取View弹窗中的候选列表
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from typing import List, Dict, Optional
import time


class MetaboAnalystClient:
    """MetaboAnalyst网站自动化客户端"""
    
    def __init__(self, headless: bool = False):
        """
        初始化客户端
        
        Args:
            headless: 是否使用无头模式（不显示浏览器窗口）
        """
        options = webdriver.ChromeOptions()
        if headless:
            options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        
        # 自动安装和使用ChromeDriver
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=options)
        self.wait = WebDriverWait(self.driver, 20)
    
    def get_candidates_for_compound(self, compound_name: str) -> List[Dict]:
        """
        获取某个化合物的候选列表
        
        注意：需要先调用 navigate_to_name_mapping() 并上传CSV
        
        Args:
            compound_name: 化合物名称
            
        Returns:
            候选列表，格式：
            [
                {
                    'name': 'Ethyl crotonate',
                    'hmdb': 'HMDB0039581',
                    'pubchem': '5354263',
                    'kegg': 'NA'
                },
                ...
            ]
        """
        try:
            # 1. 找到对应化合物的View按钮
            # 这里需要根据实际页面结构定位
            # 暂时使用简化逻辑：按文本查找
            
            print(f"  查找物质: {compound_name}")
            
            # 2. 点击View按钮触发弹窗
            # 实际实现需要精确的选择器
            view_links = self.driver.find_elements(By.LINK_TEXT, "View")
            
            if not view_links:
                print(f"  ⚠ 未找到View按钮")
                return []
            
            # 点击第一个View（简化版，实际需要匹配compound_name）
            view_links[0].click()
            
            # 3. 等待弹窗出现
            modal = self.wait.until(
                EC.presence_of_element_located((By.CLASS_NAME, "ui-dialog"))
            )
            
            print(f"  ✓ 弹窗已打开")
            
            # 4. 解析候选列表
            candidates = self._parse_candidate_list(modal)
            
            print(f"  ✓ 找到 {len(candidates)} 个候选")
            
            # 5. 关闭弹窗（点击Cancel）
            cancel_button = modal.find_element(By.XPATH, ".//button[contains(text(), 'Cancel')]")
            cancel_button.click()
            
            time.sleep(0.5)
            
            return candidates
            
        except TimeoutException:
            print(f"  ⚠ 等待弹窗超时")
            return []
        except Exception as e:
            print(f"  ❌ 获取候选失败: {str(e)}")
            return []
    
    def _parse_candidate_list(self, modal_element) -> List[Dict]:
        """
        解析弹窗中的候选列表
        
        Args:
            modal_element: 弹窗的WebElement
            
        Returns:
            候选列表
        """
        candidates = []
        
        try:
            # 查找候选列表的容器
            # 根据截图，候选是在一个表格或列表中
            
            # 方法1: 尝试找表格行
            rows = modal_element.find_elements(By.TAG_NAME, "tr")
            
            if rows:
                # 跳过表头
                for row in rows[1:]:
                    cells = row.find_elements(By.TAG_NAME, "td")
                    
                    if len(cells) >= 4:
                        # 提取单选框和文本
                        checkbox = cells[0].find_element(By.TAG_NAME, "input")
                        
                        name = cells[1].text.strip()
                        hmdb = cells[2].text.strip()
                        pubchem = cells[3].text.strip()
                        kegg = cells[4].text.strip() if len(cells) > 4 else "NA"
                        
                        # 跳过"None of the above"
                        if "None" in name:
                            continue
                        
                        candidate = {
                            'name': name,
                            'hmdb': hmdb if hmdb else 'NA',
                            'pubchem': pubchem if pubchem else 'NA',
                            'kegg': kegg if kegg else 'NA',
                            'checkbox_element': checkbox  # 保存用于后续选择
                        }
                        
                        candidates.append(candidate)
            
            else:
                # 方法2: 如果不是表格，尝试其他结构
                # 根据实际HTML结构调整
                pass
            
        except Exception as e:
            print(f"  ⚠ 解析候选列表失败: {str(e)}")
        
        return candidates
    
    def select_candidate(self, candidate: Dict) -> bool:
        """
        在弹窗中选择某个候选并确认
        
        Args:
            candidate: 候选字典（必须包含checkbox_element）
            
        Returns:
            是否成功
        """
        try:
            # 点击单选框
            checkbox = candidate.get('checkbox_element')
            if checkbox:
                checkbox.click()
                time.sleep(0.3)
            
            # 点击OK按钮
            ok_button = self.driver.find_element(
                By.XPATH, 
                "//button[contains(text(), 'OK') or contains(@value, 'OK')]"
            )
            ok_button.click()
            
            time.sleep(0.5)
            
            print(f"  ✓ 已选择: {candidate['name']}")
            return True
            
        except Exception as e:
            print(f"  ❌ 选择候选失败: {str(e)}")
            return False
    
    def close(self):
        """关闭浏览器"""
        if self.driver:
            self.driver.quit()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# 使用示例
if __name__ == '__main__':
    with MetaboAnalystClient(headless=False) as client:
        # 这只是示例，实际使用需要先导航到页面并上传CSV
        candidates = client.get_candidates_for_compound("Cryptopic Acid H")
        
        for c in candidates:
            print(f"{c['name']} - HMDB:{c['hmdb']} PubChem:{c['pubchem']}")
