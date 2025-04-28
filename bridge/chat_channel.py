import logging
import traceback

logger = logging.getLogger(__name__)

try:
    # 原有代码
except Exception as e:
    logger.error(f"Worker return exception: {str(e)}")
    logger.error(f"Exception details: {traceback.format_exc()}")

if context.type == ContextType.JOIN_GROUP:
    # 确保group_name存在于上下文中
    if 'group_name' not in context.kwargs:
        context.kwargs['group_name'] = context.kwargs.get('receiver', '群聊').split('@')[0] 