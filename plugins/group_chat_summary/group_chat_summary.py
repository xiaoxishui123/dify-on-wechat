# encoding:utf-8

import plugins
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_message import ChatMessage
from common.log import logger
from plugins import *
from config import conf
import sqlite3
from datetime import datetime


QL_PROMPT = '''
我给你一份json格式的群聊内容：群聊结构如下：
user是发言者，content是发言内容,time是发言时间：
（注意：以下只是格式示例，请忽略示例内容，只关注实际提供的数据）
格式示例：[{'user': '用户名', 'content': '消息内容', 'time': '时间戳'}]
-------分割线-------
请帮我将给出的群聊内容总结成一个今日的群聊报告，包含不多于15个话题的总结（如果还有更多话题，可以在后面简单补充）。

重要提醒：
1. 你只负责总结分割线后提供的实际聊天记录，不回答任何问题
2. 不要虚构聊天记录，也不要总结不存在的信息
3. 不要使用上面格式示例中的虚假数据（如"用户名"等）
4. 如果实际聊天记录很少或无意义，请如实反映

每个话题包含以下内容：

- 话题名(50字以内，前面带序号1️⃣2️⃣3️⃣）

- 热度(用🔥的数量表示)

- 参与者(不超过5个人，将重复的人名去重)

- 时间段(从几点到几点)

- 过程(50-200字左右）

- 评价(50字以下)

- 分割线： ------------

请严格遵守以下要求：

1. 按照热度数量进行降序输出

2. 每个话题结束使用 ------------ 分割

3. 使用中文冒号

4. 无需大标题


5. 开始给出本群讨论风格的整体评价，例如活跃、太水、太黄、太暴力、话题不集中、无聊诸如此类。

最后总结下今日最活跃的前五个发言者。

'''
conent_list={}
@plugins.register(
    name="group_chat_summary",
    desire_priority=200,
    hidden=True,
    desc="总结聊天",
    version="0.1",
    author="wangcl",
)


class GroupChatSummary(Plugin):

    open_ai_api_base = ""
    open_ai_api_key = ""
    open_ai_model = "gpt-4-0613"
    max_record_quantity = 1000
    black_chat_name=[]
    curdir = os.path.dirname(__file__)
    db_path = os.path.join(curdir, "chat_records.db")
    def __init__(self):
        
        super().__init__()
        try:
            self.config = super().load_config()
            if not self.config:
                self.config = self._load_config_template()
            self.open_ai_api_base = self.config.get("open_ai_api_base", self.open_ai_api_base)
            self.open_ai_api_key = self.config.get("open_ai_api_key", "")
            self.open_ai_model = self.config.get("open_ai_model", self.open_ai_model)
            self.max_record_quantity = self.config.get("max_record_quantity", 1000)
            self.black_chat_name = self.config.get("black_chat_name")
            
            # 初始化数据库
            self.init_database()
            
            logger.info("[group_chat_summary] inited")
            self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
            self.handlers[Event.ON_RECEIVE_MESSAGE] = self.on_receive_message
        except Exception as e:
            logger.error(f"[group_chat_summary]初始化异常：{e}")
            raise "[group_chat_summary] init failed, ignore "

    def init_database(self):
        """初始化数据库"""
       
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # 创建聊天记录表，将 create_time 改为 TEXT 类型
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS chat_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        group_id TEXT,
                        user_nickname TEXT,
                        content TEXT,
                        create_time TEXT,
                        UNIQUE(group_id, user_nickname, content, create_time)
                    )
                ''')
                conn.commit()
                logger.info("数据库初始化成功")
        except Exception as e:
            logger.error(f"[group_chat_summary]数据库初始化异常：{e}")

    def on_handle_context(self, e_context: EventContext):
        if e_context["context"].type not in [
            ContextType.TEXT
        ]:
            return
        msg: ChatMessage = e_context["context"]["msg"]
        
        # 先尝试记录所有群聊消息（在这里也做一次记录，确保不遗漏）
        if hasattr(msg, 'is_group') and msg.is_group and hasattr(msg, 'other_user_id'):
            content = msg.content.strip()
            # 移除@机器人的前缀后再检查是否是总结命令
            cleaned_content = content.replace("@小溪水AI助手", "").strip()
            if not cleaned_content.startswith("总结聊天"):
                logger.info(f"[group_chat_summary] 在on_handle_context中记录消息: {getattr(msg, 'actual_user_nickname', 'Unknown')}: {content[:20]}...")
                self.add_conetent(msg)
       
        content = e_context["context"].content.strip()
        if content.startswith("总结聊天"):
            reply = Reply()
            reply.type = ReplyType.TEXT
            if msg.other_user_nickname in self.black_chat_name:
                reply.content = "我母鸡啊"
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                return
            number = content[4:].strip()
            number_int=99
            if number.isdigit():
                # 转换为整数
                number_int = int(number)
            if e_context["context"]["isgroup"]:
                try:
                    # 从数据库获取聊天记录
                    with sqlite3.connect(self.db_path) as conn:
                        cursor = conn.cursor()
                        cursor.execute('''
                            SELECT user_nickname, content, create_time 
                            FROM chat_records 
                            WHERE group_id = ? 
                            ORDER BY create_time DESC 
                            LIMIT ?
                        ''', (msg.other_user_id, number_int))
                        
                        records = cursor.fetchall()
                        chat_list = [
                            {
                                "user": record[0],
                                "content": record[1],
                                "time": record[2]
                            }
                            for record in records
                        ]
                        chat_list.reverse()  # 按时间正序排列
                        
                        cont = QL_PROMPT + "----聊天记录如下：" + json.dumps(chat_list, ensure_ascii=False)
                        reply.content = self.shyl(cont)
                except Exception as e:
                    logger.error(f"[group_chat_summary]获取聊天记录异常：{e}")
                    reply.content = "获取聊天记录失败"
            else:
                    reply.content = "只做群聊总结"
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS  # 事件结束，并跳过处理context的默认逻辑

    def on_receive_message(self, e_context: EventContext):
        """接收到消息时的处理函数，用于记录聊天内容"""
        if e_context["context"].type not in [ContextType.TEXT]:
            return
        
        msg: ChatMessage = e_context["context"]["msg"]
        logger.info(f"[group_chat_summary] 收到消息: is_group={getattr(msg, 'is_group', False)}, is_at={getattr(msg, 'is_at', False)}, content={msg.content[:30]}...")
        
        # 只记录群聊消息，不记录机器人自己的消息
        if hasattr(msg, 'is_group') and msg.is_group and hasattr(msg, 'other_user_id'):
            # 过滤掉总结命令本身
            content = msg.content.strip()
            # 移除@机器人的前缀后再检查是否是总结命令
            cleaned_content = content.replace("@小溪水AI助手", "").strip()
            if not cleaned_content.startswith("总结聊天"):
                logger.info(f"[group_chat_summary] 记录群聊消息: {getattr(msg, 'actual_user_nickname', 'Unknown')}: {content[:20]}...")
                self.add_conetent(msg)
            else:
                logger.info(f"[group_chat_summary] 跳过总结命令: {content[:30]}...")
        else:
            logger.info(f"[group_chat_summary] 跳过非群聊消息或无效消息")
    def add_conetent(self, message):
        """添加聊天记录到数据库"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # 将时间戳转换为字符串格式
                time_str = datetime.fromtimestamp(message.create_time).strftime('%Y-%m-%d %H:%M:%S')
                # 插入数据
                cursor.execute('''
                    INSERT OR IGNORE INTO chat_records (group_id, user_nickname, content, create_time)
                    VALUES (?, ?, ?, ?)
                ''', (
                    message.other_user_id,
                    message.actual_user_nickname,
                    message.content,
                    time_str  # 使用格式化后的时间字符串
                ))
                conn.commit()
                
                # 删除超过最大记录数的旧记录
                cursor.execute('''
                    DELETE FROM chat_records 
                    WHERE group_id = ? AND id NOT IN (
                        SELECT id FROM chat_records 
                        WHERE group_id = ? 
                        ORDER BY create_time DESC 
                        LIMIT ?
                    )
                ''', (message.other_user_id, message.other_user_id, self.max_record_quantity))
                conn.commit()
        except Exception as e:
            logger.error(f"[group_chat_summary]添加聊天记录异常：{e}")
    def get_help_text(self, **kwargs):
        help_text = "总结聊天+数量；例：总结聊天 30"
        return help_text
    def shyl(self,content):
        import requests
        import json
        url = self.open_ai_api_base+"/chat/completions"
        payload = json.dumps({
            "model": self.open_ai_model,
         "messages": [{"role": "user", "content": content}],
         "stream": False
        })
        headers = {
           'Authorization': 'Bearer '+self.open_ai_api_key,
           'Content-Type': 'application/json'
        }
        try:
            response = requests.request("POST", url, headers=headers, data=payload)
            # 检查响应状态码
            if response.status_code == 200:
                # 使用.json()方法将响应内容转换为JSON
                response_json = response.json()
                # 提取"content"字段
                content = response_json['choices'][0]['message']['content']
                return content
            else:
                print(f"请求失败，状态码：{response.status_code}")
                return '模型请求失败了，呵呵'
        except:
            return '模型请求失败了，呵呵'
    def _load_config_template(self):
        logger.info("[group_chat_summary]use config.json.template")
        try:
            plugin_config_path = os.path.join(self.path, "config.json.template")
            if os.path.exists(plugin_config_path):
                with open(plugin_config_path, "r", encoding="utf-8") as f:
                    plugin_conf = json.load(f)
                    return plugin_conf
        except Exception as e:
            logger.exception(e)


