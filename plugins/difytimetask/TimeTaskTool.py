# encoding:utf-8

from plugins.difytimetask.Tool import ExcelTool
from plugins.difytimetask.Tool import TimeTaskModel
import logging
import time
import arrow
import threading
from typing import List
from plugins.difytimetask.config import conf, load_config
from lib import itchat
from lib.itchat.content import *
import config as RobotConfig
import random
from common.task_manager_registry import (
    register_task_manager,
    unregister_task_manager,
    claim_task_execution,
)



try:
    from channel.wechatnt.ntchat_channel import wechatnt
except Exception as e:
    print(f"未安装ntchat: {e}")


class TaskManager(object):

    #存活实例登记在 common.task_manager_registry 中，而不是类属性里。
    #原因：#scanp 插件重载会 importlib.reload 本模块，类属性会被重置，
    #旧实例的子线程虽然还在运行，却再也找不到、停不掉，
    #结果每重载一次就多一个检测线程并发触发同一任务、并发读写 timeTask.xlsx。

    #方法 handle_delay_for_recurring_task 来处理轮询任务的延时
    def handle_delay_for_recurring_task(self, model: TimeTaskModel):
        if model.delay_range:
            # 解析延时区间
            delay_min, delay_max = map(int, model.delay_range.split('-'))
            # 生成随机延时时间
            delay_time = random.randint(delay_min, delay_max)
            
            # 新任务的ID
            new_task_id = f"{model.taskId}_New"
            
            # 检查是否已经存在相同ID的任务
            existing_tasks = ExcelTool().readExcel()
            for task in existing_tasks:
                if task[0] == new_task_id:  # task[0] 是任务ID
                    print(f"任务 {new_task_id} 已存在，跳过创建")
                    return True  # 跳过创建，避免重复
            
            # 创建副本任务
            new_task_time = arrow.get(model.timeStr, "HH:mm:ss").shift(minutes=delay_time).format("HH:mm:ss")
            
            # 获取今日日期（年-月-日）
            today_date = arrow.now().format('YYYY-MM-DD')
            
            # 创建副本任务
            new_task = TimeTaskModel(
                (new_task_id, "1", new_task_time, today_date, model.eventStr, model.fromUser, model.fromUser_id, model.toUser, model.toUser_id, model.other_user_nickname, model.other_user_id, "1" if model.isGroup else "0", model.originMsg, "0"),
                None, False
            )
            
            # 添加副本任务
            ExcelTool().addItemToExcel(new_task.get_formatItem())
            
            # 标记母本任务为已执行（修改列N为1）
            ExcelTool().write_columnValue_withTaskId_toExcel(model.taskId, 14, "1")  # 修改列N为1
            
            # 刷新缓存及更新内存
            self.refreshDataFromExcel()
            
            # 跳过母本任务
            return True
        return False



    #方法 handle_delay_for_single_task 来处理单次任务的延时
    def handle_delay_for_single_task(self, model: TimeTaskModel):
        """
        处理延时单次任务：
        1. 解析延时区间（如 1-3）。
        2. 生成随机延时时间（如 2 分钟）。
        3. 修改任务的执行时间（修改 C 列）。
        4. 清空延时区间（清空 O 列）。
        5. 跳过当前任务，等待新时间执行。
        """
        if model.delay_range:
            try:
                # 解析延时区间
                delay_min, delay_max = map(int, model.delay_range.split('-'))
                # 生成随机延时时间
                delay_time = random.randint(delay_min, delay_max)
                
                # 修改任务时间（修改 C 列）
                task_time = arrow.get(model.timeStr, "HH:mm:ss")
                new_task_time = task_time.shift(minutes=delay_time).format("HH:mm:ss")
                
                # 更新任务时间（修改 C 列）
                ExcelTool().write_columnValue_withTaskId_toExcel(model.taskId, 3, new_task_time)  # 列 C 是第 3 列
                
                # 清空延时区间（清空 O 列）
                ExcelTool().write_columnValue_withTaskId_toExcel(model.taskId, 15, "")  # 列 O 是第 15 列
                
                # 打印日志
                print(f"任务 {model.taskId} 已延时 {delay_time} 分钟，新执行时间为 {new_task_time}")
                
                # 刷新缓存及更新内存
                self.refreshDataFromExcel()
                
                # 跳过当前任务
                return True
            except Exception as e:
                print(f"处理延时任务时发生错误: {e}")
                return False
        return False
    
    
    def __init__(self, timeTaskFunc):
        super().__init__()
        #保存定时任务回调
        self.timeTaskFunc = timeTaskFunc
        #线程停止信号
        self._stop_event = threading.Event()

        #登记当前实例，并停掉插件重载(#scanp)前遗留的旧实例，避免多线程重复触发任务
        for old_manager in register_task_manager(self):
            try:
                old_manager.stop()
            except Exception as e:
                print(f"[timeTask] 停止旧的定时任务线程失败：{e}")

        # 创建子线程
        t = threading.Thread(target=self.pingTimeTask_in_sub_thread)
        t.setDaemon(True) 
        t.start()

    #停止当前实例的检测线程
    def stop(self):
        self._stop_event.set()
        unregister_task_manager(self)

    #线程是否已停止
    def is_stopped(self):
        return self._stop_event.is_set()

    # 定义子线程函数
    def pingTimeTask_in_sub_thread(self):
        #延迟5秒后再检测，让初始化任务执行完（等待期间可被停止信号中断）
        if self._stop_event.wait(5):
            return
        
        #检测是否重新登录了
        self.isRelogin = False
        
        #迁移任务的标识符：用于标识在目标时间，只迁移一次
        self.moveHistoryTask_identifier = ""
        
        #刷新任务的标识符：用于标识在目标时间，只刷新一次
        self.refreshTimeTask_identifier = ""
        
        #存放历史数据
        self.historyTasks = []
        
        #配置加载
        load_config()
        self.conf = conf()
        self.debug = self.conf.get("is_debug", False)
        #迁移任务的时间
        self.move_historyTask_time = self.conf.get("move_historyTask_time", "04:00:00")
        #默认每秒检测一次
        self.time_check_rate = self.conf.get("time_check_rate", 1)
        
        #excel创建
        obj = ExcelTool()
        obj.create_excel()
        #任务数组
        self.refreshDataFromExcel()
        #过期任务数组、现在待消费数组、未来任务数组
        historyArray, _, _ = self.getFuncArray(self.timeTasks)
        #启动时，默认迁移一次过期任务
        self.moveTask_toHistory(historyArray)

        #循环
        while not self.is_stopped():
            try:
                # 定时检测
                self.timeCheck()
            except Exception as e:
                #单轮检测异常不能让整个定时任务线程死掉
                print(f"[timeTask] 定时检测异常：{e}")
            self._stop_event.wait(int(self.time_check_rate))
    
    #时间检查
    def timeCheck(self):
        
        #检测是否重新登录了
        self.check_isRelogin()
        #重新登录、未登录，均跳过
        if self.isRelogin:
            return
        
        #过期任务数组、现在待消费数组、未来任务数组
        modelArray = self.timeTasks
        historyArray, currentExpendArray, featureArray = self.getFuncArray(modelArray)
        
        #存放历史数据
        if len(historyArray) > 0:
            for item in historyArray:
                if item not in currentExpendArray and item not in featureArray and item not in self.historyTasks:
                      self.historyTasks.append(item)
        
        #是否到了凌晨00:00 - 目标时间，刷新今天的cron任务
        if self.is_targetTime("00:00"):
            #刷新cron时间任务、周期任务的今天执行态
            self.refresh_times(featureArray) 
        elif len(self.refreshTimeTask_identifier) > 0:
            self.refreshTimeTask_identifier = ""
            
        
        #是否到了迁移历史任务 - 目标时间
        if self.is_targetTime(self.move_historyTask_time):
            #迁移过期任务
            self.moveTask_toHistory(self.historyTasks)
        elif len(self.moveHistoryTask_identifier) > 0:
            self.moveHistoryTask_identifier = ""
            
        #任务数组
        if len(modelArray) <= 0:
            return
                    
        #将数组赋值数组，提升性能(若self.timeTasks 未被多线程更新，赋值为待执行任务组)
        timeTask_ids = '😄'.join(item.taskId for item in self.timeTasks)
        modelArray_ids = '😄'.join(item.taskId for item in modelArray)
        featureArray_ids = '😄'.join(item.taskId for item in featureArray)
        if timeTask_ids == modelArray_ids and timeTask_ids != featureArray_ids:
            #将任务数组 更新为 待执行数组； 当前任务在下面执行消费逻辑
            self.timeTasks = featureArray
            print(f"内存任务更新：原任务列表 -> 待执行任务列表")
            print(f"原任务ID列表：{timeTask_ids}")
            print(f"待执行任务ID列表：{featureArray_ids}")
        
        #当前无待消费任务     
        if len(currentExpendArray) <= 0:
            if self.debug:
                logging.info("[difytimetask][定时检测]：当前时刻 - 无定时任务...")
            return
        
        #消费当前task
        print(f"[difytimetask][定时检测]：当前时刻 - 存在定时任务, 执行消费 当前时刻任务")
        self.runTaskArray(currentExpendArray)
        
        
    #检测是否重新登录了    
    def check_isRelogin(self):
        #机器人ID
        robot_user_id = ""
        #通道
        channel_name = RobotConfig.conf().get("channel_type", "wx")
        if channel_name == "wx":
            robot_user_id = itchat.instance.storageClass.userName
        elif channel_name == "ntchat":
            try:
                login_info = wechatnt.get_login_info()
                nickname = login_info['nickname']
                user_id = login_info['wxid']
                robot_user_id = user_id
            except Exception as e:
                print(f"获取 ntchat的 userid 失败: {e}")
                #nt
                self.isRelogin = False
                return  
        else:
            #其他通道，默认不更新用户ID
            self.isRelogin = False
            return  
        
        #登录后
        if robot_user_id is not None and len(robot_user_id) > 0:
            #NTChat的userID不变  
            if channel_name == "ntchat":
                self.isRelogin = False
                return  
        
            #取出任务中的一个模型
            if self.timeTasks is not None and len(self.timeTasks) > 0: 
                model : TimeTaskModel = self.timeTasks[0]
                temp_isRelogin = robot_user_id != model.toUser_id
            
                if temp_isRelogin:
                    #更新为重新登录态
                    self.isRelogin = True
                    #等待登录完成
                    time.sleep(3)
                    
                    #更新userId
                    ExcelTool().update_userId()
                    #刷新数据
                    self.refreshDataFromExcel()
                    
                    #更新为非重新登录态
                    self.isRelogin = False
        else:
            #置为重新登录态
            self.isRelogin = True      
        
            
    #拉取Excel最新数据    
    def refreshDataFromExcel(self):
        tempArray = ExcelTool().readExcel()
        self.convetDataToModelArray(tempArray) 
        
    #迁移历史任务   
    def moveTask_toHistory(self, modelArray):
        if len(modelArray) <= 0:
            return
          
        #当前时间的小时：分钟
        current_time_hour_min = arrow.now().format('HH:mm')
        #执行中 - 标识符
        identifier_running = f"{current_time_hour_min}_running"
        #结束 - 标识符
        identifier_end = f"{current_time_hour_min}_end"
        
        #当前状态
        current_task_state = self.moveHistoryTask_identifier
        
        #未执行：本分钟尚未迁移过
        if current_task_state == "":
            #打印当前任务
            new_array = [item.taskId for item in self.timeTasks]
            print(f"[timeTask] 触发了迁移历史任务~ 当前任务ID为：{new_array}")
            
            #置为执行中
            self.moveHistoryTask_identifier = identifier_running
            #迁移任务
            newTimeTask = ExcelTool().moveTasksToHistoryExcel(modelArray)
            #数据刷新
            self.convetDataToModelArray(newTimeTask)
            #置为本分钟执行完成，防止同一分钟内重复迁移
            self.moveHistoryTask_identifier = identifier_end
            
        #执行中 / 本分钟已执行完成：同一分钟内不重复迁移
        elif current_task_state in (identifier_running, identifier_end):
            return
        
        #容错：跨分钟残留的旧标识符，复位后下一个目标时间才能再次迁移
        #（原实现用 == 写成比较表达式，导致标识符永远无法复位）
        else:
            self.moveHistoryTask_identifier = ""
                
                
    #刷新c任务   
    def refresh_times(self, modelArray):
        #当前时间的小时：分钟
        current_time_hour_min = arrow.now().format('HH:mm')
        #执行中 - 标识符
        identifier_running = f"{current_time_hour_min}_running"
        #结束 - 标识符
        identifier_end = f"{current_time_hour_min}_end"
        
        #当前状态
        current_task_state = self.refreshTimeTask_identifier
        
        #未执行
        if current_task_state == "":
            #打印此时任务
            new_array = [item.taskId for item in self.timeTasks]
            print(f"[timeTask] 触发了凌晨刷新任务~ 当前任务ID为：{new_array}")
            
            #置为执行中
            self.refreshTimeTask_identifier = identifier_running
            #刷新任务
            for m in modelArray:
                taskModel : TimeTaskModel = m
                taskModel.is_today_consumed = False
                ExcelTool().write_columnValue_withTaskId_toExcel(taskModel.taskId, 14, "0")
            
            #刷新数据
            self.refreshDataFromExcel()
            #置为本分钟执行完成，防止同一分钟内重复刷新
            self.refreshTimeTask_identifier = identifier_end
            
        #执行中 / 本分钟已执行完成：同一分钟内不重复刷新
        elif current_task_state in (identifier_running, identifier_end):
            return
        
        #容错：跨分钟残留的旧标识符，复位后下一个目标时间才能再次刷新
        #（原实现用 == 写成比较表达式，导致标识符永远无法复位）
        else:
            self.refreshTimeTask_identifier = ""
       
    #获取功能数组    
    def getFuncArray(self, modelArray):
        #待消费数组
        featureArray = []
        #当前待消费数组
        currentExpendArray=[]
        #过期任务数组
        historyArray=[]
        #遍历检查时间
        for item in modelArray:
            model : TimeTaskModel = item
            if model.enable:
                #是否现在时刻
                is_nowTime, nowTime = model.is_nowTime()
                #是否未来时刻
                is_featureTime = model.is_featureTime()
                #是否today
                is_today = model.is_today()
                #是否未来day
                is_featureDay = model.is_featureDay()
            
                #是否历史
                isHistory = True
                #由于一个model既可以是当前的任务，又可能是以后得任务，所以这里对一个model同时判定现在和未来的判定
                #是否现在时刻的任务
                if is_nowTime and is_today:
                    #精度为分钟，cron中消费本次任务
                    if model.isCron_time():
                       if nowTime in model.cron_today_times:
                            model.cron_today_times.remove(nowTime)
                            currentExpendArray.append(model)
                            isHistory = False
                        
                    #今天未被消费
                    elif not model.is_today_consumed:
                        currentExpendArray.append(model)
                        isHistory = False
                        model.is_today_consumed = True       
                
                #是否当前时刻后面待消费任务
                if (is_featureTime and is_today) or is_featureDay:
                    featureArray.append(model)
                    isHistory = False                     
                
                #存入历史数组
                #循环任务（每天/每周/工作日/cron）即使本次判定为过期也绝不能迁出活动表，
                #否则重启/重载时会被永久删除，任务再也不会触发。
                if isHistory and not self.is_recurring_model(model):
                    historyArray.append(model.get_formatItem())
            else:
                #已禁用的任务：循环任务保留在活动表，避免误判导致任务永久丢失
                if not self.is_recurring_model(model):
                    historyArray.append(model.get_formatItem())  
        
        return  historyArray, currentExpendArray, featureArray

    #是否循环任务（每天/每周/工作日/cron），这类任务不允许被迁移进历史任务
    def is_recurring_model(self, model: TimeTaskModel):
        try:
            return model.is_recurring_task() or model.isCron_time()
        except Exception as e:
            print(f"[timeTask] 判断任务是否循环失败：{e}")
            return False
    
        
          
    #执行task
    def runTaskArray(self, modelArray):
        try:
            #执行任务列表
            for _, model in enumerate(modelArray):
                self.runTaskItem(model)
        except Exception as e:
            print(f"执行定时任务，发生了错误：{e}")
            
                
    #执行task
    def runTaskItem(self, model: TimeTaskModel):
        
        #兜底去重：同一任务在同一分钟内只执行一次。
        #各检测线程内存中的消费态（is_today_consumed / cron_today_times）互不可见，
        #一旦存在多个线程（例如历史遗留线程），同一任务会被重复触发、重复发送。
        minute_key = arrow.now().format("YYYY-MM-DD HH:mm")
        if not claim_task_execution(model.taskId, minute_key):
            print(f"[timeTask] 任务【{model.taskId}】在 {minute_key} 已执行过，跳过重复触发")
            return
        
        if model.is_recurring_task():
            # 处理轮询任务延时
            if self.handle_delay_for_recurring_task(model):
                return
        else:
            # 处理单次任务延时
            if self.handle_delay_for_single_task(model):
                return
        
        #非cron，置为已消费
        if not model.isCron_time():
            model.is_today_consumed = True
            #置为消费
            ExcelTool().write_columnValue_withTaskId_toExcel(model.taskId, 14, "1")
        
        # 非延时任务或延时处理完成后，执行任务
        print(f"😄执行定时任务:【{model.taskId}】，任务详情：{model.circleTimeStr} {model.timeStr} {model.eventStr}")
        # 回调定时任务执行
        self.timeTaskFunc(model)
        
        # 任务消费
        #循环任务（每天/每周/工作日/cron）执行后必须保持可用，
        #一旦被置为不可用，就可能在后续迁移中被踢出活动表，导致任务永久失效。
        if not model.is_featureDay() and not self.is_recurring_model(model):
            obj = ExcelTool()
            obj.write_columnValue_withTaskId_toExcel(model.taskId , 2, "0")  # 修改 B 列为 0（任务不可用）
            # 刷新数据
            self.refreshDataFromExcel()
        
    #添加任务
    def addTask(self, taskModel: TimeTaskModel):
        #幂等保护：任务ID由内容+目标计算得出，重复下发同一条指令会产生同ID重复行，
        #而重复行会在迁移历史任务时造成误删相邻任务。此处复用已有任务。
        try:
            for item in ExcelTool().readExcel():
                model = TimeTaskModel(item, None, False)
                if model.taskId and model.taskId == taskModel.taskId:
                    #已存在但被禁用（如被误判为过期）时，重新启用，避免任务永久失效
                    if not model.enable:
                        ExcelTool().write_columnValue_withTaskId_toExcel(model.taskId, 2, "1")
                    self.convetDataToModelArray(ExcelTool().readExcel())
                    return model.taskId
        except Exception as e:
            print(f"[timeTask] 检查重复任务失败：{e}")

        taskList = ExcelTool().addItemToExcel(taskModel.get_formatItem())
        self.convetDataToModelArray(taskList)
        return taskModel.taskId   
    
    #model数组转换
    def convetDataToModelArray(self, dataArray):
        tempArray = []
        for item in dataArray:
            model = TimeTaskModel(item, None, False, True)
            tempArray.append(model)
        #赋值
        self.timeTasks = tempArray
        
    #是否目标时间      
    def is_targetTime(self, timeStr):
        tempTimeStr = timeStr
        #对比精准到分（忽略秒）
        current_time = arrow.now().format('HH:mm')
        
        #如果是分钟
        if tempTimeStr.count(":") == 1:
           tempTimeStr = tempTimeStr + ":00"
        
        #转为分钟时间
        task_time = arrow.get(tempTimeStr, "HH:mm:ss").format("HH:mm")
        tempValue = current_time == task_time
        return tempValue 
