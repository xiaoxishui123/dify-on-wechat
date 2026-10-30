# encoding:utf-8
import plugins
from bridge.context import ContextType, Context
from bridge.reply import Reply, ReplyType
from channel.chat_message import ChatMessage
import logging
from plugins import *
from plugins.difytimetask.TimeTaskTool import TaskManager
from plugins.difytimetask.config import conf, load_config
from plugins.difytimetask.Tool import TimeTaskModel
from lib import itchat
from lib.itchat.content import *
import re
import arrow
from plugins.difytimetask.Tool import ExcelTool
from bridge.bridge import Bridge
import config as RobotConfig
import requests
import io
import time
import gc
from channel import channel_factory
from lib.gewechat import GewechatClient
from lib.gewechat.client import GewechatClient
from config import global_config  # 引入 global_config

class TimeTaskRemindType(Enum):
    NO_Task = 1           #无任务
    Add_Success = 2       #添加任务成功
    Add_Failed = 3        #添加任务失败
    Cancel_Success = 4    #取消任务成功
    Cancel_Failed = 5     #取消任务失败
    TaskList_Success = 6  #查看任务列表成功
    TaskList_Failed = 7   #查看任务列表失败

@plugins.register(
    name="difytimetask",
    desire_priority=950,
    hidden=True,
    desc="定时任务系统，可定时处理事件",
    version="1.1",
    author="haikerwang",
)

# https://github.com/cm04918/difytimetask
# 此插件只能在 https://github.com/hanfangyuan4396/dify-on-wechat 下运行，请勿与timetask 同时使用。

# 在 TimeTask 类的 __init__ 方法中初始化 GewechatClient
class difytimetask(Plugin):

    # ==================== 每日一句：确定性轮换配置（可自行调整） ====================
    # 提示词中带此标记的 GPT 任务，才会注入轮换参数，其他 GPT 任务不受影响
    DAILY_ROTATION_MARK = "[ROTATE]"
    # 类型配额：7 天一轮 = 4 天名人名言 + 2 天原创金句 + 1 天原创早安问候
    DAILY_TYPE_CYCLE = ["名言", "原创金句", "名言", "原创问候", "名言", "原创金句", "名言"]
    # 作者分组轮换：每次轮到"名言"就前进一组，走完一轮后循环
    # "商道谋略"组独占鬼谷子，一轮出现一次（约两周一次），想更频繁可调整其位置或复制该组
    DAILY_AUTHOR_GROUPS = [
        {"name": "古典哲思", "authors": ["苏格拉底", "柏拉图", "亚里士多德"]},
        {"name": "温暖生活", "authors": ["泰戈尔", "汪曾祺", "丰子恺"]},
        {"name": "行动意志", "authors": ["罗曼·罗兰", "海明威", "爱默生"]},
        {"name": "治学修身", "authors": ["鲁迅", "朱光潜", "钱钟书"]},
        {"name": "人生通透", "authors": ["老舍", "梁启超", "胡适"]},
        {"name": "思想远方", "authors": ["歌德", "托尔斯泰", "雨果"]},
        {"name": "自然简朴", "authors": ["林语堂", "梭罗"]},
        {"name": "商道谋略", "authors": ["鬼谷子"]},
    ]
    # 鬼谷子句池（已人工核校，只允许原样引用，禁止模型自行联想池外句子）
    DAILY_GUGUZI_POOL = [
        "世无常贵，事无常师。",
        "相益则亲，相损则疏。",
        "欲闻其声反默，欲张反敛，欲高反下，欲取反与。",
        "事贵制人，而不贵见制于人。",
        "故知之始己，自知而后知人也。",
        "智用于众人之所不能知。",
        "世无可抵，则深隐而待时。",
        "故远而亲者，有阴德也。",
        "口者，心之门户也。",
    ]
    # 主题域，按 day_index 步进 3 轮转（3 与 8 互质，走满一轮才重复）
    DAILY_TOPICS = ["行动", "坚持", "时间", "专注", "学习", "节奏", "勇气", "温度"]
    DAILY_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "taskFile", "daily_rotation.json")

    def __init__(self):
        super().__init__()
        self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
        print("[difytimetask] inited")
        load_config()
        self.conf = conf()
        self.taskManager = TaskManager(self.runTimeTask)
        self.channel = None
        
        # 读取根目录的 config.json 文件
        self.gewechat_config = self._load_root_config()
        if self.gewechat_config:
            self.app_id = self.gewechat_config.get("gewechat_app_id")
            self.base_url = self.gewechat_config.get("gewechat_base_url")
            self.token = self.gewechat_config.get("gewechat_token")
            # 初始化 GewechatClient
            self.client = GewechatClient(self.base_url, self.token)
        else:
            logger.error("[difytimetask] 无法加载根目录的 config.json 文件，GewechatClient 初始化失败")
            self.client = None

    def _load_root_config(self):
        """加载根目录的 config.json 文件"""
        try:
            root_config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config.json")
            if os.path.exists(root_config_path):
                with open(root_config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            else:
                logger.error(f"[difytimetask] 根目录的 config.json 文件不存在: {root_config_path}")
                return None
        except Exception as e:
            logger.error(f"[difytimetask] 加载根目录的 config.json 文件失败: {e}")
            return None



    def cancel_all_tasks(self, e_context: EventContext):
        """
        取消所有任务，将所有任务的 '是否可用' 列（列 B）设置为 0
        """
        # 获取所有任务
        task_list = ExcelTool().readExcel()
        
        if len(task_list) <= 0:
            # 没有任务时返回提示
            reply_text = "⏰当前没有任务可取消~"
            self.replay_use_default(reply_text, e_context)
            return
        
        # 遍历所有任务，将 '是否可用' 列（列 B）设置为 0
        for task in task_list:
            task_id = task[0]  # 任务 ID
            ExcelTool().write_columnValue_withTaskId_toExcel(task_id, 2, "0")  # 列 B 是第 2 列
        
        # 刷新内存中的任务列表
        self.taskManager.refreshDataFromExcel()
        
        # 返回成功提示
        reply_text = "⏰所有任务已成功取消~"
        self.replay_use_default(reply_text, e_context)
  
        
    def on_handle_context(self, e_context: EventContext):
        context = e_context["context"]
        if context.type not in [ContextType.TEXT]:
            return
    
        # 查询内容
        query = context.content
        logging.info("定时任务的输入信息为:{}".format(query))
        
        # 指令前缀
        command_prefix = self.conf.get("command_prefix", "$time")
        
        # 如果输入内容以指令前缀开头，处理定时任务
        if query.startswith(command_prefix):
            # 检查用户是否已经通过管理员认证
            user = context["receiver"]
            isadmin = user in global_config.get("admin_users", [])  # 使用 global_config 检查管理员认证
    
            if not isadmin:
                reply = Reply()
                reply.type = ReplyType.ERROR
                reply.content = "您未通过管理员认证，无法使用定时任务功能。输入 #auth [口令] 进行认证。"
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS  # 明确中断事件处理流程
                return
    
            # 处理定时任务
            content = query.replace(f"{command_prefix}", "", 1).strip()
            self.deal_timeTask(content, e_context)

    #处理时间任务
    def deal_timeTask(self, content, e_context: EventContext):
        # 如果是任务列表命令，直接调用获取任务列表的方法
        if content.strip() == "任务列表":
            self.get_timeTaskList(content, e_context)
            return
        
        # 如果是取消所有任务命令，调用取消所有任务的方法
        if content.strip() == "取消所有任务":
            self.cancel_all_tasks(e_context)
            return
        
        # 如果是取消任务命令，调用取消任务的方法
        if content.startswith("取消任务"):
            # 解析任务编号
            task_id = content.replace("取消任务", "").strip()
            if task_id:
                self.cancel_timeTask(task_id, e_context)
            else:
                self.replay_use_default("⏰定时任务指令格式异常😭，请核查！", e_context)
            return
        
        # 解析 t[1-3]
        delay_match = re.search(r't\[(\d+-\d+)\]', content)
        delay_range = delay_match.group(1) if delay_match else ""
        
        # 移除 t[1-3] 从 content 中
        content = re.sub(r't\[\d+-\d+\]', '', content).strip()
        
        # 解析周期、时间、事件
        circleStr, timeStr, eventStr = self.get_timeInfo(content)
        
        # 检查是否指定了群聊或个人任务，考虑换行符
        group_match = re.search(r'group\[([^\]]+)\]', eventStr, re.DOTALL)
        user_match = re.search(r'user\[([^\]]+)\]', eventStr, re.DOTALL)
        
        # 处理群任务
        if group_match:
            group_title = group_match.group(1).strip()
            group_id = self._get_group_id_by_title(group_title)  # 获取群 ID
            if group_id:
                eventStr = re.sub(r'group\[([^\]]+)\]', '', eventStr, flags=re.DOTALL).strip()
                # 设置群 ID 和其他字段
                e_context["context"]["msg"].other_user_id = group_id
                e_context["context"]["msg"].other_user_nickname = group_title
                e_context["context"]["msg"].is_group = True  # 设置为群聊任务
                # 将群名称写入 toUser 字段（列 H）
                e_context["context"]["msg"].to_user_nickname = group_title
            else:
                self.replay_use_default(f"未找到群: {group_title}", e_context)
                return
        
        # 处理个人任务
        if user_match:
            user_nickname = user_match.group(1).strip()
            user_id = self._get_user_nickname_by_nickname(user_nickname)
            if user_id:
                eventStr = re.sub(r'user\[([^\]]+)\]', '', eventStr, flags=re.DOTALL).strip()
                # 设置目标用户 ID
                e_context["context"]["msg"].other_user_id = user_id
                # 将用户昵称写入 toUser 字段（列 H）
                e_context["context"]["msg"].to_user_nickname = user_nickname
            else:
                self.replay_use_default(f"未找到用户: {user_nickname}", e_context)
                return
        
        # 容错
        if len(circleStr) <= 0 or len(timeStr) <= 0 or len(eventStr) <= 0:
            self.replay_use_default("⏰定时任务指令格式异常😭，请核查！", e_context)
            return
        
        # 获取消息对象
        msg: ChatMessage = e_context["context"]["msg"]
        
        # 初始化 taskInfo
        taskInfo = (
            "",  # ID - 唯一ID (自动生成，无需填写)
            "1",  # 是否可用 - 0/1，0=不可用，1=可用
            timeStr,  # 时间信息 - 格式为：HH:mm:ss
            circleStr,  # 轮询信息 - 格式为：每天、每周X、YYYY-MM-DD
            eventStr,  # 消息内容 - 消息内容
            msg.from_user_nickname,  # fromUser - 来源user
            msg.from_user_id,  # fromUserID - 来源user ID
            msg.to_user_nickname,  # toUser - 发送给的user
            msg.to_user_id,  # toUser id - 来源user ID
            msg.other_user_nickname,  # other_user_nickname - Other名称
            msg.other_user_id,  # other_user_id - otehrID
            "1" if msg.is_group else "0",  # isGroup - 0/1，是否群聊； 0=否，1=是
            str(msg),  # 原始内容 - 原始的消息体
            "0",  # 今天是否被消费 - 每天会在凌晨自动重置
            delay_range  # 延时区间时间
        )
        
        # 创建 TimeTaskModel 实例
        taskModel = TimeTaskModel(taskInfo, msg, True, client=self.client, app_id=self.app_id)
        
        # 一次性任务的时间若已经过去（如 16:09 创建"今天 14:10"的任务），
        # 该任务永远等不到触发时刻，也不会出现在任务列表中，只会静静地留在活动表里
        # 直到次日 04:00 被迁移，用户却收到"创建成功"的回复。此处直接拦截并提示。
        if self._is_expired_once_task(taskModel):
            self.replay_use_default(
                f"⏰任务时间【{taskModel.circleTimeStr} {taskModel.timeStr}】已经过去了😭\n"
                f"【当前时间】：{arrow.now().format('YYYY-MM-DD HH:mm:ss')}\n"
                f"该任务不会被执行，请设置一个晚于当前时间的时间。",
                e_context,
            )
            return
        
        # 添加任务
        taskId = self.taskManager.addTask(taskModel)
        
        # 回消息
        reply_text = ""
        tempStr = ""
        if len(taskId) > 0:
            tempStr = self.get_default_remind(TimeTaskRemindType.Add_Success)
            taskStr = ""
            if taskModel.isCron_time():
                taskStr = f"{circleStr} {taskModel.eventStr}"
            else:
                taskStr = f"{circleStr} {timeStr} {taskModel.eventStr}"
            
            # 任务类型和对象
            task_type = "群任务" if msg.is_group else "个人任务"
            task_target = group_title if msg.is_group else (user_nickname if 'user_nickname' in locals() else msg.other_user_nickname or msg.from_user_nickname)
            
            # 延时时间
            delay_info = f"【延时时间】：{delay_range}分钟" if delay_range else ""
            
            # 构建回复消息
            reply_text = f"恭喜你，⏰定时任务已创建成功🎉~\n【任务编号】：{taskId}\n【任务详情】：{taskStr}\n【任务类型】：{task_type}\n【任务对象】：{task_target}\n{delay_info}"
        else:
            tempStr = self.get_default_remind(TimeTaskRemindType.Add_Failed)
            reply_text = f"sorry，⏰定时任务创建失败😭"
        
        # 拼接提示
        reply_text = reply_text + tempStr
        
        # 回复
        self.replay_use_default(reply_text, e_context)
        
    #是否为"时间已过"的一次性任务
    def _is_expired_once_task(self, model: TimeTaskModel):
        """判断任务是否为"永远不会再触发"的一次性任务。

        - cron、每天/每周/工作日 等循环任务永远有下一次，放行；
        - 时间点正好落在当前分钟（is_nowTime）仍会被触发，放行；
        - 今天的一次性任务且时间点已过 => 过期；
        - 具体日期早于今天 => 过期。
        """
        #循环任务放行
        if model.isCron_time() or model.is_recurring_task():
            return False
        
        #当前分钟内的任务仍会正常触发，放行
        is_now, _ = model.is_nowTime()
        if is_now:
            return False
        
        #今天的一次性任务：时间点已过 => 过期
        if model.is_today():
            return not model.is_featureTime()
        
        #具体日期：早于今天 => 过期
        if model.is_valid_date(model.circleTimeStr):
            return arrow.get(model.circleTimeStr, 'YYYY-MM-DD').date() < arrow.now().date()
        
        return False
        
    #取消任务
    def cancel_timeTask(self, task_id, e_context: EventContext):
        """
        取消指定任务编号的任务
        """
        # 检查任务编号是否为空
        if not task_id:
            self.replay_use_default("⏰任务编号不能为空，请核查！", e_context)
            return
        
        # 调用 ExcelTool 取消任务
        isExist, taskModel = ExcelTool().write_columnValue_withTaskId_toExcel(task_id, 2, "0")  # 列 B 是第 2 列
        taskContent = "未知"
        if taskModel:
            taskContent = f"{taskModel.circleTimeStr} {taskModel.timeStr} {taskModel.eventStr}"
            if taskModel.isCron_time():
                taskContent = f"{taskModel.circleTimeStr} {taskModel.eventStr}"
        
        # 回消息
        reply_text = ""
        tempStr = ""
        if isExist:
            tempStr = self.get_default_remind(TimeTaskRemindType.Cancel_Success)
            reply_text = "⏰定时任务，取消成功~\n" + "【任务编号】：" + task_id + "\n" + "【任务详情】：" + taskContent
        else:
            tempStr = self.get_default_remind(TimeTaskRemindType.Cancel_Failed)
            reply_text = "⏰定时任务，取消失败😭，未找到任务编号，请核查\n" + "【任务编号】：" + task_id
        
        # 拼接提示
        reply_text = reply_text + tempStr
        
        # 回复
        self.replay_use_default(reply_text, e_context)
        
        # 刷新内存列表
        self.taskManager.refreshDataFromExcel()
        
        
    #获取任务列表
    def get_timeTaskList(self, content, e_context: EventContext):
        # 任务列表
        taskArray = ExcelTool().readExcel()
        tempArray = []
        for item in taskArray:
            model = TimeTaskModel(item, None, False)
            if model.enable and model.taskId and len(model.taskId) > 0:
                isToday = model.is_today()
                is_now, _ = model.is_nowTime()
                isNowOrFeatureTime = model.is_featureTime() or is_now
                isCircleFeatureDay = model.is_featureDay()
                if (isToday and isNowOrFeatureTime) or isCircleFeatureDay:
                    tempArray.append(model)
        
        # 回消息
        reply_text = ""
        tempStr = ""
        if len(tempArray) <= 0:
            tempStr = self.get_default_remind(TimeTaskRemindType.NO_Task)
            reply_text = "⏰当前无待执行的任务列表"
        else:
            tempStr = self.get_default_remind(TimeTaskRemindType.TaskList_Success)
            reply_text = "⏰定时任务列表如下：\n\n"
            # 根据时间排序
            sorted_times = sorted(tempArray, key=lambda x: self.custom_sort(x.timeStr))
            for model in sorted_times:
                taskModel : TimeTaskModel = model
                tempTimeStr = f"{taskModel.circleTimeStr} {taskModel.timeStr}"
                if taskModel.isCron_time():
                    tempTimeStr = f"{taskModel.circleTimeStr}"
                
                # 任务类型和对象
                task_type = "群任务" if taskModel.isGroup else "个人任务"
                task_target = taskModel.toUser if taskModel.toUser else "未知"  # 从列 H 中提取对象名称
                
                # 延时时间
                delay_info = f"【延时时间】：{taskModel.delay_range}分钟" if taskModel.delay_range else ""
                
                # 构建任务详情
                reply_text += f"【{taskModel.taskId}】@{taskModel.fromUser}: {tempTimeStr} {taskModel.eventStr}\n"
                reply_text += f"【任务类型】：{task_type}\n"
                reply_text += f"【任务对象】：{task_target}\n"
                if delay_info:
                    reply_text += f"{delay_info}\n"
                reply_text += "\n"  # 添加空行分隔任务
            
            # 移除最后一个换行
            reply_text = reply_text.rstrip('\n')
            
        # 拼接提示
        reply_text = reply_text + tempStr
        
        # 回复
        self.replay_use_default(reply_text, e_context)  
        
          
    #添加任务
    def add_timeTask(self, content, e_context: EventContext):
        # 失败时，默认提示
        defaultErrorMsg = "⏰定时任务指令格式异常😭，请核查！" + self.get_default_remind(TimeTaskRemindType.Add_Failed)
        
        # 周期、时间、事件
        circleStr, timeStr, eventStr = self.get_timeInfo(content)
        
        
        # 检查是否指定了群聊
        group_match = re.match(r'.*group\[([^\]]+)\]', eventStr)
        if group_match:
            group_title = group_match.group(1)
            group_id = self._get_group_id_by_title(group_title)  # 获取群 ID
            if group_id:
                eventStr = eventStr.replace(f"group[{group_title}]", "").strip()
                # 设置群 ID 和其他字段
                e_context["context"]["msg"].other_user_id = group_id
                e_context["context"]["msg"].other_user_nickname = group_title
                e_context["context"]["msg"].is_group = True  # 设置为群聊任务
            else:
                self.replay_use_default(f"未找到群: {group_title}", e_context)
                return
        
        
        # 检查是否指定了用户
        user_match = re.match(r'.*user\[([^\]]+)\]', eventStr)
        if user_match:
            user_nickname = user_match.group(1)
            user_id = self._get_user_nickname_by_nickname(user_nickname)
            if user_id:
                eventStr = eventStr.replace(f"user[{user_nickname}]", "").strip()
                # 设置目标用户 ID
                e_context["context"]["msg"].other_user_id = user_id
            else:
                self.replay_use_default(f"未找到用户: {user_nickname}", e_context)
                return
        
        # 容错
        if len(circleStr) <= 0 or len(timeStr) <= 0 or len(eventStr) <= 0 :
            self.replay_use_default(defaultErrorMsg, e_context)
            return
        
        # 0：ID - 唯一ID (自动生成，无需填写) 
        # 1：是否可用 - 0/1，0=不可用，1=可用
        # 2：时间信息 - 格式为：HH:mm:ss
        # 3：轮询信息 - 格式为：每天、每周X、YYYY-MM-DD
        # 4：消息内容 - 消息内容
        msg: ChatMessage = e_context["context"]["msg"]
        taskInfo = ("",
                    "1", 
                    timeStr, 
                    circleStr, 
                    eventStr, 
                    msg)

        # 创建 TimeTaskModel 实例时传入 client 和 app_id
        taskModel = TimeTaskModel(taskInfo, msg, True, client=self.client, app_id=self.app_id)
        
        if not taskModel.isCron_time():
            # 时间转换错误
            if len(taskModel.timeStr) <= 0 or len(taskModel.circleTimeStr) <= 0:
                self.replay_use_default(defaultErrorMsg, e_context)
                return
        else:
            # cron表达式格式错误
            if not taskModel.isValid_Cron_time():
               self.replay_use_default(defaultErrorMsg, e_context)
               return
           
        # 私人为群聊任务
        if taskModel.isPerson_makeGrop():
            newEvent, groupTitle = taskModel.get_Persion_makeGropTitle_eventStr()
            if len(groupTitle) <= 0 or len(newEvent) <= 0 :
               self.replay_use_default(defaultErrorMsg, e_context)
               return
            else:
                channel_name = RobotConfig.conf().get("channel_type", "wx")
                groupId = taskModel.get_gropID_withGroupTitle(groupTitle , channel_name)
                if len(groupId) <= 0:
                    defaultErrorMsg = f"⏰定时任务指令格式异常😭，未找到群名为【{groupTitle}】的群聊，请核查！" + self.get_default_remind(TimeTaskRemindType.Add_Failed)
                    self.replay_use_default(defaultErrorMsg, e_context)
                    return
        
        # task入库
        taskId = self.taskManager.addTask(taskModel)
        # 回消息
        reply_text = ""
        tempStr = ""
        if len(taskId) > 0:
            tempStr = self.get_default_remind(TimeTaskRemindType.Add_Success)
            taskStr = ""
            if taskModel.isCron_time():
                taskStr = f"{circleStr} {taskModel.eventStr}"
            else:
                taskStr = f"{circleStr} {timeStr} {taskModel.eventStr}"
            reply_text = f"恭喜你，⏰定时任务已创建成功🎉~\n【任务编号】：{taskId}\n【任务详情】：{taskStr}"
        else:
            tempStr = self.get_default_remind(TimeTaskRemindType.Add_Failed)
            reply_text = f"sorry，⏰定时任务创建失败😭"
            
        # 拼接提示
        reply_text = reply_text + tempStr
            
        # 回复
        self.replay_use_default(reply_text, e_context)
        
        

    def _get_user_nickname_by_nickname(self, nickname):
        """根据昵称或备注名获取用户 ID"""
        try:
            # 获取所有联系人列表
            contacts_response = self.client.fetch_contacts_list(self.app_id)
            print(f"[difytimetask] fetch_contacts_list 返回数据: {contacts_response}")  # 打印返回数据
            if contacts_response.get('ret') == 200:
                # 提取好友的 wxid 列表
                wxids = contacts_response.get('data', {}).get('friends', [])
                print(f"[difytimetask] 提取的 wxids: {wxids}")  # 打印提取的 wxids
    
                # 如果 wxids 为空，直接返回 None
                if not wxids:
                    logger.error("[difytimetask] 未找到有效的 wxid")
                    return None
    
                # 分批获取详细信息（每次最多 20 个 wxid）
                for i in range(0, len(wxids), 20):
                    batch_wxids = wxids[i:i + 20]  # 每次最多 20 个 wxid
                    # 获取当前批次的详细信息
                    detail_response = self.client.get_detail_info(self.app_id, batch_wxids)
                    print(f"[difytimetask] get_detail_info 返回数据: {detail_response}")  # 打印详细信息
                    if detail_response.get('ret') == 200:
                        details = detail_response.get('data', [])
                        # 遍历详细信息，查找匹配的昵称或备注名
                        for detail in details:
                            # 检查昵称或备注名是否匹配
                            if detail.get('nickName') == nickname or detail.get('remark') == nickname:
                                return detail.get('userName')  # 返回 wxid
        except Exception as e:
            logger.error(f"[difytimetask] 获取用户信息失败: {e}")
            return None
        
    #获取时间信息
    def get_timeInfo(self, content):
        # 如果是任务列表命令，直接返回空值
        if content.strip() == "任务列表":
            return "", "", ""
        
        # 周期
        circleStr = ""
        # 时间
        timeStr = ""
        # 事件
        eventStr = ""
        
        # 时间格式判定
        if content.startswith("cron[") or content.startswith("Cron["):
            # cron表达式； 格式示例："cron[0,30 14 * 3 3] 吃饭"
            # 找到第一个 "]"
            cron_end_index = content.find("]")
            # 找到了
            if cron_end_index != -1:
                # 分割字符串为 A 和 B
                corn_string = content[:cron_end_index+1]
                eventStr :str = content[cron_end_index + 1:]
                eventStr = eventStr.strip()
                circleStr = corn_string
                timeStr = corn_string
            else:
                print("cron表达式 格式异常！")
        
        else:  
            # 分割
            wordsArray = content.split(" ")
            if len(wordsArray) <= 2:
                logging.info("指令格式异常，请核查")
            else:
                # 指令解析
                # 周期
                circleStr = wordsArray[0]
                # 时间
                timeStr = self.format_time(wordsArray[1])  # 调用时间格式化函数
                # 事件
                eventStr = ' '.join(map(str, wordsArray[2:])).strip()
        
        return circleStr, timeStr, eventStr
            

    def format_time(self, time_str):
        """将不完整的时间格式转换为标准的 HH:mm:ss 格式"""
        try:
            # 如果时间字符串为空，返回默认时间
            if not time_str:
                return "00:00:00"
            
            # 如果时间字符串包含秒，直接返回
            if len(time_str.split(':')) == 3:
                return time_str
            
            # 分割小时和分钟
            parts = time_str.split(':')
            if len(parts) == 1:
                # 只有小时，补全分钟和秒
                hour = parts[0].zfill(2)
                return f"{hour}:00:00"
            elif len(parts) == 2:
                # 有小时和分钟，补全秒
                hour, minute = parts
                hour = hour.zfill(2)
                minute = minute.zfill(2)
                return f"{hour}:{minute}:00"
            else:
                # 其他情况，返回默认时间
                return "00:00:00"
        except Exception as e:
            logging.error(f"时间格式化失败: {e}")
            return "00:00:00"  # 如果格式化失败，返回默认时间


    #使用默认的回复
    def replay_use_default(self, reply_message, e_context: EventContext):
        #回复内容
        reply = Reply()
        reply.type = ReplyType.TEXT
        reply.content = reply_message
        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS  # 事件结束，并跳过处理context的默认逻辑
        
    #使用自定义回复
    def replay_use_custom(self, model: TimeTaskModel, reply_text: str, replyType: ReplyType, context :Context, retry_cnt=0):
                
        try:    
            reply = Reply()
            reply.type = replyType
            reply.content = reply_text
            channel_name = RobotConfig.conf().get("channel_type", "wx")
            channel = channel_factory.create_channel(channel_name)
            channel.send(reply, context)
            
            #释放
            channel = None
            gc.collect()    
                
        except Exception as e:
            if retry_cnt < 2:
                time.sleep(3 + 3 * retry_cnt)
                self.replay_use_custom(model, reply_text, replyType, context,retry_cnt + 1)
            
        
    # ==================== 每日一句：确定性轮换实现 ====================

    @staticmethod
    def _daily_norm(text):
        """只保留中文字符，用于比对句子是否同一句（忽略标点差异）"""
        return re.sub(r"[^\u4e00-\u9fff]", "", str(text or ""))

    def _load_daily_state(self):
        try:
            with open(self.DAILY_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_daily_state(self, data):
        try:
            os.makedirs(os.path.dirname(self.DAILY_STATE_FILE), exist_ok=True)
            with open(self.DAILY_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"[difytimetask] 每日一句轮换状态保存失败: {e}")

    def build_daily_rotation(self, task_id):
        """推进轮换状态并返回本次的生成参数指令（与日期无关，重启后依然连续）"""
        state = self._load_daily_state()
        task = state.get(task_id) or {}
        day_index = int(task.get("day_index", 0))
        author_index = int(task.get("author_index", 0))
        used_quotes = task.get("used_quotes") or []
        recent = task.get("recent") or []

        type_name = self.DAILY_TYPE_CYCLE[day_index % len(self.DAILY_TYPE_CYCLE)]
        topic = self.DAILY_TOPICS[(day_index * 3) % len(self.DAILY_TOPICS)]

        lines = ["", "【本次生成参数】以下为内部参数，禁止复述，禁止出现在最终输出里："]
        if type_name == "名言":
            group = self.DAILY_AUTHOR_GROUPS[author_index % len(self.DAILY_AUTHOR_GROUPS)]
            author_index += 1
            lines.append("- 本条类型：类型3（真实名人名言）")
            if "鬼谷子" in group["authors"]:
                used_norm = [self._daily_norm(q) for q in used_quotes]
                remaining = [q for q in self.DAILY_GUGUZI_POOL if self._daily_norm(q) not in used_norm]
                if not remaining:
                    remaining = list(self.DAILY_GUGUZI_POOL)
                lines.append("- 本条限定作者：鬼谷子（商道谋略主题，用于经营与取舍语境）")
                lines.append("- 必须从下列句池中原样引用一条，一字不改，不得拼接两句，不得引用池外句子：")
                lines.extend([f"    {i + 1}. {q}" for i, q in enumerate(remaining)])
            else:
                lines.append(f"- 本条限定作者：只能从这几位里选一位：{'、'.join(group['authors'])}")
                lines.append("- 必须逐字忠于该名人的原句，可只截取其中完整的一句，绝对不许增字、漏字或改写")
        elif type_name == "原创金句":
            lines.append("- 本条类型：类型2（原创正能量金句），不要署名，不要英文原文")
        else:
            lines.append("- 本条类型：类型1（原创正能量早安问候），不要署名，不要英文原文")

        lines.append(f"- 本条主题域：{topic}")
        lines.append("- 长度：正文 20~50 个字；引用较长名言时可放宽到 60 个字；中文部分总计不超过 80 字")
        if recent:
            lines.append("- 最近已发布过的内容，必须避开，不得重复句子、句式与核心意象：")
            lines.extend([f"    · {str(r).replace(chr(10), ' / ')}" for r in recent[-5:]])
        lines.append("- 只输出成品本身，从【每日一句】那一行开始输出")

        state[task_id] = {
            "day_index": day_index + 1,
            "author_index": author_index,
            "used_quotes": used_quotes,
            "recent": recent,
            "last_type": type_name,
        }
        self._save_daily_state(state)
        logging.info(f"[difytimetask] 每日一句轮换 任务{task_id} 第{day_index + 1}次 -> {type_name} / 主题{topic}")
        return "\n".join(lines)

    def record_daily_output(self, task_id, reply_text):
        """记录已发布内容，供后续几天避重（含鬼谷子已用句）"""
        clean = str(reply_text or "").strip()
        if not clean:
            return
        state = self._load_daily_state()
        task = state.get(task_id) or {}
        recent = (task.get("recent") or []) + [clean]
        used_quotes = task.get("used_quotes") or []
        clean_norm = self._daily_norm(clean)
        for q in self.DAILY_GUGUZI_POOL:
            if self._daily_norm(q) in clean_norm and q not in used_quotes:
                used_quotes.append(q)
        task["recent"] = recent[-8:]
        task["used_quotes"] = used_quotes[-30:]
        state[task_id] = task
        self._save_daily_state(state)

    #执行定时task
    def runTimeTask(self, model: TimeTaskModel):
        
        #事件内容
        eventStr = model.eventStr
        #发送的用户ID
        other_user_id = model.other_user_id
        #是否群聊
        isGroup = model.isGroup
        
        #是否个人为群聊制定的任务
        if model.isPerson_makeGrop():
            newEvent, groupTitle = model.get_Persion_makeGropTitle_eventStr()
            eventStr = newEvent
            channel_name = RobotConfig.conf().get("channel_type", "wx")
            groupId = model.get_gropID_withGroupTitle(groupTitle , channel_name)
            other_user_id = groupId
            isGroup = True
            if len(groupId) <= 0:
                logging.error(f"通过群标题【{groupTitle}】,未查到对应的群ID, 跳过本次消息")
                return
        
        print("触发了定时任务：{} , 任务详情：{}".format(model.taskId, eventStr))
        
        #去除多余字符串
        orgin_string = model.originMsg.replace("ChatMessage:", "")
        # 使用正则表达式匹配键值对
        pattern = r'(\w+)\s*=\s*([^,]+)'
        matches = re.findall(pattern, orgin_string)
        # 创建字典
        content_dict = {match[0]: match[1] for match in matches}
        #替换源消息中的指令
        content_dict["content"] = eventStr
        #添加必要key
        content_dict["receiver"] = other_user_id
        content_dict["session_id"] = other_user_id
        content_dict["isgroup"] = isGroup
        content_dict["from_plugin"] = "difytimetask"
        msg : ChatMessage = ChatMessage(content_dict)
        #信息映射
        for key, value in content_dict.items():
            if hasattr(msg, key):
                setattr(msg, key, value)
        #处理message的is_group
        msg.is_group = isGroup
        content_dict["msg"] = msg
        context = Context(ContextType.TEXT, eventStr, content_dict)
        # 注入 channel：dify_bot 等 bot 发送"中间结果"（如 Dify 返回的卡片图片）时依赖
        # context["channel"]，正常消息流程由 chat_channel._generate_reply 设置；
        # 定时任务是自己构造 context，之前缺失该字段，导致图片类中间回复被静默丢弃，
        # 只发出最后一段纯文本（表现为：手动发消息有卡片图、定时推送只有文字）
        try:
            channel_name = RobotConfig.conf().get("channel_type", "wx")
            context["channel"] = channel_factory.create_channel(channel_name)
        except Exception as e:
            logging.error(f"[difytimetask] 注入 channel 失败，图片类中间回复将无法发送: {e}")
        
        #处理GPT
        event_content = eventStr
        key_word = "GPT"
        isGPT = event_content.startswith(key_word)
    
        #GPT处理
        if isGPT:
            index = event_content.find(key_word)
            #内容体      
            event_content = event_content[:index] + event_content[index+len(key_word):]
            event_content = event_content.strip()
            #每日一句轮换：注入本次的类型/限定作者/主题/避重清单（仅带标记的任务生效）
            daily_rotation_taskId = None
            if self.DAILY_ROTATION_MARK in event_content:
                event_content = event_content.replace(self.DAILY_ROTATION_MARK, "").strip()
                daily_rotation_taskId = model.taskId
                #独立会话：每日一句不复用群聊会话，避免与群聊的 conversation_id 串号
                daily_session_id = f"{other_user_id}__dailysentence"
                content_dict["session_id"] = daily_session_id
                context.__setitem__("session_id", daily_session_id)
                if msg is not None:
                    msg.session_id = daily_session_id
                #可选：路由到"每日一句"专用Dify应用；未配置则沿用全局应用，行为与原来完全一致
                daily_app_key = str(self.conf.get("dify_daily_app_key", "") or "").strip()
                if daily_app_key:
                    context.__setitem__("dify_api_key", daily_app_key)
                    daily_app_type = str(self.conf.get("dify_daily_app_type", "") or "").strip()
                    if daily_app_type:
                        context.__setitem__("dify_app_type", daily_app_type)
                    daily_app_base = str(self.conf.get("dify_daily_app_base", "") or "").strip()
                    if daily_app_base:
                        context.__setitem__("dify_api_base", daily_app_base)
                    logging.info("[difytimetask] 每日一句已路由到专用Dify应用")
                try:
                    event_content = event_content + "\n" + self.build_daily_rotation(daily_rotation_taskId)
                except Exception as e:
                    daily_rotation_taskId = None
                    logging.error(f"[difytimetask] 每日一句轮换参数生成失败，按原提示词执行: {e}")
            #替换源消息中的指令
            content_dict["content"] = event_content
            msg.content = event_content
            context.__setitem__("content",event_content)
        
            content = context.content.strip()
            imgPrefix = RobotConfig.conf().get("image_create_prefix")
            img_match_prefix = self.check_prefix(content, imgPrefix)
            if img_match_prefix:
                content = content.replace(img_match_prefix, "", 1)
                context.type = ContextType.IMAGE_CREATE
            
            #获取回复信息
            replay :Reply = Bridge().fetch_reply_content(content, context)
            if daily_rotation_taskId and replay and replay.content:
                try:
                    self.record_daily_output(daily_rotation_taskId, replay.content)
                except Exception as e:
                    logging.error(f"[difytimetask] 每日一句发布记录保存失败: {e}")
            self.replay_use_custom(model,replay.content,replay.type, context)
            return

        #变量
        e_context = None
        # 是否开启了所有回复路由
        is_open_route_everyReply = self.conf.get("is_open_route_everyReply", True)
        if is_open_route_everyReply:
            try:
                # 检测插件是否会消费该消息
                e_context = PluginManager().emit_event(
                    EventContext(
                        Event.ON_HANDLE_CONTEXT,
                        {"channel": self.channel, "context": context, "reply": Reply()},
                    )
                )
            except  Exception as e:
                print(f"开启了所有回复均路由，但是消息路由插件异常！后续会继续查询是否开启拓展功能。错误信息：{e}")

        #查看配置中是否开启拓展功能
        is_open_extension_function = self.conf.get("is_open_extension_function", True)
        #需要拓展功能 & 未被路由消费
        route_replyType = None
        if e_context:
            route_replyType = e_context["reply"].type
        if is_open_extension_function and route_replyType is None:
            #事件字符串
            event_content = eventStr
            #支持的功能
            funcArray = self.conf.get("extension_function", [])
            for item in funcArray:
              key_word = item["key_word"]
              func_command_prefix = item["func_command_prefix"]
              #匹配到了拓展功能
              isFindExFuc = False
              if event_content.startswith(key_word):
                index = event_content.find(key_word)
                insertStr = func_command_prefix + key_word 
                #内容体      
                event_content = event_content[:index] + insertStr + event_content[index+len(key_word):]
                event_content = event_content.strip()
                isFindExFuc = True
                break
            
            #找到了拓展功能
            if isFindExFuc:
                #替换源消息中的指令
                content_dict["content"] = event_content
                msg.content = event_content
                context.__setitem__("content",event_content)
                
                try:
                    #检测插件是否会消费该消息
                    e_context = PluginManager().emit_event(
                        EventContext(
                            Event.ON_HANDLE_CONTEXT,
                            {"channel": self.channel, "context": context, "reply": Reply()},
                        )
                    )
                except  Exception as e:
                    print(f"路由插件异常！将使用原消息回复。错误信息：{e}")
            
        #回复处理
        reply_text = ""
        replyType = None
        #插件消息
        if e_context:
            reply = e_context["reply"]
            if reply and reply.type: 
                reply_text = reply.content
                replyType = reply.type
            
        #原消息
        if reply_text is None or len(reply_text) <= 0:
            #标题
            if self.conf.get("is_need_title_whenNormalReply", True):
                reply_text += f"⏰叮铃铃，定时任务时间已到啦~\n"
            #时间
            if self.conf.get("is_need_currentTime_whenNormalReply", True):
                # 获取当前时间
                current_time = arrow.now()
                # 去除秒钟
                current_time_without_seconds = current_time.floor('minute')
                # 转换为指定格式的字符串
                formatted_time = current_time_without_seconds.format("YYYY-MM-DD HH:mm:ss")
                reply_text += f"【当前时间】：{formatted_time}\n"
            #任务标识
            if self.conf.get("is_need_identifier_whenNormalReply", True):
                reply_text += f"【任务编号】：{model.taskId}\n"
            #内容描述
            if self.conf.get("is_need_detailDeccription_whenNormalReply", True):
                reply_text += f"【任务详情】："

            reply_text += eventStr
            replyType = ReplyType.TEXT
                
        #消息回复
        self.replay_use_custom(model, reply_text, replyType, context)


    #检查前缀是否匹配
    def check_prefix(self, content, prefix_list):
        if not prefix_list:
            return None
        for prefix in prefix_list:
            if content.startswith(prefix):
                return prefix
        return None

    # 自定义排序函数，将字符串解析为 arrow 对象，并按时间进行排序
    def custom_sort(self, time):
        #cron - 排列最后
        if time.startswith("cron"):
            return arrow.get("23:59:59", "HH:mm:ss")
        
        #普通时间
        return arrow.get(time, "HH:mm:ss")
    
    # 默认的提示
    def get_default_remind(self, currentType: TimeTaskRemindType):
        # 指令前缀
        command_prefix = self.conf.get("command_prefix", "$time")
    
        #head
        head = "\n\n【温馨提示】\n"
        addTask = f"👉添加任务：{command_prefix} 今天 10:00 提醒我健身" + "\n" + f"👉cron任务：{command_prefix} cron[0 * * * *] 准点报时" + "\n"
        addTask += f"👉定群任务：{command_prefix} 今天 10:00 提醒我健身 group[群标题]" + "\n"
        addGPTTask = f"👉GPT任务：{command_prefix} 今天 10:00 GPT 夸夸我" + "\n"
        cancelTask = f"👉取消任务：{command_prefix} 取消任务 任务编号" + "\n"
        taskList = f"👉任务列表：{command_prefix} 任务列表" + "\n"
        cancelAllTask = f"👉取消所有任务：{command_prefix} 取消所有任务" + "\n"
        more = "👉更多功能：#help difytimetask"
        
        # NO_Task = 1           #无任务
        # Add_Success = 2       #添加任务成功
        # Add_Failed = 3        #添加任务失败
        # Cancel_Success = 4    #取消任务成功
        # Cancel_Failed = 5     #取消任务失败
        # TaskList_Success = 6  #查看任务列表成功
        # TaskList_Failed = 7   #查看任务列表失败
    
        #组装
        tempStr = head
        if currentType == TimeTaskRemindType.NO_Task:
           tempStr = tempStr + addTask + addGPTTask + cancelTask + taskList + cancelAllTask
            
        elif currentType == TimeTaskRemindType.Add_Success:
            tempStr = tempStr + cancelTask + taskList + cancelAllTask
            
        elif currentType == TimeTaskRemindType.Add_Failed:
            tempStr = tempStr + addTask + addGPTTask + cancelTask + taskList + cancelAllTask
            
        elif currentType == TimeTaskRemindType.Cancel_Success:
            tempStr = tempStr + addTask + addGPTTask + taskList + cancelAllTask 
            
        elif currentType == TimeTaskRemindType.Cancel_Failed:
            tempStr = tempStr + addTask + addGPTTask + cancelTask + taskList + cancelAllTask
            
        elif currentType == TimeTaskRemindType.TaskList_Success:
            tempStr = tempStr + addTask + addGPTTask + cancelTask + cancelAllTask
            
        elif currentType == TimeTaskRemindType.TaskList_Failed:
            tempStr = tempStr + addTask + addGPTTask + cancelTask + taskList + cancelAllTask   
                      
        else:
          tempStr = tempStr + addTask + addGPTTask + cancelTask + taskList + cancelAllTask
          
        #拼接help指令
        tempStr = tempStr + more
          
        return tempStr
    
    
    
    # 在 timetask.py 中增加以下代码

    
    def _get_user_nickname(self, user_id):
        """获取用户昵称"""
        try:
            response = requests.post(
                f"{conf().get('gewechat_base_url')}/contacts/getBriefInfo",
                json={
                    "appId": conf().get('gewechat_app_id'),
                    "wxids": [user_id]
                },
                headers={
                    "X-GEWE-TOKEN": conf().get('gewechat_token')
                }
            )
            if response.status_code == 200:
                data = response.json()
                if data.get('ret') == 200 and data.get('data'):
                    return data['data'][0].get('nickName', user_id)
            return user_id
        except Exception as e:
            logger.error(f"[difytimetask] 获取用户昵称失败: {e}")
            return user_id
        
    
    def _get_group_id_by_title(self, group_title):
        """根据群名称获取群 ID

        查找顺序（gewechat 通讯录仅含"已保存到通讯录"的群，故需多重回退）：
            1. 直接传入群 wxid：group[xxxx@chatroom]
            2. 通讯录精确匹配
            3. 本地群名索引精确匹配
            4. 本地群名索引模糊匹配
        """
        if not group_title:
            return None

        # 1) 支持直接填写群 wxid
        if group_title.endswith("@chatroom"):
            logger.info(f"[difytimetask] 直接使用群 wxid: {group_title}")
            return group_title

        # 2) 通讯录精确匹配（内部会把查到的群同步进本地群名索引）
        group_id = self._find_group_id_in_contacts(group_title)
        if group_id:
            return group_id

        # 3) 本地群名索引：精确优先，其次模糊
        try:
            from common.group_index import lookup_group_id, search_group_id

            group_id = lookup_group_id(group_title)
            if group_id:
                logger.info(f"[difytimetask] 命中本地群名索引: {group_title} -> {group_id}")
                return group_id

            matched = search_group_id(group_title)
            if matched:
                matched_name, group_id = matched
                logger.info(f"[difytimetask] 本地群名索引模糊匹配: {group_title} -> {matched_name} ({group_id})")
                return group_id
        except Exception as e:
            logger.debug(f"[difytimetask] 查询本地群名索引失败: {e}")

        return None

    def _find_group_id_in_contacts(self, group_title):
        """从通讯录按群名查找群 wxid（仅含已保存到通讯录的群）"""
        try:
            if not self.client:
                logger.error("[difytimetask] client 未初始化")
                return None
    
            if not self.app_id:
                logger.error("[difytimetask] app_id 未初始化")
                return None
    
            # 获取所有群聊列表
            contacts_response = self.client.fetch_contacts_list(self.app_id)
            logger.debug(f"[difytimetask] fetch_contacts_list 返回数据: {contacts_response}")
            if contacts_response.get('ret') == 200:
                chatrooms = contacts_response.get('data', {}).get('chatrooms', [])
                logger.info(f"[difytimetask] 群聊列表: {chatrooms}")
    
                # 提取所有群聊的 wxid
                wxids = [chatroom_id for chatroom_id in chatrooms if chatroom_id]
                logger.info(f"[difytimetask] 提取的 wxids: {wxids}")
    
                # 如果 wxids 为空，直接返回 None
                if not wxids:
                    logger.error("[difytimetask] 未找到有效的群聊 wxid")
                    return None
    
                # 分批获取详细信息（每次最多 20 个 wxid）
                for i in range(0, len(wxids), 20):
                    batch_wxids = wxids[i:i + 20]  # 每次最多 20 个 wxid
                    # 获取当前批次的详细信息
                    detail_response = self.client.get_detail_info(self.app_id, batch_wxids)
                    logger.debug(f"[difytimetask] get_detail_info 返回数据: {detail_response}")
                    if detail_response.get('ret') == 200:
                        details = detail_response.get('data', [])
                        # 遍历详细信息，查找匹配的群聊名称
                        for detail in details:
                            logger.debug(f"[difytimetask] 当前群聊信息: {detail}")
                            nick_name = detail.get('nickName')
                            user_name = detail.get('userName')
                            # 顺带同步进本地群名索引，便于该群日后被移出通讯录后仍可检索
                            if nick_name and user_name:
                                try:
                                    from common.group_index import record_group

                                    record_group(nick_name, user_name)
                                except Exception as e:
                                    logger.debug(f"[difytimetask] 记录群名索引失败: {e}")
                            if nick_name == group_title:
                                return user_name  # 返回群聊 wxid
        except Exception as e:
            logger.error(f"[difytimetask] 获取群信息失败: {e}")
    
        return None
    
    
    
    #help信息
    def get_help_text(self, **kwargs):
        # 指令前缀
        command_prefix = self.conf.get("command_prefix", "$time")
    
        help_text = """
    📌 功能介绍：添加定时任务、取消定时任务、获取任务列表、延时任务、个人任务、群任务等。
    
    🎉 功能一：添加定时任务
        【指令格式】: 
        {command_prefix} 周期 时间 事件 group[群标题] t[延时时间]
        {command_prefix} 周期 时间 事件 user[用户昵称] t[延时时间]
        【周期】: 
            - 今天、明天、后天
            - 每天、工作日
            - 每周X（如：每周三）
            - YYYY-MM-DD的日期
            - cron表达式（如：cron[0 * * * *]）
        【时间】: 
            - X点X分（如：十点十分）
            - HH:mm:ss的时间（如：10:00:00）
        【事件】: 
            - 早报、点歌、搜索
            - GPT（如：GPT 夸夸我）
            - 文案提醒（如：提醒我健身）
        【群任务】: 
            - 使用 group[群标题] 指定群聊，任务将在指定群聊中执行。
            - 示例: {command_prefix} 今天 10:00 提醒我健身 group[工作群]
        【个人任务】: 
            - 使用 user[用户昵称] 指定用户，任务将发送给指定用户。
            - 示例: {command_prefix} 今天 10:00 提醒我健身 user[小明]
        【延时任务】: 
            - 使用 t[延时时间] 指定任务的延时执行时间（单位：分钟）。
            - 示例: {command_prefix} 今天 10:00 提醒我健身 t[5-10] （表示任务将在10:05到10:10之间随机执行）
        【示例】:
            - 提醒任务: {command_prefix} 今天 10:00 提醒我健身
            - cron任务: {command_prefix} cron[0 * * * *] 准点报时
            - 定群任务: {command_prefix} 今天 10:00 提醒我健身 group[工作群]
            - 个人任务: {command_prefix} 今天 10:00 提醒我健身 user[小明]
            - 延时任务: {command_prefix} 今天 10:00 提醒我健身 t[5-10]
            - GPT任务: {command_prefix} 今天 10:00 GPT 夸夸我
    
    🎉 功能二：取消定时任务
        【指令格式】: {command_prefix} 取消任务 任务编号
        【任务编号】: 任务编号（添加任务成功时，机器人回复中有）
        【示例】: {command_prefix} 取消任务 urwOi0he
    
    🎉 功能三：取消所有任务
        【指令格式】: {command_prefix} 取消所有任务
        【示例】: {command_prefix} 取消所有任务
    
    🎉 功能四：获取任务列表
        【指令格式】: {command_prefix} 任务列表
        【示例】: {command_prefix} 任务列表
    
    🎉 功能五：延时任务
        【指令格式】: {command_prefix} 周期 时间 事件 t[延时时间]
        【延时时间】: 任务的延时执行时间（单位：分钟），格式为 t[最小延时-最大延时]。
        【示例】: {command_prefix} 今天 10:00 提醒我健身 t[5-10] （表示任务将在10:05到10:10之间随机执行）
    
    🎉 功能六：个人任务
        【指令格式】: {command_prefix} 周期 时间 事件 user[用户昵称]
        【用户昵称】: 指定接收任务的用户昵称。
        【示例】: {command_prefix} 今天 10:00 提醒我健身 user[小明]
    
    🎉 功能七：群任务
        【指令格式】: {command_prefix} 周期 时间 事件 group[群标题]
        【群标题】: 指定接收任务的群聊标题。
        【示例】: {command_prefix} 今天 10:00 提醒我健身 group[工作群]
        """.format(command_prefix=command_prefix)
    
        return help_text
