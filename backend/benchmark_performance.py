#!/usr/bin/env python3
"""性能基准测试 —— 测量全市场涨停基因分析各阶段耗时。"""
import asyncio
import time

from limitup_screener.service import get_screener_result


async def main():
    print("=" * 60)
    print("性能基准测试：全市场涨停基因分析")
    print("=" * 60)
    
    # 预热缓存
    print("\n[1/2] 预热缓存...")
    start = time.perf_counter()
    await get_screener_result()
    elapsed = time.perf_counter() - start
    print(f"  预热耗时: {elapsed:.2f}s")
    
    # 正式测试（缓存命中）
    print("\n[2/2] 缓存命中测试...")
    start = time.perf_counter()
    result = await get_screener_result()
    elapsed = time.perf_counter() - start
    print(f"  缓存命中耗时: {elapsed:.2f}s")
    print(f"  股票数量: {len(result.gene_scores)}")
    print(f"  合格数量: {len(result.qualified)}")
    print(f"  高基因数量: {len(result.high_gene)}")
    
    # 性能评估
    print("\n" + "=" * 60)
    print("性能评估（PRD V2.0 目标）")
    print("=" * 60)
    print(f"  数据获取层目标: <8s")
    print(f"  计算层目标: <60s")
    print(f"  API响应层目标: <500ms")
    print(f"\n  实际缓存命中耗时: {elapsed:.2f}s")
    
    if elapsed < 0.5:
        print("  ✅ API响应层：优秀")
    elif elapsed < 2.0:
        print("  ✅ API响应层：良好")
    else:
        print("  ⚠️  API响应层：需要优化")
    
    print("\n注：首次计算（缓存未命中）会包含数据获取和计算时间，")
    print("   通常需要 5-30 秒 depending on 网络和股票数量。")


if __name__ == "__main__":
    asyncio.run(main())
