"""
CSV 文件读写和解析模块
负责处理 MetaboAnalyst 的 name mapping 输出文件
"""

import csv
from typing import List, Dict
from pathlib import Path


class CSVHandler:
    """处理CSV文件的读写操作"""
    
    def __init__(self, file_path: str):
        """
        初始化CSV处理器
        
        Args:
            file_path: CSV文件路径
        """
        self.file_path = Path(file_path)
        self.data: List[Dict] = []
        self.headers: List[str] = []
    
    def read_csv(self) -> List[Dict]:
        """
        读取CSV文件
        
        Returns:
            包含所有行数据的字典列表
        """
        if not self.file_path.exists():
            raise FileNotFoundError(f"文件不存在: {self.file_path}")
        
        with open(self.file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            self.headers = reader.fieldnames
            self.data = list(reader)
        
        return self.data
    
    def filter_unmatched(self) -> List[Dict]:
        """
        筛选出未匹配的代谢物（Comment = 0）
        
        Returns:
            未匹配代谢物的列表
        """
        if not self.data:
            self.read_csv()
        
        # 筛选 Comment=0 的行（全NA，未匹配）
        unmatched = [row for row in self.data if row.get('Comment', '').strip() == '0']
        
        print(f"总共 {len(self.data)} 条记录，其中 {len(unmatched)} 条未匹配")
        
        return unmatched
    
    def update_row(self, query_name: str, matched_data: Dict):
        """
        更新某一行的匹配结果
        
        Args:
            query_name: Query字段的值（代谢物名称）
            matched_data: 包含 Match, HMDB, PubChem, KEGG, SMILES 的字典
        """
        for row in self.data:
            if row['Query'] == query_name:
                row['Match'] = matched_data.get('Match', 'NA')
                row['HMDB'] = matched_data.get('HMDB', 'NA')
                row['PubChem'] = matched_data.get('PubChem', 'NA')
                row['KEGG'] = matched_data.get('KEGG', 'NA')
                row['SMILES'] = matched_data.get('SMILES', 'NA')
                row['Comment'] = '1'  # 标记为已匹配
                break
    
    def write_csv(self, output_path: str = None):
        """
        将更新后的数据写入CSV文件
        
        Args:
            output_path: 输出文件路径，如果为None则覆盖原文件
        """
        if output_path is None:
            output_path = self.file_path
        else:
            output_path = Path(output_path)
        
        with open(output_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=self.headers)
            writer.writeheader()
            writer.writerows(self.data)
        
        print(f"已保存到: {output_path}")
    
    def get_query_names(self) -> List[str]:
        """
        获取所有未匹配代谢物的名称列表
        
        Returns:
            代谢物名称列表
        """
        unmatched = self.filter_unmatched()
        return [row['Query'] for row in unmatched]
