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
from plugins.event import EventAction
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
        self.rounded_corner_radius = 20  # 新增圆角半径配置
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
            self.rounded_corner_radius = config.get("rounded_corner_radius", 20)  # 读取圆角半径配置

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
        """初始化插件
        """
        super().__init__()
        self.logger = logging.getLogger('ChinesePUA')
        
        # 设置日志
        if not self.logger.handlers:  # 避免重复添加处理器
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
        
        self.logger.setLevel(logging.INFO)  # 默认INFO级别，可在配置中修改
        self.logger.info("[ChinesePUA] 插件初始化开始")
        
        # 插件配置
        self.plugin_config = {}
        pdir = os.path.dirname(os.path.abspath(__file__))
        self.logger.info(f"[ChinesePUA] 插件目录: {pdir}")
        
        # 命令字典 - 将被get_event_handler使用
        self.commands = {
            "解释": self.explain_handler,
            "吐槽": self.explain_handler,
            "解字": self.explain_handler
        }
        
        # EventContext处理的优先级
        self.priority = 100
        
        self.logger.info("[ChinesePUA] 插件注册了命令: " + ", ".join(list(self.commands.keys())))
        self.logger.info("[ChinesePUA] 插件初始化完成")
        
        # 注册事件处理器
        self.handlers[Event.ON_HANDLE_CONTEXT] = self.handle_event
        self.logger.info(f"[ChinesePUA] 已注册事件处理器: {self.handlers.keys()}")
        
        # 初始化配置和目录
        try:
            config_path = os.path.join(os.path.dirname(__file__), 'config.json')
            self.logger.info(f"[ChinesePUA] 配置文件路径: {config_path}")
            self.config = ChinesePuaConfig(config_path)
            self.temp_dir = TmpDir().path()
            self.logger.info(f"[ChinesePUA] 临时目录路径: {self.temp_dir}")
            self._ensure_temp_dir()
            
            # 加载并缓存HTML模板
            self.template_path = os.path.join(os.path.dirname(__file__), 'template_card.html')
            self.logger.info(f"[ChinesePUA] 模板文件路径: {self.template_path}")
            self.logger.info(f"[ChinesePUA] 模板文件路径是否为None: {self.template_path is None}")
            self.template_content = self._load_template()
            
            # 验证配置
            if not self._validate_config():
                raise RuntimeError("配置验证失败")
            
            self.logger.info("=== [ChinesePUA] 插件初始化成功 ===")
            
        except Exception as e:
            self.logger.error(f"[ChinesePUA] 插件初始化失败: {str(e)}", exc_info=True)
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

    def _generate_translations(self, keyword: str) -> dict:
        """生成拼音、英文、日文翻译
        
        Args:
            keyword: 需要翻译的关键词
            
        Returns:
            dict: 包含拼音、英文、日文翻译的字典
        """
        try:
            # 首先尝试从预设字典获取翻译
            dict_result = self._get_dict_translations(keyword)
            
            # 如果字典中有完整翻译，直接返回
            if dict_result['from_dict']:
                self.logger.info(f"[翻译] 使用字典翻译: {keyword}")
                return dict_result
            
            # 检查是否启用AI翻译
            if self.plugin_config.get("enable_ai_translation", True):
                # 使用AI生成翻译
                self.logger.info(f"[翻译] 字典中未找到'{keyword}'，使用AI生成翻译")
                ai_result = self._generate_ai_translations(keyword)
                
                # 如果AI生成成功，返回AI结果
                if ai_result['success']:
                    return ai_result
            else:
                self.logger.info(f"[翻译] AI翻译已禁用，跳过AI翻译")
            
            # AI生成失败时，返回字典的部分结果（至少有拼音）
            self.logger.warning(f"[翻译] AI翻译失败，使用字典部分结果")
            return dict_result
            
        except Exception as e:
            self.logger.error(f"生成翻译失败: {str(e)}")
            # 返回默认值
            return {
                'pinyin': keyword,
                'english': keyword,
                'japanese': keyword,
                'text_char': keyword[0] if keyword else keyword,
                'from_dict': False,
                'success': False
            }

    def _get_dict_translations(self, keyword: str) -> dict:
        """从预设字典获取翻译
        
        Args:
            keyword: 需要翻译的关键词
            
        Returns:
            dict: 包含翻译结果和是否来自字典的标识
        """
        try:
            # 扩展拼音字典 - 更全面的汉字拼音映射
            pinyin_dict = {
                # 原有词汇
                '内': 'Nèi', '卷': 'Juǎn',
                '加': 'Jiā', '班': 'Bān',
                '摸': 'Mō', '鱼': 'Yú',
                '打': 'Dǎ', '工': 'Gōng',
                '社': 'Shè', '交': 'Jiāo',
                '考': 'Kǎo', '试': 'Shì',
                '恋': 'Liàn', '爱': 'Ài',
                '相': 'Xiāng', '亲': 'Qīn',
                '房': 'Fáng', '贷': 'Dài',
                '存': 'Cún', '钱': 'Qián',
                '熬': 'Áo', '夜': 'Yè',
                '下': 'Xià', '班': 'Bān',
                '工': 'Gōng', '资': 'Zī',
                '会': 'Huì', '议': 'Yì',
                '周': 'Zhōu', '一': 'Yī',
                '假': 'Jià', '期': 'Qī',
                '摇': 'Yáo', '号': 'Hào',
                '外': 'Wài', '卖': 'Mài',
                '回': 'Huí', '家': 'Jiā',
                '精': 'Jīng', '神': 'Shén', '股': 'Gǔ', '东': 'Dōng',
                '委': 'Wěi', '婉': 'Wǎn',
                '杠': 'Gàng', '杆': 'Gǎn',
                # 新增常用字
                '自': 'Zì', '由': 'Yóu', '职': 'Zhí', '业': 'Yè',
                '互': 'Hù', '联': 'Lián', '网': 'Wǎng', 
                '创': 'Chuàng', '新': 'Xīn', '企': 'Qǐ',
                '人': 'Rén', '生': 'Shēng', '活': 'Huó',
                '学': 'Xué', '习': 'Xí', '成': 'Chéng', '长': 'Zhǎng',
                '梦': 'Mèng', '想': 'Xiǎng', '未': 'Wèi', '来': 'Lái',
                '青': 'Qīng', '春': 'Chūn', '年': 'Nián', '轻': 'Qīng',
                '奋': 'Fèn', '斗': 'Dòu', '努': 'Nǔ', '力': 'Lì',
                '成': 'Chéng', '功': 'Gōng', '失': 'Shī', '败': 'Bài',
                '压': 'Yā', '力': 'Lì', '焦': 'Jiāo', '虑': 'Lǜ',
                '快': 'Kuài', '乐': 'Lè', '幸': 'Xìng', '福': 'Fú',
                '友': 'Yǒu', '谊': 'Yì', '朋': 'Péng', '友': 'Yǒu',
                '时': 'Shí', '间': 'Jiān', '空': 'Kōng', '闲': 'Xián',
                '金': 'Jīn', '钱': 'Qián', '财': 'Cái', '富': 'Fù',
                '健': 'Jiàn', '康': 'Kāng', '身': 'Shēn', '体': 'Tǐ',
                '旅': 'Lǚ', '行': 'Xíng', '游': 'Yóu', '玩': 'Wán',
                '美': 'Měi', '食': 'Shí', '吃': 'Chī', '喝': 'Hē',
                '睡': 'Shuì', '觉': 'Jiào', '休': 'Xiū', '息': 'Xī',
                '购': 'Gòu', '物': 'Wù', '买': 'Mǎi', '卖': 'Mài',
                '手': 'Shǒu', '机': 'Jī', '电': 'Diàn', '脑': 'Nǎo',
                '网': 'Wǎng', '络': 'Luò', '线': 'Xiàn', '上': 'Shàng',
                '文': 'Wén', '化': 'Huà', '艺': 'Yì', '术': 'Shù',
                '音': 'Yīn', '乐': 'Yuè', '电': 'Diàn', '影': 'Yǐng',
                '书': 'Shū', '本': 'Běn', '阅': 'Yuè', '读': 'Dú',
                '运': 'Yùn', '动': 'Dòng', '健': 'Jiàn', '身': 'Shēn',
                '天': 'Tiān', '气': 'Qì', '季': 'Jì', '节': 'Jié',
                '城': 'Chéng', '市': 'Shì', '乡': 'Xiāng', '村': 'Cūn',
                '交': 'Jiāo', '通': 'Tōng', '出': 'Chū', '租': 'Zū',
                '地': 'Dì', '铁': 'Tiě', '公': 'Gōng', '交': 'Jiāo',
                '医': 'Yī', '院': 'Yuàn', '看': 'Kàn', '病': 'Bìng',
                '药': 'Yào', '店': 'Diàn', '感': 'Gǎn', '冒': 'Mào',
                '银': 'Yín', '行': 'Háng', '存': 'Cún', '款': 'Kuǎn',
                '贷': 'Dài', '款': 'Kuǎn', '信': 'Xìn', '用': 'Yòng',
                '保': 'Bǎo', '险': 'Xiǎn', '投': 'Tóu', '资': 'Zī',
                # 新增网络词汇相关拼音
                '天': 'Tiān', '选': 'Xuǎn', '打': 'Dǎ', '工': 'Gōng', '人': 'Rén',
                '网': 'Wǎng', '络': 'Luò', '梗': 'Gěng',
                '流': 'Liú', '行': 'Xíng', '段': 'Duàn', '子': 'Zi',
                '表': 'Biǎo', '情': 'Qíng', '包': 'Bāo',
                '弹': 'Dàn', '幕': 'Mù', '直': 'Zhí', '播': 'Bō',
                '博': 'Bó', '主': 'Zhǔ', '红': 'Hóng',
                '粉': 'Fěn', '丝': 'Sī', '点': 'Diǎn', '赞': 'Zàn',
                '转': 'Zhuǎn', '发': 'Fā', '评': 'Píng', '论': 'Lùn',
                '热': 'Rè', '搜': 'Sōu', '话': 'Huà', '题': 'Tí',
                '趋': 'Qū', '势': 'Shì'
            }
            
            # 生成拼音
            pinyin_chars = []
            for char in keyword:
                if char in pinyin_dict:
                    pinyin_chars.append(pinyin_dict[char])
                else:
                    # 如果字典中没有，尝试简单的音译
                    pinyin_chars.append(self._simple_pinyin_fallback(char))
            pinyin = ' '.join(pinyin_chars)
            
            # 扩展的英文翻译映射
            english_dict = {
                '内卷': 'Involution',
                '加班': 'Overtime',
                '摸鱼': 'Slack off',
                '打工': 'Work',
                '社交': 'Social',
                '考试': 'Exam',
                '恋爱': 'Love',
                '相亲': 'Blind date',
                '房贷': 'Mortgage',
                '存钱': 'Save money',
                '熬夜': 'Stay up late',
                '下班': 'Off work',
                '工资': 'Salary',
                '会议': 'Meeting',
                '周一': 'Monday',
                '假期': 'Holiday',
                'deadline': 'Deadline',
                '摇号': 'Lottery',
                '外卖': 'Takeout',
                '回家': 'Go home',
                '精神股东': 'Spiritual Shareholder',
                '委婉': 'Euphemism',
                '杠杆': 'Leverage',
                # 新增词汇
                '自由职业': 'Freelance',
                '互联网': 'Internet',
                '创新': 'Innovation',
                '人生': 'Life',
                '学习': 'Learning',
                '成长': 'Growth',
                '梦想': 'Dream',
                '未来': 'Future',
                '青春': 'Youth',
                '奋斗': 'Struggle',
                '成功': 'Success',
                '失败': 'Failure',
                '压力': 'Pressure',
                '焦虑': 'Anxiety',
                '快乐': 'Happiness',
                '幸福': 'Wellbeing',
                '友谊': 'Friendship',
                '时间': 'Time',
                '金钱': 'Money',
                '健康': 'Health',
                '旅行': 'Travel',
                '美食': 'Cuisine',
                '睡觉': 'Sleep',
                '购物': 'Shopping',
                '手机': 'Mobile',
                '网络': 'Network',
                '文化': 'Culture',
                '音乐': 'Music',
                '阅读': 'Reading',
                '运动': 'Exercise',
                '天气': 'Weather',
                '城市': 'City',
                '交通': 'Traffic',
                '医院': 'Hospital',
                '银行': 'Bank',
                '投资': 'Investment',
                # 新增网络流行词汇
                '天选打工人': 'Chosen Worker',
                '网络梗': 'Internet Meme',
                '打工人': 'Worker',
                '天选': 'Chosen One',
                '梗': 'Meme',
                '网络': 'Network',
                '流行': 'Popular',
                '段子': 'Joke',
                '表情包': 'Emoji Pack',
                '弹幕': 'Bullet Comments',
                '直播': 'Live Stream',
                '博主': 'Blogger',
                '网红': 'Internet Celebrity',
                '粉丝': 'Fans',
                '点赞': 'Like',
                '转发': 'Share',
                '评论': 'Comment',
                '热搜': 'Hot Search',
                '话题': 'Topic',
                '趋势': 'Trend'
            }
            
            # 扩展的日文翻译映射
            japanese_dict = {
                '内卷': 'ないかん',
                '加班': '残業',
                '摸鱼': 'サボる',
                '打工': 'アルバイト',
                '社交': '社交',
                '考试': '試験',
                '恋爱': '恋愛',
                '相亲': 'お見合い',
                '房贷': '住宅ローン',
                '存钱': '貯金',
                '熬夜': '夜更かし',
                '下班': '退勤',
                '工资': '給料',
                '会议': '会議',
                '周一': '月曜日',
                '假期': '休暇',
                'deadline': 'デッドライン',
                '摇号': '抽選',
                '外卖': '出前',
                '回家': '帰宅',
                '精神股东': 'スピリチュアル株主',
                '委婉': '婉曲',
                '杠杆': 'レバレッジ',
                # 新增词汇
                '自由职业': 'フリーランス',
                '互联网': 'インターネット',
                '创新': '革新',
                '人生': '人生',
                '学习': '学習',
                '成长': '成長',
                '梦想': '夢',
                '未来': '未来',
                '青春': '青春',
                '奋斗': '奮闘',
                '成功': '成功',
                '失败': '失敗',
                '压力': 'プレッシャー',
                '焦虑': '不安',
                '快乐': '楽しさ',
                '幸福': '幸福',
                '友谊': '友情',
                '时间': '時間',
                '金钱': 'お金',
                '健康': '健康',
                '旅行': '旅行',
                '美食': '美食',
                '睡觉': '睡眠',
                '购物': 'ショッピング',
                '手机': 'スマホ',
                '网络': 'ネットワーク',
                '文化': '文化',
                '音乐': '音楽',
                '阅读': '読書',
                '运动': '運動',
                '天气': '天気',
                '城市': '都市',
                '交通': '交通',
                '医院': '病院',
                '银行': '銀行',
                '投资': '投資',
                # 新增网络流行词汇
                '天选打工人': '天選サラリーマン',
                '网络梗': 'ネットミーム',
                '打工人': 'サラリーマン',
                '天选': '天選',
                '梗': 'ミーム',
                '网络': 'ネットワーク',
                '流行': '流行',
                '段子': 'ジョーク',
                '表情包': 'スタンプ',
                '弹幕': 'コメント弾幕',
                '直播': 'ライブ配信',
                '博主': 'ブロガー',
                '网红': 'ネットアイドル',
                '粉丝': 'ファン',
                '点赞': 'いいね',
                '转发': 'シェア',
                '评论': 'コメント',
                '热搜': 'トレンド',
                '话题': 'トピック',
                '趋势': 'トレンド'
            }
            
            english = english_dict.get(keyword, None)
            japanese = japanese_dict.get(keyword, None)
            
            # 取关键词的第一个字符作为背景文字
            text_char = keyword[0] if keyword else keyword
            
            # 判断是否有完整翻译（英文和日文都在字典中）
            has_complete_translation = english is not None and japanese is not None
            
            return {
                'pinyin': pinyin,
                'english': english if english else keyword,
                'japanese': japanese if japanese else keyword,
                'text_char': text_char,
                'from_dict': has_complete_translation,
                'success': True
            }
            
        except Exception as e:
            self.logger.error(f"字典翻译失败: {str(e)}")
            # 返回默认值
            return {
                'pinyin': keyword,
                'english': keyword,
                'japanese': keyword,
                'text_char': keyword[0] if keyword else keyword,
                'from_dict': False,
                'success': False
            }

    def _generate_ai_translations(self, keyword: str) -> dict:
        """使用AI模型生成拼音、英文、日文翻译
        
        Args:
            keyword: 需要翻译的关键词
            
        Returns:
            dict: 包含AI生成的翻译结果
        """
        try:
            self.logger.info(f"[AI翻译] 开始为'{keyword}'生成翻译")
            self.logger.info(f"[AI翻译] self.plugin_config类型: {type(self.plugin_config)}")
            self.logger.info(f"[AI翻译] self.plugin_config内容: {self.plugin_config}")
            
            # 检查配置中的api_base值
            api_base_value = self.plugin_config.get("api_base") if self.plugin_config else None
            self.logger.info(f"[AI翻译] 从配置中获取的api_base: {api_base_value}")
            
            # 构建专门的翻译提示词
            translation_prompt = f"""请为中文词汇"{keyword}"提供准确的翻译信息。

要求：
1. 拼音：提供标准的汉语拼音，包含声调标记
2. 英文翻译：提供最贴切的英文表达，考虑词汇的文化内涵
3. 日文翻译：提供地道的日文表达，可以使用汉字、平假名或片假名

请严格按照以下JSON格式返回，不要添加任何其他内容：
{{
    "pinyin": "标准拼音",
    "english": "英文翻译",
    "japanese": "日文翻译"
}}

示例：
词汇：内卷
{{
    "pinyin": "Nèi Juǎn",
    "english": "Involution",
    "japanese": "ないかん"
}}

现在请为"{keyword}"提供翻译："""

            # 准备API请求参数
            api_params = {
                "model": self.plugin_config.get("api_model", "gpt-4o-mini"),
                "messages": [
                    {
                        "role": "system",
                        "content": "你是一个专业的中英日翻译专家，精通中文、英文和日文的对应关系，能够提供准确、地道的翻译。"
                    },
                    {
                        "role": "user", 
                        "content": translation_prompt
                    }
                ],
                "max_tokens": 200,
                "temperature": 0.1  # 降低随机性，提高翻译一致性
            }
            
            # 只有支持JSON模式的模型才添加response_format
            model_name = self.plugin_config.get("api_model", "gpt-4o-mini")
            if "gpt-4" in model_name or "gpt-3.5" in model_name:
                api_params["response_format"] = {"type": "json_object"}

            # 调用API
            import requests
            import json
            
            headers = {
                "Authorization": f"Bearer {self.plugin_config.get('api_key')}",
                "Content-Type": "application/json"
            }
            
            api_base = self.plugin_config.get("api_base", "https://api.openai.com/v1")
            # 确保API地址正确拼接
            if api_base.endswith("/v1"):
                api_url = f"{api_base}/chat/completions"
            else:
                api_url = f"{api_base}/v1/chat/completions"
            
            self.logger.info(f"[AI翻译] 配置的api_base: {api_base}")
            self.logger.info(f"[AI翻译] 最终API地址: {api_url}")
            
            response = requests.post(
                api_url,
                headers=headers,
                json=api_params,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                content = result['choices'][0]['message']['content']
                
                # 尝试解析JSON响应
                try:
                    translation_data = json.loads(content)
                    
                    # 验证响应格式
                    required_keys = ['pinyin', 'english', 'japanese']
                    if all(key in translation_data for key in required_keys):
                        
                        # 取关键词的第一个字符作为背景文字
                        text_char = keyword[0] if keyword else keyword
                        
                        result_dict = {
                            'pinyin': translation_data['pinyin'],
                            'english': translation_data['english'],
                            'japanese': translation_data['japanese'],
                            'text_char': text_char,
                            'from_dict': False,
                            'success': True
                        }
                        
                        self.logger.info(f"[AI翻译] 成功生成'{keyword}'的翻译: {result_dict}")
                        return result_dict
                    else:
                        self.logger.error(f"[AI翻译] 响应格式不正确: {translation_data}")
                        
                except json.JSONDecodeError as e:
                    self.logger.error(f"[AI翻译] JSON解析失败: {e}, 响应内容: {content}")
                    
                    # JSON解析失败时，尝试手动解析
                    try:
                        translation_result = self._parse_translation_text(content, keyword)
                        if translation_result['success']:
                            self.logger.info(f"[AI翻译] 手动解析成功: {translation_result}")
                            return translation_result
                    except Exception as parse_error:
                        self.logger.error(f"[AI翻译] 手动解析也失败: {parse_error}")
            else:
                self.logger.error(f"[AI翻译] API请求失败: {response.status_code}, {response.text}")
                
        except Exception as e:
            self.logger.error(f"[AI翻译] 生成翻译时发生错误: {str(e)}")
        
        # AI翻译失败，返回失败标识
        return {
            'pinyin': keyword,
            'english': keyword,
            'japanese': keyword,
            'text_char': keyword[0] if keyword else keyword,
            'from_dict': False,
            'success': False
        }

    def _parse_translation_text(self, text: str, keyword: str) -> dict:
        """手动解析AI返回的翻译文本
        
        Args:
            text: AI返回的文本内容
            keyword: 原关键词
            
        Returns:
            dict: 解析后的翻译结果
        """
        try:
            # 尝试提取拼音、英文、日文信息
            import re
            
            # 初始化结果
            pinyin = keyword
            english = keyword
            japanese = keyword
            
            # 尝试不同的解析模式
            patterns = [
                # JSON格式的变体
                r'"pinyin"\s*:\s*"([^"]+)"',
                r'"english"\s*:\s*"([^"]+)"', 
                r'"japanese"\s*:\s*"([^"]+)"',
                # 其他格式
                r'拼音[：:]\s*([^\n\r,，]+)',
                r'英文[：:]\s*([^\n\r,，]+)',
                r'日文[：:]\s*([^\n\r,，]+)',
                r'pinyin[：:]\s*([^\n\r,，]+)',
                r'english[：:]\s*([^\n\r,，]+)',
                r'japanese[：:]\s*([^\n\r,，]+)',
            ]
            
            # 解析拼音
            for pattern in [patterns[0], patterns[3], patterns[6]]:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    pinyin = match.group(1).strip()
                    break
            
            # 解析英文
            for pattern in [patterns[1], patterns[4], patterns[7]]:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    english = match.group(1).strip()
                    break
            
            # 解析日文
            for pattern in [patterns[2], patterns[5], patterns[8]]:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    japanese = match.group(1).strip()
                    break
            
            # 如果至少有一个翻译不是原词汇，则认为解析成功
            success = (pinyin != keyword) or (english != keyword) or (japanese != keyword)
            
            return {
                'pinyin': pinyin,
                'english': english,
                'japanese': japanese,
                'text_char': keyword[0] if keyword else keyword,
                'from_dict': False,
                'success': success
            }
            
        except Exception as e:
            self.logger.error(f"手动解析翻译文本失败: {str(e)}")
            return {
                'pinyin': keyword,
                'english': keyword,
                'japanese': keyword,
                'text_char': keyword[0] if keyword else keyword,
                'from_dict': False,
                'success': False
            }

    def _simple_pinyin_fallback(self, char: str) -> str:
        """简单的拼音回退方法，为未知汉字提供基本音译
        
        Args:
            char: 单个汉字
            
        Returns:
            str: 拼音或原字符
        """
        # 如果是非汉字字符，直接返回
        if ord(char) < 0x4e00 or ord(char) > 0x9fff:
            return char
        # 对于未知汉字，返回一个通用格式
        return f"[{char}]"

    def _generate_random_color_scheme(self) -> dict:
        """生成随机配色方案
        
        Returns:
            dict: 包含颜色变量的字典
        """
        import random
        
        # 定义多种配色方案，对应提示词中的色系
        color_schemes = {
            "morandi": {
                # 莫兰迪色系（默认）
                "primary": "#B6B5A7",
                "secondary": "#9A8F8F", 
                "accent": "#C5B4A0",
                "background": "#E8E3DE",
                "card_bg": "#F2EDE9",
                "text": "#5B5B5B",
                "light_text": "#8C8C8C",
                "divider": "#D1CBC3"
            },
            "soft_pastel": {
                # 柔和粉彩系
                "primary": "#E8B5B5",
                "secondary": "#D4A5A5",
                "accent": "#F0C5C5", 
                "background": "#F5F0F0",
                "card_bg": "#FAF5F5",
                "text": "#6B4C4C",
                "light_text": "#8C7070",
                "divider": "#E0D0D0"
            },
            "deep_gem": {
                # 深邃宝石系
                "primary": "#7B9F9E",
                "secondary": "#5A7B7A",
                "accent": "#9FBFBE",
                "background": "#E8F0F0",
                "card_bg": "#F0F8F8",
                "text": "#2F4F4F",
                "light_text": "#5F7F7F",
                "divider": "#C0D8D8"
            },
            "fresh_natural": {
                # 清新自然系
                "primary": "#9EBF7B",
                "secondary": "#7BA05A",
                "accent": "#BEDF9B",
                "background": "#F0F5E8",
                "card_bg": "#F8FDF0",
                "text": "#3F5F2F",
                "light_text": "#6F8F5F",
                "divider": "#D0E0C0"
            },
            "elegant_gray": {
                # 高雅灰度系
                "primary": "#A8A8A8",
                "secondary": "#888888",
                "accent": "#C8C8C8",
                "background": "#F0F0F0",
                "card_bg": "#F8F8F8",
                "text": "#404040",
                "light_text": "#707070",
                "divider": "#D0D0D0"
            },
            "vintage_nostalgic": {
                # 复古怀旧系
                "primary": "#C5A27B",
                "secondary": "#A5825A",
                "accent": "#E5C29B",
                "background": "#F0EBE8",
                "card_bg": "#F8F3F0",
                "text": "#5F4F3F",
                "light_text": "#8F7F6F",
                "divider": "#E0D5C0"
            },
            "bright_energetic": {
                # 明亮活力系
                "primary": "#FFB366",
                "secondary": "#FF9933",
                "accent": "#FFCC99",
                "background": "#FFF5E6",
                "card_bg": "#FFFAF0",
                "text": "#CC6600",
                "light_text": "#E68A00",
                "divider": "#FFE6CC"
            },
            "cold_minimal": {
                # 冷淡极简系
                "primary": "#B0C4DE",
                "secondary": "#8FA4C7",
                "accent": "#D0E4FF",
                "background": "#F0F4F8",
                "card_bg": "#F8FAFC",
                "text": "#2C3E50",
                "light_text": "#5C6E80",
                "divider": "#E0E8F0"
            },
            "ocean_lake": {
                # 海洋湖泊系
                "primary": "#5DADE2",
                "secondary": "#3F8FBF",
                "accent": "#7DCDFF",
                "background": "#E8F4FD",
                "card_bg": "#F0F8FF",
                "text": "#1B4F72",
                "light_text": "#4A6FA5",
                "divider": "#C8E0F8"
            },
            "autumn_harvest": {
                # 秋季丰收系
                "primary": "#D2691E",
                "secondary": "#B8860B",
                "accent": "#F4A460",
                "background": "#FDF5E6",
                "card_bg": "#FFFAF0",
                "text": "#8B4513",
                "light_text": "#A0522D",
                "divider": "#F5DEB3"
            }
        }
        
        # 随机选择一个配色方案
        scheme_name = random.choice(list(color_schemes.keys()))
        return color_schemes[scheme_name]

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

    def explain_handler(self, e_context, context):
        """处理解释或吐槽命令
        
        Args:
            e_context: 事件上下文
            context: 消息上下文对象
        """
        try:
            self.logger.info("[ChinesePUA] ====== 解释处理器开始 ======")
            
            # 从context获取消息内容
            content = context.content if hasattr(context, 'content') else ""
            self.logger.info(f"[ChinesePUA] 获取到消息内容: '{content}'")
            
            # 提取关键词
            keyword = None
            if content.startswith("解释"):
                keyword = content[len("解释"):].strip()
                self.logger.info(f"[ChinesePUA] 解析到'解释'命令，关键词: '{keyword}'")
                command_type = "explain"
            elif content.startswith("吐槽"):
                keyword = content[len("吐槽"):].strip()
                self.logger.info(f"[ChinesePUA] 解析到'吐槽'命令，关键词: '{keyword}'")
                command_type = "complain"
            elif content.startswith("解字"):
                keyword = content[len("解字"):].strip()
                self.logger.info(f"[ChinesePUA] 解析到'解字'命令，关键词: '{keyword}'")
                command_type = "explain"
            else:
                self.logger.warning(f"[ChinesePUA] 未识别的命令: '{content}'")
                self._set_reply_text(e_context, "命令格式错误，请使用'解释 关键词'、'解字 关键词'或'吐槽 关键词'")
                return
            
            # 验证关键词
            if not self.validate_keyword(keyword):
                self.logger.warning(f"[ChinesePUA] 关键词无效: '{keyword}'")
                self._set_reply_text(e_context, f"关键词 '{keyword}' 无效，请提供有效的关键词")
                return
            
            # 准备请求参数
            self.logger.info(f"[ChinesePUA] 准备{command_type}请求参数")
            self.logger.info(f"[ChinesePUA] self.template_path: {self.template_path}")
            self.logger.info(f"[ChinesePUA] self.template_path是否为None: {self.template_path is None}")
            template_path = self.plugin_config.get("template_file", self.template_path)
            self.logger.info(f"[ChinesePUA] template_path: {template_path}")
            self.logger.info(f"[ChinesePUA] template_path是否为None: {template_path is None}")
            
            # 确保template_path不为None
            if template_path is None:
                template_path = os.path.join(os.path.dirname(__file__), 'template_card.html')
                self.logger.info(f"[ChinesePUA] 使用默认模板路径: {template_path}")
            
            template_params = {
                "command_type": command_type,
                "keyword": keyword
            }
            
            # 发送请求获取AI解释
            try:
                result = self.generate_explanation_with_ai(keyword, command_type)
                self.logger.info(f"[ChinesePUA] 从AI获取到解释: {result}")
            except Exception as api_error:
                self.logger.error(f"[ChinesePUA] 调用API失败: {str(api_error)}")
                self._set_reply_text(e_context, f"调用AI服务失败: {str(api_error)}")
                return
            
            # 处理回复
            if not result:
                self.logger.warning("[ChinesePUA] 从Dify获取到空回复")
                self._set_reply_text(e_context, "AI服务未返回有效回复")
                return
            
            # 检查是否需要生成图片卡片
            with_text = self.config.with_text if hasattr(self.config, 'with_text') else False
            self.logger.info(f"[ChinesePUA] with_text配置: {with_text}")
            
            if not with_text:
                # 生成图片卡片
                self.logger.info("[ChinesePUA] 开始生成图片卡片")
                try:
                    # 使用事件循环运行异步函数
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    
                    # 生成HTML (传递关键词和API返回的结果)
                    temp_html_path = loop.run_until_complete(self._generate_html(keyword, result))
                    
                    # 渲染图片
                    image_data = loop.run_until_complete(self._render_html_to_image(temp_html_path))
                    
                    if image_data:
                        # 保存图片（圆角效果已在HTML模板中实现）
                        image_path = self._save_image(image_data)
                        if image_path:
                            # 发送图片回复
                            reply = Reply(ReplyType.IMAGE, image_path)
                            e_context["reply"] = reply
                            self.logger.info("[ChinesePUA] 成功生成并设置图片回复")
                            loop.close()
                            return  # 修复：成功生成图片后直接返回，不再执行文本回复逻辑
                        else:
                            self.logger.error("[ChinesePUA] 保存图片失败")
                    else:
                        self.logger.error("[ChinesePUA] 渲染图片失败")
                        
                    # 如果图片生成失败，回退到文本回复
                    loop.close()
                except Exception as img_error:
                    self.logger.error(f"[ChinesePUA] 生成图片卡片失败: {str(img_error)}", exc_info=True)
                    # 继续执行文本回复
            
            # 设置文本回复
            try:
                e_context.econtext["reply"] = Reply(ReplyType.TEXT, result)
                self.logger.info("[ChinesePUA] 成功设置文本回复到e_context.econtext['reply']")
                return
            except Exception as reply_error:
                self.logger.error(f"[ChinesePUA] 设置回复到econtext失败: {str(reply_error)}")
            
            # 尝试替代方式设置回复
            try:
                # 尝试使用_set_reply_text方法
                self._set_reply_text(e_context, result)
                self.logger.info("[ChinesePUA] 使用_set_reply_text成功设置回复")
                return
            except Exception as set_error:
                self.logger.error(f"[ChinesePUA] _set_reply_text失败: {str(set_error)}")
            
            # 尝试使用channel方式发送
            try:
                if hasattr(context, 'channel') and hasattr(context.channel, 'send'):
                    context.channel.send(result)
                    self.logger.info("[ChinesePUA] 使用context.channel.send成功发送回复")
                    return
            except Exception as channel_error:
                self.logger.error(f"[ChinesePUA] context.channel.send失败: {str(channel_error)}")
            
            self.logger.warning("[ChinesePUA] 无法找到有效的回复方式")
            self.logger.info("[ChinesePUA] ====== 解释处理器结束 ======")
            
        except Exception as e:
            self.logger.error(f"[ChinesePUA] 解释处理器异常: {str(e)}", exc_info=True)
            error_message = self._format_error_message(e)
            try:
                # 尝试设置错误回复
                if "reply" in e_context.econtext:
                    e_context.econtext["reply"] = Reply(ReplyType.TEXT, f"处理失败: {error_message}")
                    self.logger.info("[ChinesePUA] 成功设置错误回复")
            except:
                self.logger.error("[ChinesePUA] 无法设置错误回复")

    def get_event_handler(self, event) -> Optional[callable]:
        """根据事件获取对应的处理函数
        
        Args:
            event: 事件对象
            
        Returns:
            处理函数或None
        """
        self.logger.info(f"[ChinesePUA] ====== get_event_handler被调用 ======")
        self.logger.info(f"[ChinesePUA] 事件类型: {type(event).__name__}")
        
        # 记录事件的所有属性
        event_attrs = dir(event)
        self.logger.info(f"[ChinesePUA] 事件对象属性: {', '.join([attr for attr in event_attrs if not attr.startswith('__')])}")
        
        # 检查各种可能存在的事件类型属性
        event_type = None
        if hasattr(event, 'event_type'):
            event_type = event.event_type
            self.logger.info(f"[ChinesePUA] 事件类型来自event_type: {event_type}")
        elif hasattr(event, 'type'):
            event_type = event.type
            self.logger.info(f"[ChinesePUA] 事件类型来自type: {event_type}")
        elif hasattr(event, 'event'):
            event_type = event.event
            self.logger.info(f"[ChinesePUA] 事件类型来自event: {event_type}")
        else:
            self.logger.warning("[ChinesePUA] 无法确定事件类型")
        
        # 记录事件的原始对象
        if hasattr(event, 'original') and event.original:
            self.logger.info(f"[ChinesePUA] 原始事件对象类型: {type(event.original).__name__}")
            if hasattr(event.original, 'econtext') and isinstance(event.original.econtext, dict):
                self.logger.info(f"[ChinesePUA] 原始事件econtext keys: {event.original.econtext.keys()}")
        
        # 尝试获取内容
        content = None
        content_source = "未知"
        
        # 直接尝试获取content
        if hasattr(event, 'content') and event.content:
            content = event.content
            content_source = "event.content"
        
        # 尝试从原始事件对象中获取
        elif hasattr(event, 'original') and event.original:
            orig = event.original
            if hasattr(orig, 'content') and orig.content:
                content = orig.content
                content_source = "event.original.content"
            elif hasattr(orig, 'econtext') and isinstance(orig.econtext, dict) and 'context' in orig.econtext:
                context = orig.econtext['context']
                if hasattr(context, 'content') and context.content:
                    content = context.content
                    content_source = "event.original.econtext['context'].content"
        
        if not content:
            self.logger.warning("[ChinesePUA] 无法从事件中获取content")
            return None
            
        content = content.strip()
        if not content:
            self.logger.warning("[ChinesePUA] 事件content为空白字符")
            return None
            
        self.logger.info(f"[ChinesePUA] 获取到事件content: '{content}' (来源: {content_source})")
        
        # 匹配解释或吐槽命令
        if content.startswith("解释") or content.startswith("吐槽"):
            cmd_type = "解释" if content.startswith("解释") else "吐槽"
            keyword = content[len(cmd_type):].strip()
            self.logger.info(f"[ChinesePUA] 匹配到'{cmd_type}'命令，关键词: '{keyword}'")
            
            if not keyword:
                self.logger.warning(f"[ChinesePUA] '{cmd_type}'命令后没有关键词")
                return None
            
            if not self.validate_keyword(keyword):
                self.logger.warning(f"[ChinesePUA] 关键词无效: '{keyword}'")
                return None
                
            self.logger.info(f"[ChinesePUA] 匹配成功，返回explain_handler处理器")
            return self.explain_handler
            
        self.logger.info(f"[ChinesePUA] 未匹配到支持的命令，跳过处理")
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

    def _set_reply_text(self, e_context, text):
        """安全地设置回复文本
        
        Args:
            e_context: 事件上下文
            text: 回复文本
        """
        try:
            reply = Reply(ReplyType.TEXT, text)
            
            # 尝试EventContext.econtext["reply"]方式
            if hasattr(e_context, 'econtext') and isinstance(e_context.econtext, dict):
                e_context.econtext["reply"] = reply
                self.logger.info(f"[ChinesePUA] 成功设置回复文本到e_context.econtext['reply']: {text[:30]}...")
                return True
            
            # 尝试设置e_context.reply属性
            if hasattr(e_context, 'reply'):
                e_context.reply = reply
                self.logger.info(f"[ChinesePUA] 成功设置回复文本到e_context.reply: {text[:30]}...")
                return True
                
            # 尝试使用e_context.send方法
            if hasattr(e_context, 'send'):
                e_context.send(reply)
                self.logger.info(f"[ChinesePUA] 成功使用e_context.send发送回复: {text[:30]}...")
                return True
            
            # 如果有context在econtext中，尝试使用channel.send
            if hasattr(e_context, 'econtext') and 'context' in e_context.econtext:
                context = e_context.econtext['context']
                if hasattr(context, 'channel') and hasattr(context.channel, 'send'):
                    context.channel.send(reply)
                    self.logger.info(f"[ChinesePUA] 成功使用context.channel.send发送回复: {text[:30]}...")
                    return True
                
            self.logger.warning(f"[ChinesePUA] 未找到设置回复的方法")
            return False
        except Exception as e:
            self.logger.error(f"[ChinesePUA] 设置回复文本失败: {str(e)}")
            return False

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

    async def _generate_html(self, keyword: str, explanation: str = None) -> str:
        """生成HTML内容
        
        Args:
            keyword: 需要解释的关键词
            explanation: 关键词的解释（可选，如果未提供则使用预设解释）
            
        Returns:
            str: 生成的HTML内容
            
        Raises:
            ValueError: 生成HTML失败
        """
        try:
            # 获取并转义关键词的解释
            if explanation is None:
                explanation = self.get_prompt(keyword)
            if not explanation:
                raise ValueError(f"无法获取关键词的解释: {keyword}")
            
            # 转义关键词和解释文本
            safe_keyword = self._escape_html(keyword)
            safe_explanation = self._escape_html(explanation)
            
            # 生成翻译
            translations = self._generate_translations(keyword)
            safe_pinyin = self._escape_html(translations['pinyin'])
            safe_english = self._escape_html(translations['english'])
            safe_japanese = self._escape_html(translations['japanese'])
            safe_text_char = self._escape_html(translations['text_char'])
            
            # 生成随机配色
            color_scheme = self._generate_random_color_scheme()
            
            # 替换模板中的占位符
            html_content = self.template_content
            html_content = html_content.replace('{{text}}', safe_keyword)
            html_content = html_content.replace('{{explanation}}', safe_explanation)
            html_content = html_content.replace('{{pinyin}}', safe_pinyin)
            html_content = html_content.replace('{{english}}', safe_english)
            html_content = html_content.replace('{{japanese}}', safe_japanese)
            html_content = html_content.replace('{{text_char}}', safe_text_char)
            
            # 替换颜色变量
            for color_key, color_value in color_scheme.items():
                html_content = html_content.replace(f'{{{{color_{color_key}}}}}', color_value)
            
            # 替换圆角半径变量
            radius = getattr(self.config, 'rounded_corner_radius', 20)
            html_content = html_content.replace('{{rounded_corner_radius}}', str(radius))
            
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
                
                # 创建新的浏览器上下文，设置合适的视口尺寸
                context = await browser.new_context(
                    viewport={'width': 600, 'height': 800},
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
                    'height': max(800, int(box['height']) + 40)
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
            
            # 渲染图片（圆角效果已在HTML模板中实现）
            image_data = await self._render_html_to_image(temp_html_path)
            if not image_data:
                return "", "渲染图片失败"
            
            # 保存图片
            image_path = self._save_image(image_data)
            if not image_path:
                return "", "保存图片失败"
            
            return image_path, ""
            
        except Exception as e:
            error_msg = f"生成图片失败: {str(e)}"
            self.logger.error(error_msg)
            return "", error_msg
            
        finally:
            # 清理临时HTML文件
            if temp_html_path:
                self._cleanup_temp_files(temp_html_path)

    def validate_keyword(self, keyword):
        """验证关键词是否有效
        
        Args:
            keyword: 用户输入的关键词
            
        Returns:
            bool: 关键词是否有效
        """
        if not keyword:
            self.logger.warning("[ChinesePUA] 关键词为空")
            return False
        
        # 去除首尾空白字符
        keyword = keyword.strip()
        if not keyword:
            self.logger.warning("[ChinesePUA] 关键词去除空白后为空")
            return False
            
        # 检查长度限制 (1-10个字符)
        if len(keyword) > 10:
            self.logger.warning(f"[ChinesePUA] 关键词'{keyword}'超过10个字符")
            return False
            
        # 检查是否含有汉字
        has_chinese = False
        for char in keyword:
            if '\u4e00' <= char <= '\u9fff':
                has_chinese = True
                break
                
        if not has_chinese:
            self.logger.warning(f"[ChinesePUA] 关键词'{keyword}'不包含汉字")
            return False
            
        self.logger.info(f"[ChinesePUA] 关键词'{keyword}'验证通过")
        return True

    def _format_error_message(self, error: Exception) -> str:
        """格式化错误信息
        
        Args:
            error: 捕获的异常对象
            
        Returns:
            str: 格式化后的错误消息
        """
        error_type = type(error).__name__
        error_msg = str(error)
        
        # 获取完整的错误追踪信息
        import traceback
        trace = traceback.format_exc()
        
        # 记录完整的错误日志
        self.logger.error(f"[ChinesePUA] 错误类型: {error_type}")
        self.logger.error(f"[ChinesePUA] 错误消息: {error_msg}")
        self.logger.error(f"[ChinesePUA] 错误追踪:\n{trace}")
        
        # 返回用户友好的错误消息
        user_msg = f"很抱歉，处理请求时遇到了问题 ({error_type})"
        
        # 对常见错误类型提供更具体的消息
        if isinstance(error, ValueError):
            user_msg = f"输入值无效: {error_msg}"
        elif isinstance(error, KeyError):
            user_msg = "系统找不到必要的配置项"
        elif isinstance(error, FileNotFoundError):
            user_msg = "找不到所需的文件"
        elif isinstance(error, PermissionError):
            user_msg = "系统权限不足，无法完成操作"
        elif isinstance(error, TimeoutError) or "timeout" in error_msg.lower():
            user_msg = "请求超时，请稍后再试"
        elif "api" in error_msg.lower() or "http" in error_msg.lower() or "request" in error_msg.lower():
            user_msg = "调用AI服务失败，请稍后再试"
            
        return user_msg

    def get_prompt(self, keyword: str) -> str:
        """生成提示词"""
        from .prompts import get_prompt
        return get_prompt(keyword)

    def handle_event(self, e_context) -> None:
        """处理事件的主方法
        
        Args:
            e_context: 事件上下文对象，是EventContext类型
        """
        try:
            self.logger.info("[ChinesePUA] ====== 事件处理开始 ======")
            self.logger.info(f"[ChinesePUA] 收到事件: {type(e_context).__name__}, 事件类型: {e_context.event}")
            
            # 检查事件对象结构
            self.logger.info(f"[ChinesePUA] EventContext.econtext的keys: {e_context.econtext.keys()}")
            
            # 尝试从context获取内容
            if "context" in e_context.econtext:
                context = e_context.econtext["context"]
                self.logger.info(f"[ChinesePUA] 找到context对象：{type(context).__name__}")
                
                # 尝试获取内容
                content = ""
                if hasattr(context, 'content'):
                    content = context.content
                    self.logger.info(f"[ChinesePUA] 从context.content获取内容: {content}")
            else:
                self.logger.warning("[ChinesePUA] 事件上下文中没有context信息")
                return
            
            # 清理旧图片
            self._cleanup_old_images()
            
            # 验证内容是否有效
            if not content:
                self.logger.warning("[ChinesePUA] 获取到的消息内容为空")
                return
            
            # 直接检查是否是解释、解字或吐槽命令
            if content.startswith("解释") or content.startswith("解字") or content.startswith("吐槽"):
                keyword = None
                if content.startswith("解释"):
                    keyword = content[len("解释"):].strip()
                    self.logger.info(f"[ChinesePUA] 直接检测到'解释'命令，提取关键词: '{keyword}'")
                elif content.startswith("解字"):
                    keyword = content[len("解字"):].strip()
                    self.logger.info(f"[ChinesePUA] 直接检测到'解字'命令，提取关键词: '{keyword}'")
                elif content.startswith("吐槽"):
                    keyword = content[len("吐槽"):].strip()
                    self.logger.info(f"[ChinesePUA] 直接检测到'吐槽'命令，提取关键词: '{keyword}'")
                
                if keyword and self.validate_keyword(keyword):
                    self.logger.info(f"[ChinesePUA] 关键词有效: '{keyword}'，调用explain_handler")
                    if "reply" not in e_context.econtext:
                        e_context.econtext["reply"] = None
                    
                    # 将context也传递给处理器，而不仅仅是e_context
                    self.explain_handler(e_context, context)
                    # 中断事件处理流程，防止其他处理器继续处理
                    e_context.action = EventAction.BREAK_PASS
                    return
                else:
                    self.logger.info(f"[ChinesePUA] 关键词无效或为空: '{keyword}'")
            
            self.logger.info(f"[ChinesePUA] 不是'解释'或'吐槽'命令，跳过处理")
            self.logger.info("[ChinesePUA] ====== 事件处理结束 ======")
            
        except Exception as e:
            error_message = self._format_error_message(e)
            self.logger.error(f"[ChinesePUA] 处理事件失败: {str(e)}", exc_info=True)
            try:
                self._set_reply_text(e_context, error_message)
            except Exception as reply_error:
                self.logger.error(f"[ChinesePUA] 无法设置回复文本: {str(reply_error)}")
                
                # 尝试使用e_context.econtext["reply"]设置回复
                try:
                    if "reply" in e_context.econtext:
                        e_context.econtext["reply"] = Reply(ReplyType.TEXT, f"处理失败: {error_message}")
                        self.logger.info(f"[ChinesePUA] 成功设置回复到e_context.econtext['reply']")
                except:
                    self.logger.error("[ChinesePUA] 无法以任何方式设置回复")
            finally:
                self.logger.info("[ChinesePUA] ====== 事件处理异常结束 ======")

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
            self.logger.info("[ChinesePUA] 开始验证配置...")
            
            # 检查临时目录
            if not os.path.exists(self.temp_dir):
                self.logger.error(f"[ChinesePUA] 临时目录不存在: {self.temp_dir}")
                return False
                
            if not os.access(self.temp_dir, os.W_OK):
                self.logger.error(f"[ChinesePUA] 临时目录无写入权限: {self.temp_dir}")
                return False
            
            self.logger.info(f"[ChinesePUA] 临时目录验证通过: {self.temp_dir}")
                
            # 检查模板文件
            if not os.path.exists(self.template_path):
                self.logger.error(f"[ChinesePUA] 模板文件不存在: {self.template_path}")
                return False
            
            self.logger.info(f"[ChinesePUA] 模板文件存在: {self.template_path}")
                
            # 验证模板内容
            try:
                template_content = self._load_template()
                if not template_content:
                    self.logger.error("[ChinesePUA] 模板内容加载失败")
                    return False
                self.logger.info("[ChinesePUA] 模板内容加载成功")
            except Exception as e:
                self.logger.error(f"[ChinesePUA] 验证模板失败: {str(e)}")
                return False
            
            # 验证API配置
            if not self.config.api_key:
                self.logger.warning("[ChinesePUA] API密钥未配置，这可能会导致某些功能无法使用")
            else:
                self.logger.info("[ChinesePUA] API密钥已配置")
                
            if not self.config.api_base:
                self.logger.warning("[ChinesePUA] API基础URL未配置，这可能会导致某些功能无法使用")
            else:
                self.logger.info(f"[ChinesePUA] API基础URL已配置: {self.config.api_base}")
                
            self.logger.info("[ChinesePUA] 配置验证通过")
            return True
            
        except Exception as e:
            self.logger.error(f"[ChinesePUA] 验证配置时发生错误: {str(e)}", exc_info=True)
            return False

    def generate_explanation_with_ai(self, keyword: str, command_type: str) -> str:
        """使用AI生成词语解释
        
        Args:
            keyword: 关键词
            command_type: 命令类型 (explain/complain)
            
        Returns:
            str: 生成的解释内容
        """
        try:
            self.logger.info(f"[ChinesePUA] 开始为关键词'{keyword}'生成{command_type}解释")
            
            # 优先使用专业的提示词模板生成解释文本
            from .prompts import get_prompt, prompts_dict
            if command_type == "explain" or command_type == "complain":
                # 基于李继刚老师的汉语新解风格，但只要解释文本
                prompt = f"""你是新汉语老师，你年轻,批判现实,思考深刻,语言风趣。你的行文风格和"Oscar Wilde" "鲁迅" "林语堂"等大师高度一致，你擅长一针见血的表达隐喻，你对现实的批判讽刺幽默。

任务：将汉语词汇"{keyword}"进行全新角度的解释，你会用一个特殊视角来解释这个词汇。

要求：
- 用一句话表达你的词汇解释
- 抓住词汇的本质，使用辛辣的讽刺、一针见血的指出本质
- 使用包含隐喻的金句
- 语言风趣，充满讽刺或幽默色彩
- 字数控制在30字以内

例如："委婉"： "刺向他人时, 决定在剑刃上撒上止痛药。"

请直接给出对"{keyword}"的解释，不要任何前缀或说明。"""
                self.logger.info(f"[ChinesePUA] 使用汉语新解风格模板")
            elif command_type == "字源" or "解字" in command_type:
                # 字源解释风格
                prompt = f"""你是中国古文化研究专家，熟知中国古文，精通说文解字。

请为汉字"{keyword}"提供字源解释，要求：
- 从《说文解字》的角度解释字源本意
- 展示历代使用和引申意思
- 用专业客观的表达方式
- 语言简洁明了，突出历史厚重感

请直接给出解释，不要前缀说明。"""
                self.logger.info(f"[ChinesePUA] 使用说文解字风格模板")
            else:
                prompt = f"请解释词语：{keyword}"
            
            self.logger.info(f"[ChinesePUA] 生成的提示词: {prompt[:100]}...")
            
            # 准备API请求参数
            api_key = getattr(self.config, "api_key", "")
            if not api_key:
                raise ValueError("缺少API密钥")
                
            base_url = getattr(self.config, "api_base", "")
            if not base_url:
                raise ValueError("缺少API基础URL")
            
            # 根据不同的API提供商构建正确的URL和数据格式
            if "siliconflow" in base_url:
                api_url = f"{base_url}/v1/chat/completions"
                # SiliconFlow使用OpenAI兼容的API格式
                data = {
                    "model": getattr(self.config, "api_model", "deepseek-ai/DeepSeek-V3"),
                    "messages": [
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": getattr(self.config, "max_tokens", 2048),
                    "temperature": getattr(self.config, "temperature", 0.7)
                }
            else:
                api_url = f"{base_url}/v1/chat-messages"
                # Dify格式
                data = {
                    "inputs": {},
                    "query": prompt,
                    "response_mode": "blocking",
                    "user": "user"
                }
            
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            # 发送请求
            import requests
            self.logger.info(f"[ChinesePUA] 发送请求到API: {api_url}")
            response = requests.post(api_url, headers=headers, json=data, timeout=30)
            response.raise_for_status()
            
            # 解析响应
            result = response.json()
            self.logger.info(f"[ChinesePUA] 请求成功，响应状态码: {response.status_code}")
            
            # 根据不同的API提供商提取回答内容
            if "siliconflow" in base_url:
                # SiliconFlow响应格式
                if "choices" in result and len(result["choices"]) > 0:
                    answer = result["choices"][0]["message"]["content"].strip()
                    self.logger.info(f"[ChinesePUA] 获取到AI解释: {answer}")
                    return answer
                else:
                    self.logger.error(f"[ChinesePUA] SiliconFlow响应中没有有效内容: {result}")
                    return f"AI暂时无法解释'{keyword}'，请稍后再试"
            else:
                # Dify响应格式
                if "answer" in result:
                    answer = result["answer"].strip()
                    self.logger.info(f"[ChinesePUA] 获取到AI解释: {answer}")
                    return answer
                else:
                    self.logger.error(f"[ChinesePUA] Dify响应中没有answer字段: {result}")
                    return f"AI暂时无法解释'{keyword}'，请稍后再试"
        
        except Exception as e:
            self.logger.error(f"[ChinesePUA] 调用AI API失败: {str(e)}", exc_info=True)
            # 使用预设解释作为降级方案
            preset_explanation = get_prompt(keyword)
            if preset_explanation and "对不起" not in preset_explanation:
                self.logger.info(f"[ChinesePUA] API失败，使用预设解释作为降级方案: {preset_explanation}")
                return preset_explanation
            # 最终降级方案
            return f"在探索'{keyword}'的深层含义时遇到了一些技术困难，但这个词本身就充满了想象空间。"
