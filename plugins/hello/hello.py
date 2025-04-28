# encoding:utf-8

import plugins
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_message import ChatMessage
from common.log import logger
from plugins import *
from config import conf


@plugins.register(
    name="Hello",
    desire_priority=-1,
    hidden=True,
    desc="A simple plugin that says hello",
    version="0.1",
    author="lanvent",
)


class Hello(Plugin):

    group_welc_prompt = "请你随机使用一种风格说一句问候语来欢迎新用户{nickname}加入群聊{group_name},要求问候语热情、有趣、独特、拟人化,贴合实际生活场景,字数在50字以内。注意：直接使用{nickname}和{group_name}的实际值，不要给用户昵称和群名字加引号，不要在回复中包含这些占位符。"
    group_exit_prompt = "请你随机使用一种风格介绍你自己，并告诉用户输入#help可以查看帮助信息。"
    patpat_prompt = "请你随机使用一种风格跟其他群用户说他违反规则\"{nickname}\"退出群聊。"

    def __init__(self):
        super().__init__()
        try:
            self.config = super().load_config()
            if not self.config:
                self.config = self._load_config_template()
            self.group_welc_fixed_msg = self.config.get("group_welc_fixed_msg", {})
            self.group_welc_prompt = self.config.get("group_welc_prompt", self.group_welc_prompt)
            self.group_exit_prompt = self.config.get("group_exit_prompt", self.group_exit_prompt)
            self.patpat_prompt = self.config.get("patpat_prompt", self.patpat_prompt)
            logger.info("[Hello] inited")
            self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
        except Exception as e:
            logger.error(f"[Hello]初始化异常：{e}")
            raise "[Hello] init failed, ignore "

    def on_handle_context(self, e_context: EventContext):
        logger.info("[Hello] Starting context handling with type: %s", e_context["context"].type)
        
        if e_context["context"].type not in [
            ContextType.TEXT,
            ContextType.JOIN_GROUP,
            ContextType.PATPAT,
            ContextType.EXIT_GROUP
        ]:
            logger.debug("[Hello] Skipping unsupported context type: %s", e_context["context"].type)
            return
        
        # 处理JOIN_GROUP消息
        if e_context["context"].type == ContextType.JOIN_GROUP:
            msg: ChatMessage = e_context["context"]["msg"]
            logger.info("[Hello] Processing JOIN_GROUP message: %s", msg.content)
            logger.info("[Hello] Context data: %s", e_context["context"])
            
            # 获取群名称
            group_name = "群聊"
            if hasattr(msg, 'group_name'):
                group_name = msg.group_name
                logger.debug("[Hello] Got group_name from msg.group_name: %s", group_name)
            elif "group_name" in e_context["context"].kwargs:
                group_name = e_context["context"].kwargs["group_name"]
                logger.debug("[Hello] Got group_name from context kwargs: %s", group_name)
            logger.info("[Hello] Final group name: %s", group_name)
            
            # 获取被邀请用户的昵称
            nickname = None
            if hasattr(msg, 'invite_nickname'):
                nickname = msg.invite_nickname
                logger.debug("[Hello] Got nickname from invite_nickname: %s", nickname)
            if not nickname:
                nickname = msg.actual_user_nickname
                logger.debug("[Hello] Using actual_user_nickname as fallback: %s", nickname)
            
            logger.info("[Hello] Final nickname: %s", nickname)
            
            # 检查是否有固定欢迎语
            if "group_welcome_msg" in conf() or group_name in self.group_welc_fixed_msg:
                logger.info("[Hello] Using fixed welcome message")
                reply = Reply()
                reply.type = ReplyType.TEXT
                if group_name in self.group_welc_fixed_msg:
                    reply.content = self.group_welc_fixed_msg.get(group_name, "")
                    logger.info("[Hello] Using group-specific welcome message: %s", reply.content)
                else:
                    reply.content = conf().get("group_welcome_msg", "")
                    logger.info("[Hello] Using global welcome message: %s", reply.content)
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                return
            
            # 没有固定欢迎语，使用AI生成
            logger.info("[Hello] No fixed welcome message found, using AI generation")
            e_context["context"].type = ContextType.TEXT
            prompt = self.group_welc_prompt.format(nickname=nickname, group_name=group_name)
            logger.info("[Hello] Generated prompt: %s", prompt)
            e_context["context"].content = prompt
            
            # 设置必要的上下文标记
            e_context["context"]["from_plugin"] = True
            e_context["context"]["is_plugin_welcome"] = True
            logger.info("[Hello] Context after setting markers: from_plugin=%s, is_plugin_welcome=%s", 
                       e_context["context"].get("from_plugin"), 
                       e_context["context"].get("is_plugin_welcome"))
            e_context.action = EventAction.BREAK
            return
        
        # 处理EXIT_GROUP消息
        if e_context["context"].type == ContextType.EXIT_GROUP:
            msg: ChatMessage = e_context["context"]["msg"]
            
            if "group_exit_msg" in conf():
                reply = Reply()
                reply.type = ReplyType.TEXT
                reply.content = conf().get("group_exit_msg", "")
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                return
            
            if conf().get("group_chat_exit_group"):
                e_context["context"].type = ContextType.TEXT
                e_context["context"].content = self.group_exit_prompt.format(nickname=msg.actual_user_nickname)
                e_context.action = EventAction.BREAK
                return
            
            e_context.action = EventAction.BREAK
            return
        
        # 处理PATPAT消息
        if e_context["context"].type == ContextType.PATPAT:
            e_context["context"].type = ContextType.TEXT
            e_context["context"].content = self.patpat_prompt
            e_context.action = EventAction.BREAK
            if not self.config or not self.config.get("use_character_desc"):
                e_context["context"]["generate_breaked_by"] = EventAction.BREAK
            return
        
        # 处理文本消息
        msg: ChatMessage = e_context["context"]["msg"]
        content = e_context["context"].content
        logger.debug("[Hello] on_handle_context. content: %s" % content)
        
        if content == "Hello":
            reply = Reply()
            reply.type = ReplyType.TEXT
            if e_context["context"]["isgroup"]:
                reply.content = f"Hello, {msg.actual_user_nickname} from {msg.from_user_nickname}"
            else:
                reply.content = f"Hello, {msg.from_user_nickname}"
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS
        
        elif content == "Hi":
            reply = Reply()
            reply.type = ReplyType.TEXT
            reply.content = "Hi"
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK
        
        elif content == "End":
            e_context["context"].type = ContextType.IMAGE_CREATE
            e_context["context"].content = "The World"
            e_context.action = EventAction.CONTINUE

    def get_help_text(self, **kwargs):
        help_text = "输入Hello，我会回复你的名字\n输入End，我会回复你世界的图片\n"
        return help_text

    def _load_config_template(self):
        logger.debug("No Hello plugin config.json, use plugins/hello/config.json.template")
        try:
            plugin_config_path = os.path.join(self.path, "config.json.template")
            if os.path.exists(plugin_config_path):
                with open(plugin_config_path, "r", encoding="utf-8") as f:
                    plugin_conf = json.load(f)
                    return plugin_conf
        except Exception as e:
            logger.exception(e)