import plugins
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.plugin import Plugin
from common.log import logger
from bridge.context import EventContext, EventAction

@plugins.register(
    name="TestPlugin",
    desire_priority=900,  # 比GodCmd低一点
    hidden=True,
    desc="测试插件系统是否正常工作",
    version="1.0",
    author="test",
)
class TestPlugin(Plugin):
    def __init__(self):
        super().__init__()
        self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
        logger.info("[TestPlugin] 插件已初始化")

    def on_handle_context(self, e_context: EventContext):
        context_type = e_context["context"].type
        if context_type != ContextType.TEXT:
            return
            
        content = e_context["context"].content
        logger.info(f"[TestPlugin] 收到消息: {content}")
        
        if content == "#test":
            reply = Reply()
            reply.type = ReplyType.INFO
            reply.content = "测试插件响应成功！"
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS
            logger.info("[TestPlugin] 响应测试命令") 