"""
化学数据库API客户端
负责查询 PubChem 和 HMDB 数据库，获取候选匹配物质
"""

import requests
import time
from typing import List, Dict, Optional
from config import PUBCHEM_BASE_URL, HMDB_BASE_URL, REQUEST_TIMEOUT, MAX_CANDIDATES


class DatabaseClient:
    """化学数据库查询客户端"""
    
    def __init__(self):
        """初始化数据库客户端"""
        self.session = requests.Session()
        self.cache = {}  # 简单的内存缓存
    
    def search_pubchem(self, compound_name: str) -> List[Dict]:
        """
        在PubChem数据库中搜索化合物
        
        Args:
            compound_name: 化合物名称
            
        Returns:
            候选化合物列表，每个包含 name, cid, smiles 等信息
        """
        # 检查缓存
        cache_key = f"pubchem_{compound_name}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        candidates = []
        
        try:
            # Step 1: 搜索化合物名称，获取CID列表
            search_url = f"{PUBCHEM_BASE_URL}/compound/name/{compound_name}/cids/JSON"
            response = self.session.get(search_url, timeout=REQUEST_TIMEOUT)
            
            if response.status_code == 200:
                data = response.json()
                cids = data.get('IdentifierList', {}).get('CID', [])
                
                # 限制候选数量
                cids = cids[:MAX_CANDIDATES]
                
                # Step 2: 获取每个CID的详细信息
                for cid in cids:
                    compound_info = self._get_pubchem_compound_info(cid)
                    if compound_info:
                        candidates.append(compound_info)
                    
                    time.sleep(0.2)  # 避免请求过快
            
        except Exception as e:
            print(f"PubChem查询失败 [{compound_name}]: {str(e)}")
        
        # 缓存结果
        self.cache[cache_key] = candidates
        return candidates
    
    def _get_pubchem_compound_info(self, cid: int) -> Optional[Dict]:
        """
        获取PubChem化合物的详细信息
        
        Args:
            cid: PubChem CID
            
        Returns:
            化合物信息字典
        """
        try:
            # 获取化合物属性
            props_url = f"{PUBCHEM_BASE_URL}/compound/cid/{cid}/property/IUPACName,CanonicalSMILES/JSON"
            response = self.session.get(props_url, timeout=REQUEST_TIMEOUT)
            
            if response.status_code == 200:
                data = response.json()
                properties = data.get('PropertyTable', {}).get('Properties', [{}])[0]
                
                return {
                    'source': 'PubChem',
                    'name': properties.get('IUPACName', 'Unknown'),
                    'pubchem_cid': str(cid),
                    'smiles': properties.get('CanonicalSMILES', 'NA'),
                    'hmdb': 'NA',  # PubChem结果没有HMDB
                    'kegg': 'NA'   # PubChem结果没有KEGG
                }
        
        except Exception as e:
            print(f"获取PubChem化合物信息失败 [CID={cid}]: {str(e)}")
            return None
    
    def search_hmdb(self, compound_name: str) -> List[Dict]:
        """
        在HMDB数据库中搜索化合物
        
        Args:
            compound_name: 化合物名称
            
        Returns:
            候选化合物列表
        """
        # 检查缓存
        cache_key = f"hmdb_{compound_name}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        candidates = []
        
        try:
            # HMDB的搜索API（简化版，实际可能需要爬虫或使用下载的数据文件）
            # 这里先返回空列表，Phase 2 可以增强
            # 实际应用中可以：
            # 1. 使用HMDB下载的XML/CSV数据文件进行本地搜索
            # 2. 或者使用网页爬虫（需要遵守HMDB使用条款）
            print(f"HMDB查询暂未实现，跳过: {compound_name}")
            
        except Exception as e:
            print(f"HMDB查询失败 [{compound_name}]: {str(e)}")
        
        # 缓存结果
        self.cache[cache_key] = candidates
        return candidates
    
    def search_all(self, compound_name: str) -> List[Dict]:
        """
        在所有数据库中搜索化合物
        
        Args:
            compound_name: 化合物名称
            
        Returns:
            合并后的候选化合物列表
        """
        print(f"\n正在搜索: {compound_name}")
        
        candidates = []
        
        # PubChem搜索
        pubchem_results = self.search_pubchem(compound_name)
        candidates.extend(pubchem_results)
        print(f"  - PubChem: 找到 {len(pubchem_results)} 个候选")
        
        # HMDB搜索（Phase 1暂未实现）
        hmdb_results = self.search_hmdb(compound_name)
        candidates.extend(hmdb_results)
        print(f"  - HMDB: 找到 {len(hmdb_results)} 个候选")
        
        return candidates
    
    def clear_cache(self):
        """清空缓存"""
        self.cache.clear()
