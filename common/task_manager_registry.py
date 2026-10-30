# encoding:utf-8
"""跨插件重载存活的状态注册表。

`#scanp` 会通过 importlib.reload 重新加载插件包及其所有子模块，模块级变量
（包括类属性）会随之被重置。定时任务插件需要记住"当前有哪些检测线程在跑"，
如果这份记忆存放在插件模块里，重载后就会丢失，旧线程再也找不到、停不掉，
于是每次重载都会多出一个检测线程，多个线程会同时触发同一个任务，造成重复发送。

本模块位于 common 包，不在插件的重载范围内（scan_plugins 只 reload 名字以
`plugins.<插件名>.` 开头的模块），因此可以安全承载这类跨重载的状态。
"""

import threading

_lock = threading.Lock()

#已启动的 TaskManager 实例
_task_managers = []

#本进程内已执行过的任务标记，元素为 (taskId, "YYYY-MM-DD HH:mm")
_executed_keys = set()


def register_task_manager(manager):
    """登记新的 TaskManager 实例，返回此前登记过的旧实例列表（供调用方停掉）。"""
    with _lock:
        old_managers = list(_task_managers)
        _task_managers.append(manager)
        return old_managers


def unregister_task_manager(manager):
    """实例停止后从注册表移除，避免内存泄漏。"""
    with _lock:
        if manager in _task_managers:
            _task_managers.remove(manager)


def claim_task_execution(task_id, minute_key):
    """抢占某个任务在某一分钟的执行权。

    minute_key 形如 "2026-09-16 08:00"。

    返回 True 表示当前线程第一个抢到，可以执行；
    返回 False 表示本分钟已有其他线程执行过同一任务，应当跳过。
    这样即使因插件重载残留了多个检测线程，同一任务在同一分钟内也只会被执行一次。
    """
    with _lock:
        today = minute_key[:10]
        #只保留今天的标记，避免集合无限增长
        stale_keys = [key for key in _executed_keys if not key[1].startswith(today)]
        for key in stale_keys:
            _executed_keys.discard(key)

        key = (task_id, minute_key)
        if key in _executed_keys:
            return False
        _executed_keys.add(key)
        return True
