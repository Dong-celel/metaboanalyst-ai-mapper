"""
核心匹配逻辑
整合数据库查询和AI匹配，执行完整的匹配流程
"""

from typing import List, Dict, Optional
from .csv_handler import CSVHandler
from .database_client import DatabaseClient
from .ai_matcher import AIMatcher


class MatcherCore:
    """代谢物匹配核心引擎"""
    
    def __init__(self):
        """初始化匹配器"""
        self.db_client = DatabaseClient()
        self.ai_matcher = AIMatcher()
        self.match_results = []  # 记录所有匹配结果
    
    def process_csv(
        self,
        input_csv: str,
        output_csv: str = None,
        pathway_hint: Optional[str] = None,
        expected_compounds: Optional[List[str]] = None
    ) -> Dict:
        """
        处理完整的CSV文件匹配流程
        
        Args:
            input_csv: 输入的CSV文件路径
            output_csv: 输出的CSV文件路径（如果为None则自动生成）
            pathway_hint: 用户提示的代谢通路
            expected_compounds: 用户预期的有效物质列表
            
        Returns:
            匹配统计信息
        """
        print("="*60)
        print("开始代谢物智能匹配")
        print("="*60)
        
        # 1. 读取CSV并筛选未匹配物质
        csv_handler = CSVHandler(input_csv)
        csv_handler.read_csv()
        unmatched_rows = csv_handler.filter_unmatched()
        
        if not unmatched_rows:
            print("\n✓ 所有代谢物都已匹配，无需处理")
            return {
                'total': len(csv_handler.data),
                'unmatched': 0,
                'newly_matched': 0,
                'still_unmatched': 0
            }
        
        # 2. 逐个处理未匹配物质
        newly_matched = 0
        still_unmatched = 0
        
        for i, row in enumerate(unmatched_rows, 1):
            query_name = row['Query']
            print(f"\n[{i}/{len(unmatched_rows)}] 处理: {query_name}")
            
            # 匹配单个代谢物
            match_result = self.match_single_compound(
                query_name,
                pathway_hint=pathway_hint,
                expected_compounds=expected_compounds
            )
            
            # 更新CSV数据
            if match_result:
                csv_handler.update_row(query_name, match_result)
                newly_matched += 1
            else:
                still_unmatched += 1
            
            # 记录结果
            self.match_results.append({
                'query': query_name,
                'matched': match_result is not None,
                'result': match_result
            })
        
        # 3. 保存结果
        if output_csv is None:
            # 自动生成输出文件名
            from pathlib import Path
            from config import OUTPUT_SUFFIX
            input_path = Path(input_csv)
            output_csv = input_path.parent / f"{input_path.stem}{OUTPUT_SUFFIX}{input_path.suffix}"
        
        csv_handler.write_csv(str(output_csv))
        
        # 4. 打印统计信息
        stats = {
            'total': len(csv_handler.data),
            'unmatched': len(unmatched_rows),
            'newly_matched': newly_matched,
            'still_unmatched': still_unmatched
        }
        
        self._print_summary(stats)
        
        return stats
    
    def match_single_compound(
        self,
        compound_name: str,
        pathway_hint: Optional[str] = None,
        expected_compounds: Optional[List[str]] = None,
        use_metaboanalyst: bool = False,
        metaboanalyst_candidates: Optional[List[Dict]] = None
    ) -> Optional[Dict]:
        """
        匹配单个代谢物
        
        Args:
            compound_name: 代谢物名称
            pathway_hint: 代谢通路提示
            expected_compounds: 预期物质列表
            use_metaboanalyst: 是否使用MetaboAnalyst提供的候选
            metaboanalyst_candidates: MetaboAnalyst的候选列表（如果已获取）
            
        Returns:
            匹配结果，包含 Match, HMDB, PubChem, KEGG, SMILES
        """
        # 如果提供了MetaboAnalyst候选，优先使用
        if use_metaboanalyst and metaboanalyst_candidates:
            candidates = metaboanalyst_candidates
            print(f"  使用MetaboAnalyst提供的 {len(candidates)} 个候选")
        else:
            # Step 1: 数据库搜索获取候选
            candidates = self.db_client.search_all(compound_name)
            
            if not candidates:
                print(f"  ⚠ 数据库未找到候选，尝试AI推测标准名称...")
                
                # 使用AI推测可能的标准名称
                suggested_names = self.ai_matcher.suggest_standard_names(
                    compound_name,
                    pathway_hint=pathway_hint,
                    expected_compounds=expected_compounds
                )
                
                if suggested_names:
                    # 用推测的名称重新搜索
                    for suggested in suggested_names:
                        print(f"  → 尝试搜索: {suggested}")
                        candidates = self.db_client.search_all(suggested)
                        if candidates:
                            print(f"  ✓ 找到 {len(candidates)} 个候选")
                            break
                
                if not candidates:
                    print(f"  ✗ 所有尝试均失败，无法匹配")
                    return None
        
        # Step 2: AI判断最佳匹配
        best_match = self.ai_matcher.select_best_match(
            compound_name,
            candidates,
            pathway_hint=pathway_hint,
            expected_compounds=expected_compounds
        )
        
        if not best_match:
            return None
        
        # Step 3: 格式化为CSV所需格式
        result = {
            'Match': best_match.get('name', 'Unknown'),
            'HMDB': best_match.get('hmdb', 'NA'),
            'PubChem': best_match.get('pubchem', 'NA') or best_match.get('pubchem_cid', 'NA'),
            'KEGG': best_match.get('kegg', 'NA'),
            'SMILES': best_match.get('smiles', 'NA'),
            'checkbox_element': best_match.get('checkbox_element')  # 保留用于Selenium点击
        }
        
        return result
    
    def _print_summary(self, stats: Dict):
        """
        打印匹配结果摘要
        
        Args:
            stats: 统计信息字典
        """
        print("\n" + "="*60)
        print("匹配完成 - 结果摘要")
        print("="*60)
        print(f"总记录数:       {stats['total']}")
        print(f"原未匹配数:     {stats['unmatched']}")
        print(f"新匹配成功:     {stats['newly_matched']}")
        print(f"仍未匹配:       {stats['still_unmatched']}")
        
        if stats['unmatched'] > 0:
            success_rate = (stats['newly_matched'] / stats['unmatched']) * 100
            print(f"匹配成功率:     {success_rate:.1f}%")
        
        print("="*60)
    
    def get_match_report(self) -> List[Dict]:
        """
        获取详细的匹配报告
        
        Returns:
            所有匹配结果的列表
        """
        return self.match_results
    
    def clear_cache(self):
        """清空数据库查询缓存"""
        self.db_client.clear_cache()
