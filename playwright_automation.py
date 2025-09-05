#!/usr/bin/env python3.9
# -*- coding: utf-8 -*-
"""
Playwright 浏览器自动化工具模块
用于在 Dify-on-WeChat 项目中提供网页自动化功能

功能包括：
- 网页内容抓取
- 表单自动填写
- 页面截图
- 等待页面元素
- 模拟用户操作

作者：AI助手
创建时间：2025年
"""

import asyncio
import os
import time
from typing import Optional, Dict, List, Any
from playwright.async_api import async_playwright, Browser, BrowserContext, Page


class PlaywrightAutomation:
    """Playwright 浏览器自动化类"""
    
    def __init__(self, headless: bool = True, browser_type: str = "chromium"):
        """
        初始化 Playwright 自动化工具
        
        Args:
            headless (bool): 是否无头模式运行浏览器，默认True
            browser_type (str): 浏览器类型，支持 "chromium", "firefox", "webkit"
        """
        self.headless = headless
        self.browser_type = browser_type
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.playwright = None
        
    async def start_browser(self) -> None:
        """
        启动浏览器实例
        """
        try:
            self.playwright = await async_playwright().start()
            
            # 根据浏览器类型选择对应的浏览器
            if self.browser_type == "chromium":
                self.browser = await self.playwright.chromium.launch(headless=self.headless)
            elif self.browser_type == "firefox":
                self.browser = await self.playwright.firefox.launch(headless=self.headless)
            elif self.browser_type == "webkit":
                self.browser = await self.playwright.webkit.launch(headless=self.headless)
            else:
                raise ValueError(f"不支持的浏览器类型: {self.browser_type}")
            
            # 创建浏览器上下文，模拟真实用户环境
            self.context = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'
            )
            
            # 创建新页面
            self.page = await self.context.new_page()
            
            print(f"✅ 浏览器已启动 ({self.browser_type}, headless={self.headless})")
            
        except Exception as e:
            print(f"❌ 启动浏览器失败: {str(e)}")
            raise
    
    async def close_browser(self) -> None:
        """
        关闭浏览器实例
        """
        try:
            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            
            print("✅ 浏览器已关闭")
        except Exception as e:
            print(f"❌ 关闭浏览器失败: {str(e)}")
    
    async def navigate_to_page(self, url: str, wait_until: str = "networkidle") -> bool:
        """
        导航到指定网页
        
        Args:
            url (str): 目标网页URL
            wait_until (str): 等待条件，可选 "load", "domcontentloaded", "networkidle"
        
        Returns:
            bool: 导航是否成功
        """
        try:
            if not self.page:
                await self.start_browser()
            
            response = await self.page.goto(url, wait_until=wait_until, timeout=30000)
            
            if response and response.status == 200:
                print(f"✅ 成功导航到: {url}")
                return True
            else:
                print(f"❌ 导航失败，状态码: {response.status if response else 'None'}")
                return False
                
        except Exception as e:
            print(f"❌ 导航失败: {str(e)}")
            return False
    
    async def get_page_content(self) -> Optional[str]:
        """
        获取当前页面的HTML内容
        
        Returns:
            Optional[str]: 页面HTML内容，失败返回None
        """
        try:
            if not self.page:
                print("❌ 页面实例不存在")
                return None
            
            content = await self.page.content()
            print(f"✅ 成功获取页面内容，长度: {len(content)}字符")
            return content
            
        except Exception as e:
            print(f"❌ 获取页面内容失败: {str(e)}")
            return None
    
    async def take_screenshot(self, file_path: str, full_page: bool = True) -> bool:
        """
        截取页面截图
        
        Args:
            file_path (str): 保存截图的文件路径
            full_page (bool): 是否截取整个页面，默认True
        
        Returns:
            bool: 截图是否成功
        """
        try:
            if not self.page:
                print("❌ 页面实例不存在")
                return False
            
            # 确保目录存在
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            await self.page.screenshot(path=file_path, full_page=full_page)
            print(f"✅ 截图已保存到: {file_path}")
            return True
            
        except Exception as e:
            print(f"❌ 截图失败: {str(e)}")
            return False
    
    async def fill_form_field(self, selector: str, value: str) -> bool:
        """
        填写表单字段
        
        Args:
            selector (str): 元素选择器
            value (str): 要填入的值
        
        Returns:
            bool: 填写是否成功
        """
        try:
            if not self.page:
                print("❌ 页面实例不存在")
                return False
            
            # 等待元素出现
            await self.page.wait_for_selector(selector, timeout=10000)
            
            # 清空并填入新值
            await self.page.fill(selector, value)
            print(f"✅ 成功填写字段 {selector}: {value}")
            return True
            
        except Exception as e:
            print(f"❌ 填写字段失败: {str(e)}")
            return False
    
    async def click_element(self, selector: str) -> bool:
        """
        点击页面元素
        
        Args:
            selector (str): 元素选择器
        
        Returns:
            bool: 点击是否成功
        """
        try:
            if not self.page:
                print("❌ 页面实例不存在")
                return False
            
            # 等待元素出现并可点击
            await self.page.wait_for_selector(selector, timeout=10000)
            await self.page.click(selector)
            print(f"✅ 成功点击元素: {selector}")
            return True
            
        except Exception as e:
            print(f"❌ 点击元素失败: {str(e)}")
            return False
    
    async def get_element_text(self, selector: str) -> Optional[str]:
        """
        获取元素的文本内容
        
        Args:
            selector (str): 元素选择器
        
        Returns:
            Optional[str]: 元素文本内容，失败返回None
        """
        try:
            if not self.page:
                print("❌ 页面实例不存在")
                return None
            
            # 等待元素出现
            await self.page.wait_for_selector(selector, timeout=10000)
            text = await self.page.text_content(selector)
            print(f"✅ 成功获取元素文本: {text[:50]}...")
            return text
            
        except Exception as e:
            print(f"❌ 获取元素文本失败: {str(e)}")
            return None
    
    async def wait_for_element(self, selector: str, timeout: int = 10000) -> bool:
        """
        等待页面元素出现
        
        Args:
            selector (str): 元素选择器
            timeout (int): 超时时间（毫秒），默认10秒
        
        Returns:
            bool: 元素是否出现
        """
        try:
            if not self.page:
                print("❌ 页面实例不存在")
                return False
            
            await self.page.wait_for_selector(selector, timeout=timeout)
            print(f"✅ 元素已出现: {selector}")
            return True
            
        except Exception as e:
            print(f"❌ 等待元素失败: {str(e)}")
            return False
    
    async def scroll_to_bottom(self) -> None:
        """
        滚动到页面底部
        """
        try:
            if not self.page:
                print("❌ 页面实例不存在")
                return
            
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            print("✅ 已滚动到页面底部")
            
        except Exception as e:
            print(f"❌ 滚动失败: {str(e)}")
    
    async def extract_links(self) -> List[str]:
        """
        提取页面中的所有链接
        
        Returns:
            List[str]: 页面中的链接列表
        """
        try:
            if not self.page:
                print("❌ 页面实例不存在")
                return []
            
            links = await self.page.evaluate("""
                () => {
                    const anchors = Array.from(document.querySelectorAll('a[href]'));
                    return anchors.map(anchor => anchor.href);
                }
            """)
            
            print(f"✅ 成功提取 {len(links)} 个链接")
            return links
            
        except Exception as e:
            print(f"❌ 提取链接失败: {str(e)}")
            return []
    
    async def execute_javascript(self, script: str) -> Any:
        """
        在页面中执行JavaScript代码
        
        Args:
            script (str): 要执行的JavaScript代码
        
        Returns:
            Any: JavaScript执行结果
        """
        try:
            if not self.page:
                print("❌ 页面实例不存在")
                return None
            
            result = await self.page.evaluate(script)
            print(f"✅ JavaScript执行成功")
            return result
            
        except Exception as e:
            print(f"❌ JavaScript执行失败: {str(e)}")
            return None


# 便民函数，提供快速使用的接口
async def quick_screenshot(url: str, output_path: str = "screenshot.png") -> bool:
    """
    快速截图功能
    
    Args:
        url (str): 目标网页URL
        output_path (str): 截图保存路径
    
    Returns:
        bool: 是否成功
    """
    automation = PlaywrightAutomation()
    try:
        await automation.start_browser()
        success = await automation.navigate_to_page(url)
        if success:
            return await automation.take_screenshot(output_path)
        return False
    finally:
        await automation.close_browser()


async def quick_content_extract(url: str) -> Optional[str]:
    """
    快速内容提取功能
    
    Args:
        url (str): 目标网页URL
    
    Returns:
        Optional[str]: 页面HTML内容
    """
    automation = PlaywrightAutomation()
    try:
        await automation.start_browser()
        success = await automation.navigate_to_page(url)
        if success:
            return await automation.get_page_content()
        return None
    finally:
        await automation.close_browser()


if __name__ == "__main__":
    # 示例使用
    async def main():
        print("🤖 Playwright 自动化工具测试")
        print("=" * 50)
        
        # 创建自动化实例
        automation = PlaywrightAutomation(headless=True)
        
        try:
            # 启动浏览器
            await automation.start_browser()
            
            # 导航到测试页面
            url = "https://www.baidu.com"
            await automation.navigate_to_page(url)
            
            # 截图
            await automation.take_screenshot("tmp/baidu_screenshot.png")
            
            # 获取页面标题
            title = await automation.execute_javascript("document.title")
            print(f"📄 页面标题: {title}")
            
            # 提取链接
            links = await automation.extract_links()
            print(f"🔗 找到 {len(links)} 个链接")
            
        finally:
            # 关闭浏览器
            await automation.close_browser()
    
    # 运行示例
    asyncio.run(main())


