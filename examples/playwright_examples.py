#!/usr/bin/env python3.9
# -*- coding: utf-8 -*-
"""
Playwright 浏览器自动化示例脚本
演示各种常用的网页自动化操作

运行方法：
python examples/playwright_examples.py

示例包括：
1. 网页截图
2. 搜索操作
3. 表单填写
4. 内容提取
5. 页面监控

作者：AI助手
创建时间：2025年
"""

import asyncio
import os
import sys
import time
from datetime import datetime

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from playwright_automation import PlaywrightAutomation, quick_screenshot, quick_content_extract


class PlaywrightExamples:
    """Playwright 使用示例集合"""
    
    def __init__(self):
        self.automation = PlaywrightAutomation(headless=True)
    
    async def example_1_basic_screenshot(self):
        """示例1: 基础网页截图"""
        print("\n📸 示例1: 基础网页截图")
        print("-" * 40)
        
        await self.automation.start_browser()
        
        # 访问百度首页并截图
        success = await self.automation.navigate_to_page("https://www.baidu.com")
        if success:
            await self.automation.take_screenshot("tmp/baidu_homepage.png")
            print("✅ 百度首页截图完成")
        
        await self.automation.close_browser()
    
    async def example_2_search_operation(self):
        """示例2: 搜索操作演示"""
        print("\n🔍 示例2: 搜索操作演示")
        print("-" * 40)
        
        await self.automation.start_browser()
        
        try:
            # 访问百度
            await self.automation.navigate_to_page("https://www.baidu.com")
            
            # 等待搜索框出现
            await self.automation.wait_for_element("#kw")
            
            # 填写搜索内容
            await self.automation.fill_form_field("#kw", "Playwright 自动化")
            
            # 点击搜索按钮
            await self.automation.click_element("#su")
            
            # 等待搜索结果加载
            await asyncio.sleep(3)
            
            # 截图保存搜索结果
            await self.automation.take_screenshot("tmp/search_results.png")
            print("✅ 搜索操作完成")
            
        except Exception as e:
            print(f"❌ 搜索操作失败: {e}")
        
        await self.automation.close_browser()
    
    async def example_3_content_extraction(self):
        """示例3: 内容提取演示"""
        print("\n📝 示例3: 内容提取演示")
        print("-" * 40)
        
        await self.automation.start_browser()
        
        try:
            # 访问新闻网站
            await self.automation.navigate_to_page("https://news.baidu.com")
            
            # 等待页面加载完成
            await asyncio.sleep(2)
            
            # 获取页面标题
            title = await self.automation.execute_javascript("document.title")
            print(f"📄 页面标题: {title}")
            
            # 提取所有链接
            links = await self.automation.extract_links()
            print(f"🔗 页面包含 {len(links)} 个链接")
            
            # 显示前5个链接
            for i, link in enumerate(links[:5]):
                print(f"   {i+1}. {link}")
            
            # 获取特定元素的文本（如果存在）
            try:
                news_title = await self.automation.get_element_text("h3")
                if news_title:
                    print(f"📰 找到新闻标题: {news_title[:50]}...")
            except:
                print("📰 未找到新闻标题元素")
            
        except Exception as e:
            print(f"❌ 内容提取失败: {e}")
        
        await self.automation.close_browser()
    
    async def example_4_github_exploration(self):
        """示例4: GitHub页面探索"""
        print("\n🐱 示例4: GitHub页面探索")
        print("-" * 40)
        
        await self.automation.start_browser()
        
        try:
            # 访问GitHub
            await self.automation.navigate_to_page("https://github.com")
            
            # 等待页面加载
            await asyncio.sleep(2)
            
            # 截图GitHub首页
            await self.automation.take_screenshot("tmp/github_homepage.png")
            
            # 获取页面信息
            title = await self.automation.execute_javascript("document.title")
            print(f"📄 GitHub页面标题: {title}")
            
            # 查找搜索框
            search_exists = await self.automation.wait_for_element("input[placeholder*='Search']", timeout=5000)
            if search_exists:
                print("✅ 找到GitHub搜索框")
                # 可以在这里添加搜索操作
            else:
                print("❌ 未找到GitHub搜索框")
            
        except Exception as e:
            print(f"❌ GitHub探索失败: {e}")
        
        await self.automation.close_browser()
    
    async def example_5_quick_functions(self):
        """示例5: 快速函数使用"""
        print("\n⚡ 示例5: 快速函数使用")
        print("-" * 40)
        
        # 使用快速截图功能
        print("使用快速截图功能...")
        success = await quick_screenshot("https://www.python.org", "tmp/python_org.png")
        if success:
            print("✅ Python官网截图完成")
        
        # 使用快速内容提取功能
        print("使用快速内容提取功能...")
        content = await quick_content_extract("https://httpbin.org/json")
        if content:
            print(f"✅ 内容提取完成，长度: {len(content)} 字符")
            print(f"📄 内容预览: {content[:200]}...")
    
    async def example_6_page_monitoring(self):
        """示例6: 页面变化监控"""
        print("\n👀 示例6: 页面变化监控演示")
        print("-" * 40)
        
        await self.automation.start_browser()
        
        try:
            # 访问一个有动态内容的页面
            await self.automation.navigate_to_page("https://httpbin.org/uuid")
            
            print("开始监控页面变化...")
            
            for i in range(3):
                # 获取当前页面内容
                content = await self.automation.get_page_content()
                timestamp = datetime.now().strftime("%H:%M:%S")
                print(f"⏰ {timestamp} - 检查 #{i+1}")
                
                # 截图记录
                await self.automation.take_screenshot(f"tmp/monitor_{i+1}.png")
                
                # 刷新页面
                await self.automation.page.reload()
                await asyncio.sleep(2)
            
            print("✅ 页面监控演示完成")
            
        except Exception as e:
            print(f"❌ 页面监控失败: {e}")
        
        await self.automation.close_browser()


async def run_all_examples():
    """运行所有示例"""
    print("🚀 Playwright 自动化工具示例演示")
    print("=" * 50)
    
    # 确保临时目录存在
    os.makedirs("tmp", exist_ok=True)
    
    examples = PlaywrightExamples()
    
    # 运行各个示例
    await examples.example_1_basic_screenshot()
    await examples.example_2_search_operation()
    await examples.example_3_content_extraction()
    await examples.example_4_github_exploration()
    await examples.example_5_quick_functions()
    await examples.example_6_page_monitoring()
    
    print("\n" + "=" * 50)
    print("🎉 所有示例演示完成！")
    print("📁 截图文件保存在 tmp/ 目录中")
    print("💡 你可以查看这些文件来了解Playwright的效果")


async def interactive_mode():
    """交互式模式"""
    print("\n🎮 交互式模式")
    print("你可以输入网址，程序会自动截图")
    print("输入 'quit' 退出")
    print("-" * 40)
    
    automation = PlaywrightAutomation(headless=True)
    await automation.start_browser()
    
    try:
        while True:
            url = input("\n请输入网址 (或 'quit' 退出): ").strip()
            
            if url.lower() == 'quit':
                break
            
            if not url:
                continue
            
            # 确保URL格式正确
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            
            print(f"📡 正在访问: {url}")
            
            success = await automation.navigate_to_page(url)
            if success:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"tmp/interactive_{timestamp}.png"
                await automation.take_screenshot(filename)
                print(f"✅ 截图已保存: {filename}")
            else:
                print("❌ 访问失败，请检查网址是否正确")
    
    except KeyboardInterrupt:
        print("\n👋 用户中断，退出交互模式")
    
    finally:
        await automation.close_browser()


if __name__ == "__main__":
    print("🤖 Playwright 浏览器自动化示例")
    print("请选择运行模式：")
    print("1. 运行所有示例 (自动)")
    print("2. 交互式模式")
    
    choice = input("\n请输入选择 (1 或 2): ").strip()
    
    if choice == "1":
        asyncio.run(run_all_examples())
    elif choice == "2":
        asyncio.run(interactive_mode())
    else:
        print("无效选择，运行所有示例...")
        asyncio.run(run_all_examples())


