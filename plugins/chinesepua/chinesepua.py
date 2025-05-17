import io
import random
import re
import time
import os
import json
import logging
import asyncio
from typing import Optional, Dict, List, Tuple, Union
from pathlib import Path
from datetime import datetime, timedelta
from playwright.async_api import async_playwright, Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError
import string

import plugins
from PIL import Image, ImageDraw, ImageFont
import textwrap
from bs4 import BeautifulSoup

from bridge.context import Context as EventContext
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from common.tmp_dir import TmpDir
from plugins import Plugin, Event
from .prompts import get_prompt

class ChinesePuaConfig:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.api_key = ""
        self.api_base = ""
        self.api_model = ""
        self.max_tokens = 2048
        self.temperature = 0.7
        self.with_text = False
        self.load_config()

    def load_config(self) -> None:
        """加载配置文件"""
        try:
            if not os.path.exists(self.config_path):
                raise FileNotFoundError(f"配置文件不存在: {self.config_path}")

            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                
            self.api_key = config.get("api_key", "")
            self.api_base = config.get("api_base", "")
            self.api_model = config.get("api_model", "")
            self.max_tokens = config.get("max_tokens", 2048)
            self.temperature = config.get("temperature", 0.7)
            self.with_text = config.get("with_text", False)

        except json.JSONDecodeError as e:
            raise ValueError(f"配置文件格式错误: {str(e)}")
        except Exception as e:
            raise RuntimeError(f"加载配置文件失败: {str(e)}")

@plugins.register(
    name="chinesepua",
    desc="A plugin that generates satirical explanation cards for Chinese phrases",
    version="0.5",
    author="BenedictKing",
    desire_priority=200,
)
class ChinesePuaPlugin(Plugin):
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        self.commands = {
            "解释": self.explain_handler,
            "吐槽": self.explain_handler,
            "help": self.help_handler,
        }
        
        # 初始化配置和目录
        try:
            config_path = os.path.join(os.path.dirname(__file__), 'config.json')
            self.config = ChinesePuaConfig(config_path)
            self.temp_dir = TmpDir().path()
            self._ensure_temp_dir()
            
            # 加载并缓存HTML模板
            self.template_path = os.path.join(os.path.dirname(__file__), 'template.html')
            self.template_content = self._load_template()
            
            # 验证配置
            if not self._validate_config():
                raise RuntimeError("配置验证失败")
            
        except Exception as e:
            self.logger.error(f"插件初始化失败: {str(e)}")
            raise

    def _load_template(self) -> str:
        """加载并验证HTML模板
        
        Returns:
            str: 验证通过的HTML模板内容
            
        Raises:
            FileNotFoundError: 模板文件不存在
            ValueError: 模板内容验证失败
        """
        try:
            if not os.path.exists(self.template_path):
                raise FileNotFoundError(f"模板文件不存在: {self.template_path}")
            
            with open(self.template_path, 'r', encoding='utf-8') as f:
                template = f.read()
            
            # 验证模板是否包含必要的占位符
            required_placeholders = ['{{text}}', '{{explanation}}']
            for placeholder in required_placeholders:
                if placeholder not in template:
                    raise ValueError(f"模板缺少必要的占位符: {placeholder}")
            
            # 验证模板基本HTML结构
            if not all(tag in template.lower() for tag in ['<!doctype html>', '<html', '<head', '<body']):
                raise ValueError("模板缺少基本HTML结构")
                
            self.logger.info("HTML模板加载并验证成功")
            return template
            
        except Exception as e:
            self.logger.error(f"加载HTML模板失败: {str(e)}")
            raise

    def _escape_html(self, text: str) -> str:
        """转义HTML特殊字符
        
        Args:
            text: 需要转义的文本
            
        Returns:
            str: 转义后的文本
        """
        html_escape_table = {
            "&": "&amp;",
            '"': "&quot;",
            "'": "&apos;",
            ">": "&gt;",
            "<": "&lt;",
        }
        return "".join(html_escape_table.get(c, c) for c in text)

    def get_help_text(self, **kwargs) -> str:
        """获取帮助信息"""
        help_text = (
            "🎭 解释梗/词语插件\n\n"
            "使用方法：\n"
            "1. 发送 '解释 [词语]' 来获取解释\n"
            "2. 词语应为1-10个汉字\n\n"
            "示例：\n"
            "- 解释 加班\n"
            "- 解释 内卷\n"
            "- 解释 摸鱼\n"
        )
        return help_text

    def help_handler(self, e_context: EventContext) -> None:
        self._set_reply_text(e_context, self.get_help_text())

    async def explain_handler(self, e_context: EventContext) -> None:
        """处理解释命令
        
        Args:
            e_context: 事件上下文
        """
        try:
            # 提取关键词
            content = e_context.content
            for prefix in ["解释", "吐槽"]:
                if content.startswith(prefix):
                    keyword = content[len(prefix):].strip()
                    break
            else:
                self._set_reply_text(e_context, "请使用'解释'或'吐槽'命令")
                return

            # 验证关键词
            if not self.validate_keyword(keyword):
                self._set_reply_text(e_context, "请输入1-10个汉字的词语")
                return

            # 生成HTML
            html_path = await self._generate_html(keyword)
            if not html_path:
                self._set_reply_text(e_context, "生成解释内容失败")
                return

            try:
                # 渲染图片
                image_data = await self._render_html_to_image(html_path)
                if not image_data:
                    raise ValueError("渲染图片失败")

                # 保存图片
                image_path = self._save_image(image_data)
                if not image_path:
                    raise ValueError("保存图片失败")

                # 发送图片
                reply = Reply(ReplyType.IMAGE, image_path)
                e_context.reply = reply
                e_context.channel.send(reply)
                self.logger.info(f"成功发送解释图片: {image_path}")

            except Exception as e:
                self.logger.error(f"生成或发送图片失败: {str(e)}")
                self._set_reply_text(e_context, f"生成解释失败: {str(e)}")
                return

            finally:
                # 清理临时文件
                self._cleanup_temp_files(html_path)

        except Exception as e:
            error_msg = self._format_error_message(e)
            self._set_reply_text(e_context, error_msg)
            self.logger.error(f"处理解释命令失败: {str(e)}")

    def get_event_handler(self, event: Event) -> Optional[callable]:
        """获取事件处理器"""
        if event.event_type != ContextType.TEXT:
            return None
        
        content = event.content.strip()
        for command, handler in self.commands.items():
            if content.startswith(command):
                self.logger.info(f"检测到命令: {command}, 内容: {content}")
                return handler
        return None

    def get_event_names(self) -> List[str]:
        """获取支持的事件名称列表"""
        return list(self.commands.keys())

    def _cleanup_old_images(self) -> None:
        """清理24小时前的旧图片文件"""
        try:
            # 确保临时目录存在
            self._ensure_temp_dir()
            
            # 获取当前时间
            now = datetime.now()
            
            # 遍历临时目录中的所有文件
            for file_name in os.listdir(self.temp_dir):
                if not file_name.endswith('.png'):
                    continue
                
                file_path = os.path.join(self.temp_dir, file_name)
                
                # 获取文件修改时间
                mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
                
                # 如果文件超过24小时，则删除
                if (now - mtime).total_seconds() > 24 * 3600:
                    try:
                        os.remove(file_path)
                        self.logger.info(f"已删除旧图片: {file_name}")
                    except Exception as e:
                        self.logger.error(f"删除旧图片失败 {file_name}: {e}")
                    
        except Exception as e:
            self.logger.error(f"清理旧图片时发生错误: {e}")
            # 继续执行，不影响主流程

    def _ensure_temp_dir(self):
        """确保临时目录存在并可写"""
        try:
            if not os.path.exists(self.temp_dir):
                os.makedirs(self.temp_dir)
                self.logger.info(f"创建临时目录: {self.temp_dir}")
            elif not os.access(self.temp_dir, os.W_OK):
                raise PermissionError(f"临时目录无写入权限: {self.temp_dir}")
        except Exception as e:
            self.logger.error(f"检查临时目录失败: {str(e)}")
            raise

    def _extract_keyword(self, content: str) -> Optional[str]:
        """从用户消息中提取关键词
        
        Args:
            content: 用户消息内容
            
        Returns:
            提取的关键词，如果提取失败则返回None
        """
        try:
            # 移除命令前缀
            for prefix in ["解释", "explain"]:
                if content.startswith(prefix):
                    keyword = content[len(prefix):].strip()
                    if self.validate_keyword(keyword):
                        return keyword
                    else:
                        self.logger.warning(f"无效的关键词: {keyword}")
                        return None
                    
            self.logger.warning(f"消息不包含有效的命令前缀: {content}")
            return None
        
        except Exception as e:
            self.logger.error(f"提取关键词时发生错误: {e}")
            return None

    def _set_reply_text(self, e_context: EventContext, text: str, reply_type: ReplyType = ReplyType.TEXT) -> None:
        """设置回复消息
        
        Args:
            e_context: 事件上下文
            text: 回复文本
            reply_type: 回复类型，默认为TEXT
        """
        try:
            if not text:
                self.logger.warning("回复文本为空")
                text = "抱歉，发生了一些错误，请稍后再试"
            
            reply = Reply(ReplyType.TEXT)
            reply.content = text
            e_context.reply = reply
            e_context.channel.send(reply)
            self.logger.info(f"已发送回复: {text}")
            
        except Exception as e:
            self.logger.error(f"设置回复消息时发生错误: {e}")
            # 确保至少发送一个错误提示
            fallback_reply = Reply(ReplyType.TEXT)
            fallback_reply.content = "抱歉，发生了意外错误，请稍后再试"
            e_context.reply = fallback_reply
            try:
                e_context.channel.send(fallback_reply)
            except:
                self.logger.error("发送fallback消息也失败了")

    async def _send_img(self, e_context: EventContext, image_path: str) -> None:
        """发送图片消息
        
        Args:
            e_context: 事件上下文对象
            image_path: 图片文件路径
        """
        try:
            if not os.path.exists(image_path):
                raise FileNotFoundError(f"图片文件不存在: {image_path}")
                
            # 检查文件大小
            file_size = os.path.getsize(image_path)
            if file_size > 5 * 1024 * 1024:  # 5MB
                raise ValueError("图片文件过大，请重试")
                
            # 检查文件格式
            if not image_path.lower().endswith(('.png', '.jpg', '.jpeg')):
                raise ValueError("不支持的图片格式")
            
            reply = Reply(ReplyType.IMAGE, image_path)
            e_context.channel.send(reply)
            self.logger.info(f"图片发送成功: {image_path}")
            
        except Exception as e:
            error_message = self._format_error_message(e)
            self._set_reply_text(e_context, error_message)
            self.logger.error(f"发送图片失败: {str(e)}")
            raise

    async def _generate_html(self, keyword: str) -> str:
        """生成HTML内容
        
        Args:
            keyword: 需要解释的关键词
            
        Returns:
            str: 生成的HTML内容
            
        Raises:
            ValueError: 生成HTML失败
        """
        try:
            # 获取并转义关键词的解释
            explanation = self.get_prompt(keyword)
            if not explanation:
                raise ValueError(f"无法获取关键词的解释: {keyword}")
            
            # 转义关键词和解释文本
            safe_keyword = self._escape_html(keyword)
            safe_explanation = self._escape_html(explanation)
            
            # 替换模板中的占位符
            html_content = self.template_content
            html_content = html_content.replace('{{text}}', safe_keyword)
            html_content = html_content.replace('{{explanation}}', safe_explanation)
            
            # 验证生成的HTML
            if not all(tag in html_content.lower() for tag in ['<!doctype html>', '<html', '<head', '<body']):
                raise ValueError("生成的HTML缺少基本结构")
            
            # 创建临时HTML文件
            temp_html_path = os.path.join(self.temp_dir, f'explanation_{int(time.time())}.html')
            with open(temp_html_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            self.logger.info(f"HTML内容生成成功: {temp_html_path}")
            return temp_html_path
            
        except Exception as e:
            self.logger.error(f"生成HTML内容失败: {str(e)}")
            raise ValueError(f"生成HTML内容失败: {str(e)}")

    async def _render_html_to_image(self, html_path: str) -> Optional[bytes]:
        """将HTML渲染为图片
        
        Args:
            html_path: HTML文件路径
            
        Returns:
            Optional[bytes]: 图片数据，失败返回None
        """
        if not os.path.exists(html_path):
            raise FileNotFoundError(f"HTML文件不存在: {html_path}")
            
        browser = None
        try:
            async with async_playwright() as p:
                # 启动浏览器，使用无头模式并优化性能
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-gpu',
                        '--disable-web-security',
                    ]
                )
                
                # 创建新的浏览器上下文，设置较小的视口
                context = await browser.new_context(
                    viewport={'width': 600, 'height': 400},
                    device_scale_factor=2.0
                )
                
                # 创建新页面并设置较短的超时
                page = await context.new_page()
                page.set_default_timeout(10000)  # 10秒超时
                
                # 加载HTML文件
                file_url = f'file://{os.path.abspath(html_path)}'
                await page.goto(file_url, wait_until='load')
                
                # 等待卡片元素出现
                card = await page.wait_for_selector('.card', timeout=5000)
                if not card:
                    raise ValueError("无法找到卡片元素")
                
                # 获取卡片尺寸并调整视口
                box = await card.bounding_box()
                if not box:
                    raise ValueError("无法获取卡片尺寸")
                
                # 确保内容完全可见
                await page.set_viewport_size({
                    'width': max(600, int(box['width']) + 40),
                    'height': max(400, int(box['height']) + 40)
                })
                
                # 截图
                screenshot = await card.screenshot(type='png')
                self.logger.info("成功渲染HTML为图片")
                return screenshot
                
        except Exception as e:
            self.logger.error(f"渲染HTML失败: {str(e)}")
            return None
            
        finally:
            if browser:
                await browser.close()

    def _save_image(self, image_data: bytes) -> Optional[str]:
        """保存图片数据到文件
        
        Args:
            image_data: 图片二进制数据
            
        Returns:
            Optional[str]: 保存的图片文件路径，失败返回None
        """
        if not image_data:
            self.logger.error("图片数据为空")
            return None
            
        try:
            # 确保临时目录存在
            self._ensure_temp_dir()
            
            # 生成唯一的文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            random_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
            filename = f"explanation_{timestamp}_{random_str}.png"
            image_path = os.path.join(self.temp_dir, filename)
            
            # 保存图片
            with open(image_path, 'wb') as f:
                f.write(image_data)
                
            self.logger.info(f"成功保存图片: {image_path}")
            return image_path
            
        except Exception as e:
            self.logger.error(f"保存图片失败: {str(e)}")
            return None

    async def _safe_generate_image(self, keyword: str) -> tuple[str, str]:
        """安全地生成解释图片
        
        Args:
            keyword: 需要解释的关键词
            
        Returns:
            tuple[str, str]: (图片路径, 错误信息)
        """
        temp_html_path = None
        try:
            # 确保临时目录存在
            self._ensure_temp_dir()
            
            # 生成HTML
            temp_html_path = await self._generate_html(keyword)
            
            # 渲染图片
            image_path = await self._render_html_to_image(temp_html_path)
            
            return image_path, ""
            
        except Exception as e:
            error_msg = f"生成图片失败: {str(e)}"
            self.logger.error(error_msg)
            return "", error_msg
            
        finally:
            # 清理临时HTML文件
            if temp_html_path:
                self._cleanup_temp_files(temp_html_path)

    def validate_keyword(self, keyword: str) -> bool:
        """验证关键词是否有效
        
        Args:
            keyword: 待验证的关键词
            
        Returns:
            bool: 关键词是否有效
        """
        if not keyword or not isinstance(keyword, str):
            self.logger.warning(f"关键词无效: {keyword}")
            return False
        
        # 去除空白字符
        keyword = keyword.strip()
        
        # 检查长度
        if len(keyword) < 1 or len(keyword) > 10:
            self.logger.warning(f"关键词长度无效: {keyword}")
            return False
        
        # 检查是否包含中文字符
        if not any('\u4e00' <= char <= '\u9fff' for char in keyword):
            self.logger.warning(f"关键词不包含中文字符: {keyword}")
            return False
        
        return True

    def _format_error_message(self, error: Exception) -> str:
        """格式化错误消息
        
        Args:
            error: 异常对象
            
        Returns:
            str: 格式化后的错误消息
        """
        try:
            if isinstance(error, FileNotFoundError):
                return "找不到所需的文件，请检查配置是否正确"
            elif isinstance(error, json.JSONDecodeError):
                return "配置文件格式错误，请检查JSON语法"
            elif isinstance(error, ValueError):
                if "keyword" in str(error).lower():
                    return "请输入有效的中文词语（1-10个字）"
                return f"输入值无效: {str(error)}"
            elif isinstance(error, PlaywrightTimeoutError):
                return "生成图片超时，请稍后重试"
            elif isinstance(error, PlaywrightError):
                return f"浏览器渲染失败: {str(error)}"
            else:
                self.logger.error(f"未处理的错误类型: {type(error)}, 错误信息: {str(error)}")
                return "抱歉，发生了意外错误，请稍后再试"
        except Exception as e:
            self.logger.error(f"格式化错误消息时发生错误: {e}")
            return "抱歉，发生了意外错误，请稍后再试"

    def get_prompt(self, keyword: str) -> str:
        """生成提示词"""
        from .prompts import get_prompt
        return get_prompt(keyword)

    async def handle_event(self, e_context: EventContext) -> None:
        """处理事件的主方法
        
        Args:
            e_context: 事件上下文对象
        """
        try:
            # 清理旧图片
            self._cleanup_old_images()
            
            # 获取事件处理器
            handler = self.get_event_handler(e_context)
            if not handler:
                return
                
            # 执行处理器
            await handler(e_context)
            
        except Exception as e:
            error_message = self._format_error_message(e)
            self._set_reply_text(e_context, error_message)
            self.logger.error(f"处理事件失败: {str(e)}")

    def get_priority(self) -> int:
        """获取插件优先级"""
        return 200

    def get_name(self) -> str:
        """获取插件名称"""
        return "ChinesePUA"

    def get_description(self) -> str:
        """获取插件描述"""
        return "一个用于解释中文词语的有趣插件"

    def get_version(self) -> str:
        """获取插件版本"""
        return "1.0.0"

    def get_author(self) -> str:
        """获取插件作者"""
        return "Your Name"

    def _cleanup_temp_files(self, file_path: str = None):
        """清理临时文件
        
        Args:
            file_path: 指定要清理的文件路径，如果为None则清理所有过期文件
        """
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
                self.logger.info(f"已删除临时文件: {file_path}")
                return
            
            # 清理24小时前的临时文件
            current_time = time.time()
            for filename in os.listdir(self.temp_dir):
                if not (filename.endswith('.html') or filename.endswith('.png')):
                    continue
                    
                file_path = os.path.join(self.temp_dir, filename)
                if os.path.getmtime(file_path) < current_time - 86400:  # 24小时 = 86400秒
                    try:
                        os.remove(file_path)
                        self.logger.info(f"已删除过期文件: {file_path}")
                    except Exception as e:
                        self.logger.warning(f"删除过期文件失败: {file_path}, 错误: {str(e)}")
                        
        except Exception as e:
            self.logger.error(f"清理临时文件失败: {str(e)}")

    def _validate_config(self) -> bool:
        """验证配置是否完整有效
        
        Returns:
            bool: 配置是否有效
        """
        try:
            # 检查临时目录
            if not os.path.exists(self.temp_dir):
                self.logger.error(f"临时目录不存在: {self.temp_dir}")
                return False
                
            if not os.access(self.temp_dir, os.W_OK):
                self.logger.error(f"临时目录无写入权限: {self.temp_dir}")
                return False
                
            # 检查模板文件
            if not os.path.exists(self.template_path):
                self.logger.error(f"模板文件不存在: {self.template_path}")
                return False
                
            # 验证模板内容
            try:
                template_content = self._load_template()
                if not template_content:
                    self.logger.error("模板内容加载失败")
                    return False
            except Exception as e:
                self.logger.error(f"验证模板失败: {str(e)}")
                return False
                
            self.logger.info("配置验证通过")
            return True
            
        except Exception as e:
            self.logger.error(f"验证配置时发生错误: {str(e)}")
            return False
