"""
测试脚本 - 使用前60种物质进行匹配测试
"""

import sys
import time
from pathlib import Path
from modules.matcher_core import MatcherCore
from modules.csv_handler import CSVHandler


def main():
    """运行测试"""
    print("="*70)
    print("Metabolite Matcher - 测试运行")
    print("使用前60种物质进行匹配测试")
    print("="*70)
    print()
    
    # 检查测试文件
    test_file = Path("test_sample.csv")
    if not test_file.exists():
        print("❌ 错误: 测试文件 test_sample.csv 不存在")
        sys.exit(1)
    
    print(f"✓ 找到测试文件: {test_file}")
    print()
    
    # 显示测试文件统计
    csv_handler = CSVHandler(str(test_file))
    csv_handler.read_csv()
    unmatched = csv_handler.filter_unmatched()
    
    print(f"测试文件统计:")
    print(f"  - 总物质数: {len(csv_handler.data)}")
    print(f"  - 已匹配: {len(csv_handler.data) - len(unmatched)}")
    print(f"  - 未匹配: {len(unmatched)}")
    print()
    
    # 显示前5个未匹配物质
    print("前5个未匹配物质:")
    for i, row in enumerate(unmatched[:5], 1):
        print(f"  {i}. {row['Query']}")
    print()
    
    # 询问是否继续
    print("⚠️  注意:")
    print("  - 此测试会调用DeepSeek API（产生费用）")
    print("  - 预计处理时间: 5-10分钟")
    print("  - 将会匹配 {} 个未匹配物质".format(len(unmatched)))
    print()
    
    response = input("是否继续? (输入 y 继续，其他键取消): ").strip().lower()
    if response != 'y':
        print("\n测试已取消")
        sys.exit(0)
    
    # 询问是否提供额外信息
    print("\n" + "="*70)
    print("🎯 可选：提供额外信息以提高匹配准确性")
    print("="*70)
    print()
    provide_hints = input("是否要提供代谢通路或预期物质信息? (y/n，默认n): ").strip().lower()
    
    pathway_hint = None
    expected_compounds = None
    
    if provide_hints == 'y':
        print()
        pathway = input("请输入预期的代谢通路名称（可选，直接回车跳过）: ").strip()
        if pathway:
            pathway_hint = pathway
            print(f"✓ 已设置通路提示: {pathway_hint}")
        
        print()
        compounds_input = input("请输入预期的有效物质，用逗号分隔（可选，直接回车跳过）: ").strip()
        if compounds_input:
            expected_compounds = [c.strip() for c in compounds_input.split(',') if c.strip()]
            print(f"✓ 已设置预期物质: {', '.join(expected_compounds)}")
    
    print()
    # 记录开始时间
    start_time = time.time()
    
    print("\n" + "="*70)
    print("开始测试...")
    print("="*70)
    print()
    
    # 显示配置
    if pathway_hint or expected_compounds:
        print("使用的额外信息:")
        if pathway_hint:
            print(f"  - 代谢通路: {pathway_hint}")
        if expected_compounds:
            print(f"  - 预期物质: {', '.join(expected_compounds)}")
        print()
    
    # 执行匹配
    try:
        matcher = MatcherCore()
        stats = matcher.process_csv(
            input_csv="test_sample.csv",
            output_csv="test_sample_matched.csv",
            pathway_hint=pathway_hint,
            expected_compounds=expected_compounds
        )
        
        # 记录结束时间
        end_time = time.time()
        elapsed = end_time - start_time
        
        # 打印详细报告
        print("\n" + "="*70)
        print("测试完成 - 详细报告")
        print("="*70)
        print()
        print(f"耗时: {elapsed:.1f} 秒 ({elapsed/60:.1f} 分钟)")
        print()
        print("匹配统计:")
        print(f"  - 总物质数: {stats['total']}")
        print(f"  - 原未匹配: {stats['unmatched']}")
        print(f"  - 新匹配成功: {stats['newly_matched']}")
        print(f"  - 仍未匹配: {stats['still_unmatched']}")
        
        if stats['unmatched'] > 0:
            success_rate = (stats['newly_matched'] / stats['unmatched']) * 100
            print(f"  - 匹配成功率: {success_rate:.1f}%")
        print()
        
        # 显示匹配详情
        print("匹配详情:")
        match_results = matcher.get_match_report()
        
        print("\n成功匹配的物质:")
        success_count = 0
        for result in match_results:
            if result['matched']:
                success_count += 1
                if success_count <= 10:  # 只显示前10个
                    query = result['query']
                    match = result['result']['Match']
                    source = result['result'].get('PubChem', 'NA')
                    print(f"  ✓ {query} → {match} (PubChem: {source})")
        
        if success_count > 10:
            print(f"  ... 还有 {success_count - 10} 个成功匹配")
        
        print("\n仍未匹配的物质:")
        failed_count = 0
        for result in match_results:
            if not result['matched']:
                failed_count += 1
                if failed_count <= 10:  # 只显示前10个
                    print(f"  ✗ {result['query']}")
        
        if failed_count > 10:
            print(f"  ... 还有 {failed_count - 10} 个未匹配")
        
        print()
        print("="*70)
        print(f"✓ 输出文件: test_sample_matched.csv")
        print("="*70)
        
    except KeyboardInterrupt:
        print("\n\n用户中断测试")
        sys.exit(130)
    
    except Exception as e:
        print(f"\n❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
