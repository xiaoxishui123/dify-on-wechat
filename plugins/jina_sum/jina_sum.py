# encoding:utf-8
import json
import os
import html
import re
from urllib.parse import urlparse
import time
import random
import asyncio
import nest_asyncio
import requests
from newspaper import Article
import newspaper
from bs4 import BeautifulSoup

# 导入requests_html用于动态内容提取
from requests_html import HTMLSession

# 应用nest_asyncio以解决事件循环问题
try:
    nest_asyncio.apply()
except Exception as e:
    logger.warning(f"[JinaSum] 无法应用nest_asyncio: {str(e)}")

import plugins
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from plugins import *

@plugins.register(
    name="JinaSum",
    desire_priority=10,
    hidden=False,
    enabled=False,
    desc="Sum url link content with jina reader and llm",
    version="0.0.1",
    author="hanfangyuan",
)
class JinaSum(Plugin):

    jina_reader_base = "https://r.jina.ai"
    open_ai_api_base = "https://api.openai.com/v1"
    open_ai_model = "gpt-3.5-turbo"
    max_words = 8000
    prompt = "我需要对下面引号内文档进行总结，总结输出包括以下三个部分：\n📖 一句话总结\n🔑 关键要点,用数字序号列出3-5个文章的核心内容\n🏷 标签: #xx #xx\n请使用emoji让你的表达更生动\n\n"
    white_url_list = []
    black_url_list = [
        "https://support.weixin.qq.com", # 视频号视频
        "https://channels-aladin.wxqcloud.qq.com", # 视频号音乐
    ]

    def __init__(self):
        super().__init__()
        try:
            self.config = super().load_config()
            if not self.config:
                self.config = self._load_config_template()
            self.jina_reader_base = self.config.get("jina_reader_base", self.jina_reader_base)
            self.open_ai_api_base = self.config.get("open_ai_api_base", self.open_ai_api_base)
            self.open_ai_api_key = self.config.get("open_ai_api_key", "")
            self.open_ai_model = self.config.get("open_ai_model", self.open_ai_model)
            self.max_words = self.config.get("max_words", self.max_words)
            self.prompt = self.config.get("prompt", self.prompt)
            self.white_url_list = self.config.get("white_url_list", self.white_url_list)
            self.black_url_list = self.config.get("black_url_list", self.black_url_list)
            logger.info(f"[JinaSum] inited, config={self.config}")
            self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
        except Exception as e:
            logger.error(f"[JinaSum] 初始化异常：{e}")
            raise "[JinaSum] init failed, ignore "

    def on_handle_context(self, e_context: EventContext, retry_count: int = 0):
        try:
            context = e_context["context"]
            content = context.content
            if context.type != ContextType.SHARING and context.type != ContextType.TEXT:
                return
            if not self._check_url(content):
                logger.debug(f"[JinaSum] {content} is not a valid url, skip")
                return
            if retry_count == 0:
                logger.debug("[JinaSum] on_handle_context. content: %s" % content)
                reply = Reply(ReplyType.TEXT, "🎉正在为您生成总结，请稍候...")
                channel = e_context["channel"]
                channel.send(reply, context)

            target_url = html.unescape(content) # 解决公众号卡片链接校验问题，参考 https://github.com/fatwang2/sum4all/commit/b983c49473fc55f13ba2c44e4d8b226db3517c45

            # 先尝试使用newspaper3k提取内容
            target_url_content = None
            
            # 使用newspaper3k
            logger.debug("[JinaSum] 尝试使用newspaper3k提取内容")
            target_url_content = self._get_content_via_newspaper(target_url)
            
            # 如果newspaper3k提取失败，尝试使用通用方法
            if not target_url_content:
                logger.debug("[JinaSum] newspaper3k提取失败，尝试使用通用方法")
                target_url_content = self._extract_content_general(target_url)
            
            # 如果前两种方法都失败，使用jina提取
            if not target_url_content:
                logger.debug("[JinaSum] 所有方法都失败，回退到使用jina提取")
                target_url_content = self._extract_content_by_jina(target_url)
            
            if not target_url_content:
                logger.error("[JinaSum] 所有方法都失败，无法提取内容")
                reply = Reply(ReplyType.ERROR, "我暂时无法总结链接，请稍后再试")
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                return

            # 清洗网页内容
            if target_url_content:
                target_url_content = self._clean_content(target_url_content)
            
            # 获取API参数
            openai_chat_url = self._get_openai_chat_url()
            openai_headers = self._get_openai_headers()
            openai_payload = self._get_openai_payload(target_url_content)
            logger.debug(f"[JinaSum] openai_chat_url: {openai_chat_url}, openai_headers: {openai_headers}, openai_payload: {openai_payload}")
            
            # 发送请求获取摘要
            response = requests.post(openai_chat_url, headers=openai_headers, json=openai_payload, timeout=60)
            response.raise_for_status()
            result = response.json()['choices'][0]['message']['content']
            
            # 构建回复
            reply = Reply(ReplyType.TEXT, result)
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS

        except Exception as e:
            if retry_count < 3:
                logger.warning(f"[JinaSum] {str(e)}, retry {retry_count + 1}")
                self.on_handle_context(e_context, retry_count + 1)
                return

            logger.exception(f"[JinaSum] {str(e)}")
            reply = Reply(ReplyType.ERROR, "我暂时无法总结链接，请稍后再试")
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS

    def get_help_text(self, verbose, **kwargs):
        return f'使用多种网页内容提取方式和ChatGPT总结网页链接内容'

    def _load_config_template(self):
        logger.debug("No Suno plugin config.json, use plugins/jina_sum/config.json.template")
        try:
            plugin_config_path = os.path.join(self.path, "config.json.template")
            if os.path.exists(plugin_config_path):
                with open(plugin_config_path, "r", encoding="utf-8") as f:
                    plugin_conf = json.load(f)
                    return plugin_conf
        except Exception as e:
            logger.exception(e)

    def _get_jina_url(self, target_url):
        return self.jina_reader_base + "/" + target_url

    def _extract_content_by_jina(self, target_url):
        """使用Jina Reader提取URL内容
        
        Args:
            target_url: 目标URL
            
        Returns:
            str: 提取的内容文本
            
        Raises:
            Exception: 当请求失败时抛出异常
        """
        try:
            logger.debug(f"[JinaSum] 使用Jina提取内容: {target_url}")
            jina_url = self._get_jina_url(target_url)
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"}
            response = requests.get(jina_url, headers=headers, timeout=60)
            response.raise_for_status()
            return response.text
        except Exception as e:
            logger.error(f"[JinaSum] Jina提取失败: {str(e)}")
            return None

    # 以下网页内容提取功能参考了 https://github.com/sofs2005/jina_sum
    def _get_content_via_newspaper(self, url):
        """使用newspaper3k库提取文章内容
        
        Args:
            url: 文章URL
            
        Returns:
            str: 文章内容,失败返回None
        """
        try:
            # 处理B站短链接
            if "b23.tv" in url:
                # 先获取重定向后的真实URL
                try:
                    logger.debug(f"[JinaSum] 解析B站短链接: {url}")
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
                    }
                    response = requests.head(url, headers=headers, allow_redirects=True, timeout=10)
                    if response.status_code == 200:
                        real_url = response.url
                        logger.debug(f"[JinaSum] B站短链接解析结果: {real_url}")
                        url = real_url
                except Exception as e:
                    logger.error(f"[JinaSum] 解析B站短链接失败: {str(e)}")
            
            # 选择随机User-Agent
            user_agents = [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0"
            ]
            selected_ua = random.choice(user_agents)
            
            # 构建请求头
            headers = {
                "User-Agent": selected_ua,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
            }
            
            # 微信公众号文章特殊处理
            if "mp.weixin.qq.com" in url:
                try:
                    # 添加微信Cookie参数
                    cookies = {
                        "appmsglist_action_" + str(int(time.time())): "card",
                        "pac_uid": f"{int(time.time())}_f{random.randint(10000, 99999)}",
                    }
                    
                    # 直接请求
                    session = requests.Session()
                    response = session.get(url, headers=headers, cookies=cookies, timeout=20)
                    response.raise_for_status()
                    
                    # 使用BeautifulSoup解析
                    soup = BeautifulSoup(response.content, 'html.parser')
                    
                    # 查找微信文章元素
                    title_elem = soup.select_one('#activity-name')
                    author_elem = soup.select_one('#js_name') or soup.select_one('#js_profile_qrcode > div > strong')
                    content_elem = soup.select_one('#js_content')
                    
                    if content_elem:
                        # 移除无用元素
                        for remove_elem in content_elem.select('script, style, svg'):
                            remove_elem.extract()
                            
                        # 获取所有文本
                        text_content = content_elem.get_text(separator='\n', strip=True)
                        
                        if text_content and len(text_content) > 200:
                            title = title_elem.get_text(strip=True) if title_elem else ""
                            author = author_elem.get_text(strip=True) if author_elem else "未知作者"
                            
                            # 构建内容
                            full_content = ""
                            if title:
                                full_content += f"标题: {title}\n"
                            if author and author != "未知作者":
                                full_content += f"作者: {author}\n"
                            full_content += f"\n{text_content}"
                            
                            logger.debug(f"[JinaSum] 成功提取微信文章内容，长度: {len(text_content)}")
                            return full_content
                except Exception as e:
                    logger.error(f"[JinaSum] 直接提取微信文章失败: {str(e)}")
            
            # 配置newspaper
            newspaper.Config().browser_user_agent = selected_ua
            newspaper.Config().request_timeout = 30
            newspaper.Config().fetch_images = False
            
            # 尝试使用newspaper提取
            try:
                # 创建Article对象
                article = Article(url, language='zh')
                
                # 手动下载
                session = requests.Session()
                response = session.get(url, headers=headers, timeout=30)
                response.raise_for_status()
                
                # 设置html内容
                article.html = response.text
                article.download_state = 2  # 下载完成
                
                # 解析
                article.parse()
            except Exception as e:
                logger.error(f"[JinaSum] 自定义下载失败，使用标准方法: {str(e)}")
                article = Article(url, language='zh')
                article.download()
                article.parse()
            
            # 获取内容
            title = article.title
            authors = ', '.join(article.authors) if article.authors else "未知作者"
            publish_date = article.publish_date.strftime("%Y-%m-%d") if article.publish_date else "未知日期"
            content = article.text
            
            # 如果内容为空或过短，尝试直接从HTML获取
            if not content or len(content) < 500:
                logger.debug("[JinaSum] Article内容太短，直接从HTML提取")
                try:
                    soup = BeautifulSoup(article.html, 'html.parser')
                    
                    # 移除脚本和样式
                    for script in soup(["script", "style"]):
                        script.extract()
                    
                    # 获取所有文本
                    text = soup.get_text(separator='\n', strip=True)
                    
                    # 如果内容更长，使用它
                    if len(text) > len(content):
                        content = text
                        logger.debug(f"[JinaSum] 使用BeautifulSoup提取的内容: {len(content)}字符")
                except Exception as bs_error:
                    logger.error(f"[JinaSum] BeautifulSoup提取失败: {str(bs_error)}")
            
            # 合成最终内容
            if title:
                full_content = f"标题: {title}\n"
                if authors and authors != "未知作者":
                    full_content += f"作者: {authors}\n"
                if publish_date and publish_date != "未知日期":
                    full_content += f"发布日期: {publish_date}\n"
                full_content += f"\n{content}"
            else:
                full_content = content
            
            if not full_content or len(full_content.strip()) < 50:
                logger.debug("[JinaSum] newspaper没有提取到内容")
                return None
                
            logger.debug(f"[JinaSum] newspaper成功提取内容，长度: {len(full_content)}")
            return full_content
            
        except Exception as e:
            logger.error(f"[JinaSum] newspaper提取内容出错: {str(e)}")
            return None

    def _extract_content_general(self, url):
        """通用网页内容提取方法
        
        Args:
            url: 网页URL
            
        Returns:
            str: 提取的内容，失败返回None
        """
        try:
            from bs4 import BeautifulSoup
            
            # 获取默认头信息
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7"
            }
            
            # 添加随机延迟
            time.sleep(random.uniform(0.5, 2))
            
            # 创建会话
            session = requests.Session()
            
            # 发送请求
            logger.debug(f"[JinaSum] 通用方法请求: {url}")
            response = session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            # 确保编码正确
            if response.encoding == 'ISO-8859-1':
                response.encoding = response.apparent_encoding
                
            # 解析HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 移除无用元素
            for element in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'form', 'iframe']):
                element.extract()
            
            # 查找标题
            title = None
            title_candidates = [
                soup.select_one('h1'),
                soup.select_one('title'),
                soup.select_one('.title'),
                soup.select_one('.article-title'),
                soup.select_one('[class*="title" i]'),
            ]
            
            for candidate in title_candidates:
                if candidate and candidate.text.strip():
                    title = candidate.text.strip()
                    break
            
            # 查找内容
            content_candidates = []
            content_selectors = [
                'article', 'main', '.content', '.article', '.post-content',
                '[class*="content" i]', '[class*="article" i]',
                '#content', '#article', '.body'
            ]
            
            for selector in content_selectors:
                elements = soup.select(selector)
                if elements:
                    content_candidates.extend(elements)
            
            # 如果没找到，寻找文本最多的div
            if not content_candidates:
                paragraphs = {}
                for elem in soup.find_all(['p', 'div']):
                    text = elem.get_text(strip=True)
                    if len(text) > 100:
                        paragraphs[elem] = len(text)
                
                if paragraphs:
                    max_elem = max(paragraphs.items(), key=lambda x: x[1])[0]
                    if max_elem.name == 'div':
                        content_candidates.append(max_elem)
                    else:
                        parent = max_elem.parent
                        if parent and len(parent.find_all('p')) > 3:
                            content_candidates.append(parent)
                        else:
                            content_candidates.append(max_elem)
            
            # 评分选择最佳内容
            best_content = None
            max_score = 0
            
            for element in content_candidates:
                # 计算文本长度
                text = element.get_text(strip=True)
                text_length = len(text)
                
                # 计算文本密度
                html_length = len(str(element))
                text_density = text_length / html_length if html_length > 0 else 0
                
                # 计算段落数量
                paragraphs = element.find_all('p')
                paragraph_count = len(paragraphs)
                
                # 评分
                score = (
                    text_length * 1.0 +
                    text_density * 100 +
                    paragraph_count * 30
                )
                
                # 减分：链接过多
                links = element.find_all('a')
                link_text_ratio = sum(len(a.get_text(strip=True)) for a in links) / text_length if text_length > 0 else 0
                if link_text_ratio > 0.5:
                    score *= 0.5
                
                # 更新最佳内容
                if score > max_score:
                    max_score = score
                    best_content = element
            
            # 提取内容
            static_content_result = None
            if best_content:
                # 移除广告
                for ad in best_content.select('[class*="ad" i], [class*="banner" i], [id*="ad" i], [class*="recommend" i]'):
                    ad.extract()
                
                # 获取文本
                content_text = best_content.get_text(separator='\n', strip=True)
                
                # 清理多余空行
                content_text = re.sub(r'\n{3,}', '\n\n', content_text)
                
                # 构建结果
                result = ""
                if title:
                    result += f"标题: {title}\n\n"
                
                result += content_text
                
                logger.debug(f"[JinaSum] 通用方法成功，内容长度: {len(result)}")
                static_content_result = result
            
            # 判断静态提取的内容质量
            content_is_good = False
            if static_content_result:
                # 内容长度检查
                if len(static_content_result) > 1000:
                    content_is_good = True
                # 结构检查 - 至少应该有多个段落
                elif static_content_result.count('\n\n') >= 3:
                    content_is_good = True
            
            # 如果静态提取内容质量不佳，尝试动态提取
            if not content_is_good:
                logger.debug("[JinaSum] 静态提取内容质量不佳，尝试动态提取")
                dynamic_content = self._extract_dynamic_content(url, headers)
                if dynamic_content:
                    logger.debug(f"[JinaSum] 动态提取成功，内容长度: {len(dynamic_content)}")
                    return dynamic_content
            
            return static_content_result
                
        except Exception as e:
            logger.error(f"[JinaSum] 通用提取方法失败: {str(e)}")
            return None

    def _extract_dynamic_content(self, url, headers=None):
        """使用JavaScript渲染提取动态页面内容
        
        Args:
            url: 网页URL
            headers: 可选的请求头
            
        Returns:
            str: 提取的内容，失败返回None
        """
        try:
            logger.debug(f"[JinaSum] 开始动态提取内容: {url}")
            
            # 创建会话并设置超时
            session = HTMLSession()
            
            # 如果没有提供headers，使用默认值
            if not headers:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7"
                }
            
            # 获取页面
            response = session.get(url, headers=headers, timeout=30)
            
            # 执行JavaScript (设置超时，防止无限等待)
            logger.debug("[JinaSum] 开始执行JavaScript")
            response.html.render(timeout=20, sleep=2)
            logger.debug("[JinaSum] JavaScript执行完成")
            
            # 处理渲染后的HTML
            rendered_html = response.html.html
            
            # 使用BeautifulSoup解析渲染后的HTML
            soup = BeautifulSoup(rendered_html, 'html.parser')
            
            # 清理无用元素
            for element in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
                element.extract()
            
            # 查找标题
            title = None
            title_candidates = [
                soup.select_one('h1'),
                soup.select_one('title'),
                soup.select_one('.title'),
                soup.select_one('[class*="title" i]'),
            ]
            
            for candidate in title_candidates:
                if candidate and candidate.text.strip():
                    title = candidate.text.strip()
                    break
            
            # 寻找主要内容
            main_content = None
            
            # 1. 尝试找主要内容容器
            main_selectors = [
                'article', 'main', '.content', '.article',
                '[class*="content" i]', '[class*="article" i]',
                '#content', '#article'
            ]
            
            for selector in main_selectors:
                elements = soup.select(selector)
                if elements:
                    # 选择包含最多文本的元素
                    main_content = max(elements, key=lambda x: len(x.get_text()))
                    break
            
            # 2. 如果没找到，寻找文本最多的div
            if not main_content:
                paragraphs = {}
                for elem in soup.find_all(['div']):
                    text = elem.get_text(strip=True)
                    if len(text) > 200:  # 只考虑长文本
                        paragraphs[elem] = len(text)
                
                if paragraphs:
                    main_content = max(paragraphs.items(), key=lambda x: x[1])[0]
            
            # 3. 如果还是没找到，使用整个body
            if not main_content:
                main_content = soup.body
            
            # 从主要内容中提取文本
            if main_content:
                # 清理可能的广告或无关元素
                for ad in main_content.select('[class*="ad" i], [class*="banner" i], [id*="ad" i], [class*="recommend" i]'):
                    ad.extract()
                
                # 获取文本
                content_text = main_content.get_text(separator='\n', strip=True)
                content_text = re.sub(r'\n{3,}', '\n\n', content_text)  # 清理多余空行
                
                # 构建最终结果
                result = ""
                if title:
                    result += f"标题: {title}\n\n"
                result += content_text
                
                # 关闭会话
                session.close()
                
                return result
            
            # 关闭会话
            session.close()
            
            return None
            
        except Exception as e:
            logger.error(f"[JinaSum] 动态提取失败: {str(e)}")
            return None

    def _clean_content(self, content: str) -> str:
        """清洗内容，去除无用信息
        
        Args:
            content: 原始内容
            
        Returns:
            str: 清洗后的内容
        """
        if not content:
            return content
            
        # 记录原始长度
        original_length = len(content)
        
        # 移除Markdown图片标签
        content = re.sub(r'!\[.*?\]\(.*?\)', '', content)
        content = re.sub(r'\[!\[.*?\]\(.*?\)', '', content)
        
        # 移除图片描述
        content = re.sub(r'\[图片\]|\[image\]|\[img\]|\[picture\]', '', content, flags=re.IGNORECASE)
        content = re.sub(r'\[.*?图片.*?\]', '', content)
        
        # 移除元数据
        content = re.sub(r'本文字数：\d+，阅读时长大约\d+分钟', '', content)
        content = re.sub(r'阅读时长[:：].*?分钟', '', content)
        content = re.sub(r'字数[:：]\d+', '', content)
        
        # 移除日期和时间戳
        content = re.sub(r'\d{4}[\.年/-]\d{1,2}[\.月/-]\d{1,2}[日号]?(\s+\d{1,2}:\d{1,2}(:\d{1,2})?)?', '', content)
        
        # 移除分隔线
        content = re.sub(r'\*\s*\*\s*\*', '', content)
        content = re.sub(r'-{3,}', '', content)
        content = re.sub(r'_{3,}', '', content)
        
        # 移除广告标记
        ad_patterns = [
            r'广告\s*[\.。]?', 
            r'赞助内容', 
            r'sponsored content',
            r'advertisement',
            r'推广信息',
            r'\[广告\]',
            r'【广告】',
        ]
        for pattern in ad_patterns:
            content = re.sub(pattern, '', content, flags=re.IGNORECASE)
        
        # 移除URL链接
        content = re.sub(r'https?://\S+', '', content)
        content = re.sub(r'www\.\S+', '', content)
        
        # 清理Markdown格式
        content = re.sub(r'\*\*(.+?)\*\*', r'\1', content)
        content = re.sub(r'\*(.+?)\*', r'\1', content)
        content = re.sub(r'`(.+?)`', r'\1', content)
        
        # 清理文章尾部
        content = re.sub(r'\*\*微信编辑\*\*.*?$', '', content, flags=re.MULTILINE)
        content = re.sub(r'\*\*推荐阅读\*\*.*?$', '', content, flags=re.MULTILINE | re.DOTALL)
        
        # 清理多余空白
        content = re.sub(r'\n{3,}', '\n\n', content)
        content = re.sub(r'\s{2,}', ' ', content)
        content = re.sub(r'^\s+', '', content, flags=re.MULTILINE)
        content = re.sub(r'\s+$', '', content, flags=re.MULTILINE)
        
        # 记录清洗后长度
        cleaned_length = len(content)
        logger.debug(f"[JinaSum] 内容清洗: 原始长度={original_length}, 清洗后长度={cleaned_length}, 减少={original_length - cleaned_length}")
        
        return content

    def _get_openai_chat_url(self):
        return self.open_ai_api_base + "/chat/completions"

    def _get_openai_headers(self):
        return {
            'Authorization': f"Bearer {self.open_ai_api_key}",
            'Host': urlparse(self.open_ai_api_base).netloc
        }

    def _get_openai_payload(self, target_url_content):
        target_url_content = target_url_content[:self.max_words] # 通过字符串长度简单进行截断
        sum_prompt = f"{self.prompt}\n\n'''{target_url_content}'''"
        messages = [{"role": "user", "content": sum_prompt}]
        payload = {
            'model': self.open_ai_model,
            'messages': messages
        }
        return payload

    def _check_url(self, target_url: str):
        stripped_url = target_url.strip()
        # 简单校验是否是url
        if not stripped_url.startswith("http://") and not stripped_url.startswith("https://"):
            return False

        # 检查白名单
        if len(self.white_url_list):
            if not any(stripped_url.startswith(white_url) for white_url in self.white_url_list):
                return False

        # 排除黑名单，黑名单优先级>白名单
        for black_url in self.black_url_list:
            if stripped_url.startswith(black_url):
                return False

        return True