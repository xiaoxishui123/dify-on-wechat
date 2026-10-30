# encoding:utf-8
"""群名 <-> 群ID(wxid) 本地索引

背景：
    gewechat 的通讯录接口(fetchContactsList)按官方说明**仅返回已保存到通讯录的群聊**，
    因此大量群聊无法通过通讯录按名称检索，导致按群名创建定时任务时提示"未找到群"。

    官方文档给出的完整获取方案为：
        1. 当未收录的群产生新消息时，会触发消息回调
        2. 开发者可在回调中调用获取群详情接口，获取群信息并入库

本模块即实现该"入库"能力：在群消息回调时持久化 (群名 -> 群wxid)，
供后续按群名反查群 wxid。
"""

import json
import os
import threading

from common.log import logger
from config import get_appdata_dir

INDEX_FILE = "group_index.json"

_lock = threading.Lock()


def _index_path():
    return os.path.join(get_appdata_dir(), INDEX_FILE)


def _load():
    """读取索引，返回 {群名: 群wxid}"""
    path = _index_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        logger.warning(f"[group_index] 群名索引格式异常，已忽略: {path}")
    except Exception as e:
        logger.warning(f"[group_index] 读取群名索引失败: {e}")
    return {}


def _save(data):
    """原子写入，避免写入过程中程序退出导致文件损坏"""
    path = _index_path()
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception as e:
        logger.warning(f"[group_index] 保存群名索引失败: {e}")


def record_group(group_name, group_id):
    """记录群名与群ID的映射

    Args:
        group_name: 群名称
        group_id: 群 wxid，形如 xxxx@chatroom

    Returns:
        bool: 是否发生了新增或变更
    """
    if not group_name or not group_id:
        return False
    # 群名获取失败时会被回退成 wxid，这种记录无意义
    if group_name == group_id or group_name.endswith("@chatroom"):
        return False

    with _lock:
        data = _load()
        if data.get(group_name) == group_id:
            return False
        data[group_name] = group_id
        _save(data)
        logger.debug(f"[group_index] 记录群名索引: {group_name} -> {group_id}")
        return True


def lookup_group_id(group_name):
    """按群名精确查找群 wxid

    Returns:
        str or None: 群 wxid
    """
    if not group_name:
        return None
    return _load().get(group_name)


def search_group_id(group_name):
    """按群名模糊查找（精确优先，其次双向包含匹配）

    Returns:
        tuple or None: (匹配到的群名, 群wxid)
    """
    if not group_name:
        return None
    data = _load()
    if not data:
        return None

    if group_name in data:
        return group_name, data[group_name]

    # 双向包含匹配：兼容群名被截断/补全的情况
    candidates = [name for name in data if group_name in name or name in group_name]
    if len(candidates) == 1:
        name = candidates[0]
        return name, data[name]
    if len(candidates) > 1:
        # 多个候选时取最长的（更完整的群名通常更贴近用户输入）
        name = max(candidates, key=len)
        logger.warning(f"[group_index] 群名'{group_name}'模糊匹配到多个群，取最长: {name}")
        return name, data[name]
    return None


def all_groups():
    """返回全部索引 {群名: 群wxid}"""
    return _load()
