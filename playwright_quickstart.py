#!/usr/bin/env python3.9
# -*- coding: utf-8 -*-
"""
Playwright 快速入门脚本
简单演示 Playwright 基础功能

运行方法：
python playwright_quickstart.py

功能演示：
- 访问网页并截图
- 简单的页面操作

作者：AI助手
创建时间：2025年
"""

import asyncio
import os
from playwright_automation import PlaywrightAutomation


async def main():
    """主函数 - 演示 Playwright 基础功能"""
    print("🚀 Playwright 快速入门")
    print("=" * 40)
    
    # 确保临时目录存在
    os.makedirs("tmp", exist_ok=True)
    
    # 创建 Playwright 自动化实例
    automation = PlaywrightAutomation(headless=True)
    
    try:
        print("📡 启动浏览器...")
        await automation.start_browser()
        
        print("🌐 访问百度首页...")
        success = await automation.navigate_to_page("https://www.baidu.com")
        
        if success:
            print("📸 截图保存...")
            await automation.take_screenshot("tmp/baidu_quickstart.png")
            
            print("📄 获取页面标题...")
            title = await automation.execute_javascript("document.title")
            print(f"   页面标题: {title}")
            
            print("🔗 提取页面链接...")
            links = await automation.extract_links()
            print(f"   找到 {len(links)} 个链接")
            
            print("✅ 演示完成！")
            print(f"📁 截图已保存到: tmp/baidu_quickstart.png")
        else:
            print("❌ 访问网页失败")
    
    except Exception as e:
        print(f"❌ 出现错误: {e}")
    
    finally:
        print("🔚 关闭浏览器...")
        await automation.close_browser()
    
    print("\n💡 想了解更多功能？运行以下命令:")
    print("   python examples/playwright_examples.py")


if __name__ == "__main__":
    asyncio.run(main())


