import base64
import uuid
import re
from bridge.context import ContextType
from channel.chat_message import ChatMessage
from common.log import logger
from common.tmp_dir import TmpDir
from config import conf
from lib.gewechat import GewechatClient
import requests
import xml.etree.ElementTree as ET

# 私聊信息示例
"""
{
    "TypeName": "AddMsg",
    "Appid": "wx_xxx",
    "Data": {
        "MsgId": 177581074,
        "FromUserName": {
            "string": "wxid_fromuser"
        },
        "ToUserName": {
            "string": "wxid_touser"
        },
        "MsgType": 49,
        "Content": {
            "string": ""
        },
        "Status": 3,
        "ImgStatus": 1,
        "ImgBuf": {
            "iLen": 0
        },
        "CreateTime": 1733410112,
        "MsgSource": "<msgsource>xx</msgsource>\n",
        "PushContent": "xxx",
        "NewMsgId": 5894648508580188926,
        "MsgSeq": 773900156
    },
    "Wxid": "wxid_gewechat_bot"  // 使用gewechat登录的机器人wxid
}
"""

# 群聊信息示例
"""
{
    "TypeName": "AddMsg",
    "Appid": "wx_xxx",
    "Data": {
        "MsgId": 585326344,
        "FromUserName": {
            "string": "xxx@chatroom"
        },
        "ToUserName": {
            "string": "wxid_gewechat_bot" // 接收到此消息的wxid, 即使用gewechat登录的机器人wxid
        },
        "MsgType": 1,
        "Content": {
            "string": "wxid_xxx:\n@name msg_content" // 发送消息人的wxid和消息内容(包含@name)
        },
        "Status": 3,
        "ImgStatus": 1,
        "ImgBuf": {
            "iLen": 0
        },
        "CreateTime": 1733447040,
        "MsgSource": "<msgsource>\n\t<atuserlist><![CDATA[,wxid_wvp31dkffyml19]]></atuserlist>\n\t<pua>1</pua>\n\t<silence>0</silence>\n\t<membercount>3</membercount>\n\t<signature>V1_cqxXBat9|v1_cqxXBat9</signature>\n\t<tmp_node>\n\t\t<publisher-id></publisher-id>\n\t</tmp_node>\n</msgsource>\n",
        "PushContent": "xxx在群聊中@了你",
        "NewMsgId": 8449132831264840264,
        "MsgSeq": 773900177
    },
    "Wxid": "wxid_gewechat_bot"  // 使用gewechat登录的机器人wxid
}
"""

# 群邀请消息示例
"""
{
    "TypeName": "AddMsg",
    "Appid": "wx_xxx",
    "Data": {
        "MsgId": 488566999,
        "FromUserName": {
            "string": "xxx@chatroom"
        },
        "ToUserName": {
            "string": "wxid_gewechat_bot"
        },
        "MsgType": 10002,
        "Content": {
            "string": "53760920521@chatroom:\n<sysmsg type=\"sysmsgtemplate\">\n\t<sysmsgtemplate>\n\t\t<content_template type=\"tmpl_type_profile\">\n\t\t\t<plain><![CDATA[]]></plain>\n\t\t\t<template><![CDATA[\"$username$\"邀请\"$names$\"加入了群聊]]></template>\n\t\t\t<link_list>\n\t\t\t\t<link name=\"username\" type=\"link_profile\">\n\t\t\t\t\t<memberlist>\n\t\t\t\t\t\t<member>\n\t\t\t\t\t\t\t<username><![CDATA[wxid_eaclcf34ny6221]]></username>\n\t\t\t\t\t\t\t<nickname><![CDATA[刘贺]]></nickname>\n\t\t\t\t\t\t</member>\n\t\t\t\t\t</memberlist>\n\t\t\t\t</link>\n\t\t\t\t<link name=\"names\" type=\"link_profile\">\n\t\t\t\t\t<memberlist>\n\t\t\t\t\t\t<member>\n\t\t\t\t\t\t\t<username><![CDATA[wxid_mmwc3zzkfcl922]]></username>\n\t\t\t\t\t\t\t<nickname><![CDATA[郑德娟]]></nickname>\n\t\t\t\t\t\t</member>\n\t\t\t\t\t</memberlist>\n\t\t\t\t\t<separator><![CDATA[、]]></separator>\n\t\t\t\t</link>\n\t\t\t</link_list>\n\t\t</content_template>\n\t</sysmsgtemplate>\n</sysmsg>\n"
        },
        "Status": 4,
        "ImgStatus": 1,
        "ImgBuf": {
            "iLen": 0
        },
        "CreateTime": 1736820013,
        "MsgSource": "<msgsource>\n\t<tmp_node>\n\t\t<publisher-id></publisher-id>\n\t</tmp_node>\n</msgsource>\n",
        "NewMsgId": 5407479395895269893,
        "MsgSeq": 821038175
    },
    "Wxid": "wxid_gewechat_bot"
}
"""

"""
{
    "TypeName": "ModContacts",
    "Appid": "wx_xxx",
    "Data": {
        "UserName": {
            "string": "xxx@chatroom"
        },
        "NickName": {
            "string": "测试2"
        },
        "PyInitial": {
            "string": "CS2"
        },
        "QuanPin": {
            "string": "ceshi2"
        },
        "Sex": 0,
        "ImgBuf": {
            "iLen": 0
        },
        "BitMask": 4294967295,
        "BitVal": 2,
        "ImgFlag": 1,
        "Remark": {},
        "RemarkPyinitial": {},
        "RemarkQuanPin": {},
        "ContactType": 0,
        "RoomInfoCount": 0,
        "DomainList": [
            {}
        ],
        "ChatRoomNotify": 1,
        "AddContactScene": 0,
        "PersonalCard": 0,
        "HasWeiXinHdHeadImg": 0,
        "VerifyFlag": 0,
        "Level": 0,
        "Source": 0,
        "ChatRoomOwner": "wxid_xxx",
        "WeiboFlag": 0,
        "AlbumStyle": 0,
        "AlbumFlag": 0,
        "SnsUserInfo": {
            "SnsFlag": 0,
            "SnsBgobjectId": 0,
            "SnsFlagEx": 0
        },
        "CustomizedInfo": {
            "BrandFlag": 0
        },
        "AdditionalContactList": {
            "LinkedinContactItem": {}
        },
        "ChatroomMaxCount": 10008,
        "DeleteFlag": 0,
        "Description": "\b\u0004\u0012\u001c\n\u0013wxid_xxx0\u0001@\u0000\u0001\u0000\u0012\u001c\n\u0013wxid_xxx0\u0001@\u0000\u0001\u0000\u0012\u001c\n\u0013wxid_xxx0\u0001@\u0000\u0001\u0000\u0012\u001c\n\u0013wxid_xxx0\u0001@\u0000\u0001\u0000\u0018\u0001\"\u0000(\u00008\u0000",
        "ChatroomStatus": 5,
        "Extflag": 0,
        "ChatRoomBusinessType": 0
    },
    "Wxid": "wxid_xxx"
}
"""

# 群聊中移除用户示例
"""
{
    "UserName": {
        "string": "xxx@chatroom"
    },
    "NickName": {
        "string": "AITestGroup"
    },
    "PyInitial": {
        "string": "AITESTGROUP"
    },
    "QuanPin": {
        "string": "AITestGroup"
    },
    "Sex": 0,
    "ImgBuf": {
        "iLen": 0
    },
    "BitMask": 4294967295,
    "BitVal": 2,
    "ImgFlag": 1,
    "Remark": {},
    "RemarkPyinitial": {},
    "RemarkQuanPin": {},
    "ContactType": 0,
    "RoomInfoCount": 0,
    "DomainList": [
        {}
    ],
    "ChatRoomNotify": 1,
    "AddContactScene": 0,
    "PersonalCard": 0,
    "HasWeiXinHdHeadImg": 0,
    "VerifyFlag": 0,
    "Level": 0,
    "Source": 0,
    "ChatRoomOwner": "wxid_xxx",
    "WeiboFlag": 0,
    "AlbumStyle": 0,
    "AlbumFlag": 0,
    "SnsUserInfo": {
        "SnsFlag": 0,
        "SnsBgobjectId": 0,
        "SnsFlagEx": 0
    },
    "CustomizedInfo": {
        "BrandFlag": 0
    },
    "AdditionalContactList": {
        "LinkedinContactItem": {}
    },
    "ChatroomMaxCount": 10037,
    "DeleteFlag": 0,
    "Description": "\b\u0002\u0012\u001c\n\u0013wxid_eacxxxx\u0001@\u0000�\u0001\u0000\u0012\u001c\n\u0013wxid_xxx\u0001@\u0000�\u0001\u0000\u0018\u0001\"\u0000(\u00008\u0000",
    "ChatroomStatus": 4,
    "Extflag": 0,
    "ChatRoomBusinessType": 0
}
"""

# 群聊中移除用户示例
"""
{
    "TypeName": "ModContacts",
    "Appid": "wx_xxx",
    "Data": {
        "UserName": {
            "string": "xxx@chatroom"
        },
        "NickName": {
            "string": "测试2"
        },
        "PyInitial": {
            "string": "CS2"
        },
        "QuanPin": {
            "string": "ceshi2"
        },
        "Sex": 0,
        "ImgBuf": {
            "iLen": 0
        },
        "BitMask": 4294967295,
        "BitVal": 2,
        "ImgFlag": 2,
        "Remark": {},
        "RemarkPyinitial": {},
        "RemarkQuanPin": {},
        "ContactType": 0,
        "RoomInfoCount": 0,
        "DomainList": [
            {}
        ],
        "ChatRoomNotify": 1,
        "AddContactScene": 0,
        "PersonalCard": 0,
        "HasWeiXinHdHeadImg": 0,
        "VerifyFlag": 0,
        "Level": 0,
        "Source": 0,
        "ChatRoomOwner": "wxid_xxx",
        "WeiboFlag": 0,
        "AlbumStyle": 0,
        "AlbumFlag": 0,
        "SnsUserInfo": {
            "SnsFlag": 0,
            "SnsBgobjectId": 0,
            "SnsFlagEx": 0
        },
        "SmallHeadImgUrl": "https://wx.qlogo.cn/mmcrhead/xxx/0",
        "CustomizedInfo": {
            "BrandFlag": 0
        },
        "AdditionalContactList": {
            "LinkedinContactItem": {}
        },
        "ChatroomMaxCount": 10007,
        "DeleteFlag": 0,
        "Description": "\b\u0003\u0012\u001c\n\u0013wxid_xxx0\u0001@\u0000\u0001\u0000\u0012\u001c\n\u0013wxid_xxx0\u0001@\u0000\u0001\u0000\u0012\u001c\n\u0013wxid_xxx0\u0001@\u0000\u0001\u0000\u0018\u0001\"\u0000(\u00008\u0000",
        "ChatroomStatus": 5,
        "Extflag": 0,
        "ChatRoomBusinessType": 0
    },
    "Wxid": "wxid_xxx"
}
"""

class GeWeChatMessage(ChatMessage):
    def __init__(self, msg, client: GewechatClient):
        super().__init__(msg)
        self.msg = msg
        self.client = client  # 将 client 的初始化移到最前面
        self.content = ''  # 初始化self.content为空字符串
        self.raw_content = ''  # 初始化raw_content为空字符串
        self.is_at = False  # 初始化is_at为False
        self.to_user_nickname = ''  # 初始化机器人的昵称
        self.app_id = conf().get("gewechat_app_id")  # 初始化 app_id

        # 添加 self.msg_data 属性，兼容 Data 和 data 字段
        self.msg_data = {}
        if 'Data' in msg:
            self.msg_data = msg['Data']
        elif 'data' in msg:
            self.msg_data = msg['data']
        else:
            logger.warning(f"[gewechat] Missing both 'Data' and 'data' in message")
            return
            
        # 获取机器人的昵称
        bot_wxid = self.msg.get('Wxid')
        if bot_wxid:
            brief_info_response = self.client.get_brief_info(self.app_id, [bot_wxid])
            if brief_info_response.get('ret') == 200 and brief_info_response.get('data'):
                brief_info = brief_info_response['data'][0]
                self.to_user_nickname = brief_info.get('nickName', bot_wxid)
                logger.debug(f"[gewechat] Bot nickname: {self.to_user_nickname}")
            
        self.create_time = self.msg_data.get('CreateTime', 0)
        if not self.msg_data:
            logger.warning(f"[gewechat] No message data available")
            return
        if 'NewMsgId' not in self.msg_data :
            logger.warning(f"[gewechat] Missing 'NewMsgId' in message data")
            logger.debug(f"[gewechat] msg_data: {self.msg_data}")
            return
        self.msg_id = self.msg_data['NewMsgId']
        self.is_group = True if "@chatroom" in self.msg_data['FromUserName']['string'] else False
        logger.info(f"[gewechat] is_group determination: FromUserName={self.msg_data['FromUserName']['string']}, is_group={self.is_group}")

        notes_join_group = ["加入群聊", "加入了群聊", "invited", "joined", "移出了群聊"]
        notes_bot_join_group = ["邀请你", "invited you", "You've joined", "你通过扫描"]

        self.from_user_id = self.msg_data['FromUserName']['string']
        self.to_user_id = self.msg_data['ToUserName']['string']
        self.other_user_id = self.from_user_id

        # 检查是否是公众号等非用户账号的消息
        if self._is_non_user_message(self.msg_data.get('MsgSource', ''), self.from_user_id):
            self.ctype = ContextType.NON_USER_MSG
            self.content = self.msg_data.get('Content', {}).get('string', '')
            logger.debug(f"[gewechat] detected non-user message from {self.from_user_id}: {self.content}")
            return

        logger.info(f"[gewechat] Processing message with MsgType: {self.msg_data['MsgType']}, msg_id: {self.msg_id}")
        
        if self.msg_data['MsgType'] == 1:  # Text message
            self.ctype = ContextType.TEXT
            # 保存原始消息内容
            self.raw_content = self.msg_data.get('Content', {}).get('string', '')
            self.content = self.raw_content
            
            # 检查是否是群聊消息
            if self.is_group:
                # 解析MsgSource中的atuserlist
                msg_source = self.msg_data.get('MsgSource', '')
                try:
                    root = ET.fromstring(msg_source)
                    atuserlist = root.find('.//atuserlist')
                    if atuserlist is not None and atuserlist.text:
                        # 检查是否@了机器人
                        bot_wxid = self.msg.get('Wxid')
                        self.is_at = bot_wxid in atuserlist.text
                        logger.info(f"[gewechat] atuserlist check: atuserlist='{atuserlist.text}', bot_wxid='{bot_wxid}', is_at={self.is_at}")
                except ET.ParseError as e:
                    logger.error(f"[gewechat] Failed to parse MsgSource XML: {e}")
                except Exception as e:
                    logger.error(f"[gewechat] Error checking @ status: {e}")
                
                # 从消息中提取实际内容
                if ':' in self.content:
                    self.content = self.content.split(':', 1)[1].strip()
                    
                # 如果通过 atuserlist 没有检测到 @，尝试通过消息内容检测
                if not self.is_at and self.to_user_nickname:
                    # 检查消息中是否包含 @机器人昵称
                    at_pattern = f"@{self.to_user_nickname}"
                    self.is_at = at_pattern in self.content
                    logger.info(f"[gewechat] content @ check: pattern='{at_pattern}', content='{self.content}', is_at={self.is_at}")
                    
                # 记录调试信息
                logger.info(f"[gewechat] Group message - raw_content: {self.raw_content}")
                logger.info(f"[gewechat] Group message - content: {self.content}")
                logger.info(f"[gewechat] Group message - is_at: {self.is_at}")
                logger.info(f"[gewechat] Group message - bot_nickname: {self.to_user_nickname}")
        elif self.msg_data['MsgType'] == 34:  # Voice message
            self.ctype = ContextType.VOICE
            self.content = self.msg_data.get('Content', {}).get('string', '')
            if 'ImgBuf' in self.msg_data and 'buffer' in self.msg_data['ImgBuf'] and self.msg_data['ImgBuf']['buffer']:
                silk_data = base64.b64decode(self.msg_data['ImgBuf']['buffer'])
                silk_file_name = f"voice_{uuid.uuid4()}.silk"
                silk_file_path = TmpDir().path() + silk_file_name
                with open(silk_file_path, "wb") as f:
                    f.write(silk_data)
                self.content = silk_file_path
        elif self.msg_data['MsgType'] == 3:  # Image message
            self.ctype = ContextType.IMAGE
            self.content = TmpDir().path() + str(self.msg_id) + ".png"
            self._prepare_fn = self.download_image
        elif self.msg_data['MsgType'] == 49:  # 引用消息，小程序，公众号等
            logger.info(f"[gewechat] Processing MsgType 49 message, msg_id: {self.msg_id}")
            # 保存原始消息内容
            self.raw_content = self.msg_data.get('Content', {}).get('string', '')
            # After getting content_xml
            content_xml = self.msg_data['Content']['string']
            logger.debug(f"[gewechat] Raw content_xml: {content_xml[:500]}...")  # 只显示前500字符避免日志过长
            
            # Find the position of '<?xml' declaration and remove any prefix
            xml_start = content_xml.find('<?xml version=')
            if xml_start != -1:
                content_xml = content_xml[xml_start:]
                logger.debug(f"[gewechat] Cleaned content_xml: {content_xml[:500]}...")
            
            try:
                root = ET.fromstring(content_xml)
                appmsg = root.find('appmsg')
                if appmsg is not None:
                    msg_type_node = appmsg.find('type')
                    msg_type_value = msg_type_node.text if msg_type_node is not None else 'None'
                    logger.info(f"[gewechat] Found appmsg with type: {msg_type_value}")
                    
                    if msg_type_node is not None and msg_type_node.text == '57':
                        logger.info(f"[gewechat] Detected quote message (type=57)")
                        self.ctype = ContextType.TEXT
                        refermsg = appmsg.find('refermsg')
                        if refermsg is not None:
                            displayname = refermsg.find('displayname').text if refermsg.find('displayname') is not None else ''
                            quoted_content = refermsg.find('content').text if refermsg.find('content') is not None else ''
                            title = appmsg.find('title').text if appmsg.find('title') is not None else ''
                            # 优化引用消息格式：先显示用户的新消息，再显示引用内容
                            self.content = f"{title}\n\n[引用了 {displayname}: {quoted_content}]"
                            logger.info(f"[gewechat] Quote message parsed - displayname: {displayname}, quoted: {quoted_content}, title: {title}")
                            
                            # 为引用消息设置发送者信息和@状态
                            if self.is_group:
                                # 从消息内容中提取发送者ID
                                content_string = self.msg_data.get('Content', {}).get('string', '')
                                logger.info(f"[gewechat] Group quote message - content_string: {content_string[:100]}")
                                if ':' in content_string:
                                    self.actual_user_id = content_string.split(':', 1)[0]
                                    logger.info(f"[gewechat] Set actual_user_id for group quote message: {self.actual_user_id}")
                                else:
                                    logger.warning(f"[gewechat] No ':' found in group quote message content")
                                
                                # 检查引用消息是否@机器人 - 检查title和quoted内容
                                if self.to_user_nickname and (self.to_user_nickname in title or self.to_user_nickname in quoted_content):
                                    self.is_at = True
                                    logger.info(f"[gewechat] Quote message contains bot nickname '{self.to_user_nickname}', set is_at=True")
                                else:
                                    logger.info(f"[gewechat] Quote message does not contain bot nickname '{self.to_user_nickname}', is_at=False")
                            else:
                                logger.info(f"[gewechat] Private quote message - using from_user_id: {self.from_user_id}")
                                self.actual_user_id = self.from_user_id
                        else:
                            self.content = content_xml
                            logger.warning(f"[gewechat] Quote message has no refermsg element")
                    elif msg_type_node is not None and msg_type_node.text == '5':
                        title = appmsg.find('title').text if appmsg.find('title') is not None else "无标题"
                        if "加入群聊" in title:
                            self.ctype = ContextType.TEXT
                            self.content = content_xml
                        else:
                            url = appmsg.find('url').text if appmsg.find('url') is not None else ""
                            self.ctype = ContextType.SHARING
                            self.content = url
                    else:
                        logger.info(f"[gewechat] MsgType 49 with unsupported app type: {msg_type_value}")
                        self.ctype = ContextType.TEXT
                        self.content = content_xml
                else:
                    logger.warning(f"[gewechat] MsgType 49 has no appmsg element")
                    self.ctype = ContextType.TEXT
                    self.content = content_xml
            except ET.ParseError as e:
                logger.error(f"[gewechat] Failed to parse XML for MsgType 49: {e}")
                logger.debug(f"[gewechat] Problematic XML: {content_xml}")
                self.ctype = ContextType.TEXT
                self.content = content_xml
            
            # 为分享消息设置发送者信息
            if self.is_group:
                # 从消息内容中提取发送者ID
                content_string = self.msg_data.get('Content', {}).get('string', '')
                if ':' in content_string:
                    self.actual_user_id = content_string.split(':', 1)[0]
                    # 从群成员列表中获取实际发送者信息
                    chatroom_member_list_response = self.client.get_brief_info(self.app_id, [self.actual_user_id])
                    if chatroom_member_list_response.get('ret') == 200 and chatroom_member_list_response.get('data'):
                        brief_info = chatroom_member_list_response['data'][0]
                        self.actual_user_nickname = brief_info.get('nickName', self.actual_user_id)
                    else:
                        self.actual_user_nickname = self.actual_user_id
                else:
                    # 如果无法提取发送者ID，使用from_user_id
                    self.actual_user_id = self.from_user_id
                    self.actual_user_nickname = self.other_user_nickname
        elif self.msg_data['MsgType'] == 51:
            self.ctype = ContextType.STATUS_SYNC
            self.content = self.msg_data.get('Content', {}).get('string', '')
            return
        elif self.msg_data['MsgType'] == 10002 and self.is_group:  # 群系统消息
            content = self.msg_data.get('Content', {}).get('string', '')
            logger.debug(f"[gewechat] detected group system message: {content}")
            
            if any(note in content for note in notes_bot_join_group):
                logger.warn("机器人加入群聊消息，不处理~")
                self.content = content
                return
                
            if any(note in content for note in notes_join_group):
                try:
                    xml_content = content.split(':\n', 1)[1] if ':\n' in content else content
                    root = ET.fromstring(xml_content)
                    
                    sysmsgtemplate = root.find('.//sysmsgtemplate')
                    if sysmsgtemplate is None:
                        raise ET.ParseError("No sysmsgtemplate found")
                        
                    content_template = sysmsgtemplate.find('.//content_template')
                    if content_template is None:
                        raise ET.ParseError("No content_template found")
                        
                    content_type = content_template.get('type')
                    if content_type not in ['tmpl_type_profilewithrevoke', 'tmpl_type_profile']:
                        raise ET.ParseError(f"Invalid content_template type: {content_type}")
                    
                    template = content_template.find('.//template')
                    if template is None:
                        raise ET.ParseError("No template element found")

                    link_list = content_template.find('.//link_list')
                    target_nickname = "未知用户"
                    target_username = None
                    
                    if link_list is not None:
                        # 根据消息模板内容确定要查找的link name
                        template_text = template.text if template is not None else ""
                        if "邀请" in template_text and "加入了群聊" in template_text:
                            # 邀请消息查找names链接
                            link_name = 'names'
                        else:
                            # 默认或移除消息查找kickoutname链接
                            link_name = 'kickoutname'
                        
                        action_link = link_list.find(f".//link[@name='{link_name}']")
                        
                        # 如果找不到指定的链接，尝试查找username链接（邀请者信息）
                        if action_link is None and link_name == 'kickoutname':
                            link_name = 'username'
                            action_link = link_list.find(f".//link[@name='{link_name}']")
                        
                        if action_link is not None:
                            members = action_link.findall('.//member')
                            nicknames = []
                            usernames = []
                            
                            for member in members:
                                nickname_elem = member.find('nickname')
                                username_elem = member.find('username')
                                nicknames.append(nickname_elem.text if nickname_elem is not None and nickname_elem.text else "未知用户")
                                usernames.append(username_elem.text if username_elem is not None else None)
                            
                            # 处理分隔符（主要针对邀请消息）
                            separator_elem = action_link.find('separator')
                            separator = separator_elem.text if separator_elem is not None else '、'
                            target_nickname = separator.join(nicknames) if nicknames else "未知用户"
                            
                            # 取第一个有效username（根据业务需求调整）
                            target_username = next((u for u in usernames if u), None)

                    # 构造最终消息内容
                    if content_type == 'tmpl_type_profilewithrevoke':
                        self.content = f'你邀请"{target_nickname}"加入了群聊'
                        self.ctype = ContextType.JOIN_GROUP
                    elif content_type == 'tmpl_type_profile':
                        # 检查模板内容来区分是邀请还是移除
                        template_text = template.text if template is not None else ""
                        if "邀请" in template_text and "加入了群聊" in template_text:
                            # 邀请用户加入群聊
                            self.content = f'"{target_nickname}"被邀请加入了群聊'
                            self.ctype = ContextType.JOIN_GROUP
                        else:
                            # 移出群聊
                            self.content = f'你将"{target_nickname}"移出了群聊'
                            self.ctype = ContextType.EXIT_GROUP

                    self.actual_user_nickname = target_nickname
                    self.actual_user_id = target_username

                    # 查找邀请人信息
                    inviter_link = link_list.find(".//link[@name='username']")
                    if inviter_link is not None:
                        member = inviter_link.find('.//member')
                        if member is not None:
                            nickname_elem = member.find('nickname')
                            self.invite_nickname = nickname_elem.text if nickname_elem is not None else "未知邀请人"
                    
                    # 确认群名
                    brief_info_response = self.client.get_brief_info(self.app_id, [self.from_user_id])
                    if brief_info_response.get('ret') == 200 and brief_info_response.get('data'):
                        brief_info = brief_info_response['data'][0]
                        self.group_name = brief_info.get('nickName', self.from_user_id)
                    else:
                        self.group_name = self.from_user_id
                    
                    logger.debug(f"[gewechat] parsed group system message: {self.content} "
                                f"type: {content_type} user: {target_nickname} ({target_username})")
                    
                except ET.ParseError as e:
                    logger.error(f"[gewechat] Failed to parse group system message XML: {e}")
                    self.content = content
                except Exception as e:
                    logger.error(f"[gewechat] Unexpected error parsing group system message: {e}")
                    self.content = content
        elif self.msg_data['MsgType'] == 47:
            self.ctype = ContextType.EMOJI
            self.content = self.msg_data.get('Content', {}).get('string', '')
        elif self.msg_data['MsgType'] == 10000 and self.is_group:  # 群系统纯文本消息（如"A"邀请"B"加入了群聊）
            content = self.msg_data.get('Content', {}).get('string', '')
            logger.info(f"[gewechat] detected group system text message(10000): {content}")
            try:
                # 优先从引号中抽取被邀请人昵称
                invited_names = []
                try:
                    invited_names = re.findall(r'"([^\"]+)"加入了群聊', content)
                    if not invited_names:
                        # 匹配 "邀请"B"加入了群聊" 模式
                        m = re.search(r'邀请\"([^\"]+)\"加入了群聊', content)
                        if m:
                            invited_names = [m.group(1)]
                    # 新增：匹配扫码进群的可能格式
                    if not invited_names:
                        # 匹配可能的扫码进群格式："XXX"通过扫描群二维码加入群聊
                        qr_patterns = [
                            r'"([^\"]+)"通过.*二维码.*加入',
                            r'"([^\"]+)"扫.*码.*加入',
                            r'"([^\"]+)".*scan.*join',
                            r'"([^\"]+)".*QR.*join',
                            r'"([^\"]+)"通过.*群.*加入'
                        ]
                        for pattern in qr_patterns:
                            qr_match = re.search(pattern, content, re.IGNORECASE)
                            if qr_match:
                                invited_names = [qr_match.group(1)]
                                logger.info(f"[gewechat] detected QR code join: {content}")
                                break
                except Exception:
                    invited_names = []
                if invited_names:
                    self.actual_user_nickname = '、'.join(invited_names)
                # 判断加入/移出 - 扩展判断条件
                if ("加入了群聊" in content or 
                    "加入群聊" in content or 
                    "二维码" in content or 
                    "扫码" in content or
                    "scan" in content.lower() or
                    "join" in content.lower()):
                    self.ctype = ContextType.JOIN_GROUP
                    logger.info(f"[gewechat] identified as JOIN_GROUP: {content}")
                elif "移出了群聊" in content:
                    self.ctype = ContextType.EXIT_GROUP
                else:
                    # 未识别，记录日志用于调试
                    logger.warning(f"[gewechat] unrecognized group system message: {content}")
                    self.ctype = ContextType.TEXT
                self.content = content
                # 提取邀请人昵称
                inviter_match = re.search(r'\"([^\"]+)\"邀请', content)
                if inviter_match:
                    self.invite_nickname = inviter_match.group(1)
                else:
                    # 扫码进群时没有邀请人，设置为空字符串
                    self.invite_nickname = ""
                
                # 确认群名
                brief_info_response = self.client.get_brief_info(self.app_id, [self.from_user_id])
                if brief_info_response.get('ret') == 200 and brief_info_response.get('data'):
                    brief_info = brief_info_response['data'][0]
                    self.group_name = brief_info.get('nickName', self.from_user_id)
                else:
                    self.group_name = self.from_user_id
            except Exception as e:
                logger.error(f"[gewechat] Unexpected error parsing 10000 system message: {e}")
                self.content = content
                self.ctype = ContextType.TEXT
        else:
            raise NotImplementedError(f"Unsupported message type: Type:{self.msg_data['MsgType']}")

        # 获取群聊或好友的名称
        brief_info_response = self.client.get_brief_info(self.app_id, [self.other_user_id])
        if brief_info_response.get('ret') == 200 and brief_info_response.get('data'):
            brief_info = brief_info_response['data'][0]
            self.other_user_nickname = brief_info.get('nickName', self.other_user_id)

        if self.is_group:
            if self.ctype == ContextType.TEXT:
                # 如果是群聊消息，获取实际发送者信息
                self.actual_user_id = self.msg_data.get('Content', {}).get('string', '').split(':', 1)[0]
                # 从群成员列表中获取实际发送者信息
                chatroom_member_list_response = self.client.get_chatroom_member_list(self.app_id, self.from_user_id)
                if chatroom_member_list_response.get('ret') == 200 and chatroom_member_list_response.get('data', {}).get('memberList'):
                    # 从群成员列表中匹配acual_user_id
                    for member_info in chatroom_member_list_response['data']['memberList']:
                        if member_info['wxid'] == self.actual_user_id:
                             # 先获取displayName，如果displayName为空，再获取nickName
                            self.actual_user_nickname = member_info.get('displayName') or member_info.get('nickName', self.actual_user_id)
                            break
                self.actual_user_nickname = self.actual_user_nickname or self.actual_user_id

                # 确保self.content是字符串后进行替换
                self.content = str(self.content)
                # 保存原始内容到raw_content
                self.raw_content = self.content
                # 移除发送者ID前缀
                self.content = re.sub(f'{self.actual_user_id}:\n', '', self.content)
                # 移除@标记，但保留原始内容
                self.content = re.sub(r'@[^\u2005]+\u2005', '', self.content)
            # 对于群聊中的其他消息类型（如JOIN_GROUP），不覆盖已设置的actual_user_nickname
        else:
            # 如果不是群聊消息，保持结构统一，也要设置actual_user_id和actual_user_nickname
            self.actual_user_id = self.other_user_id
            self.actual_user_nickname = self.other_user_nickname

        self.my_msg = self.msg.get('Wxid') == self.from_user_id
        logger.debug(f"[gewechat] my_msg check: Wxid={self.msg.get('Wxid')}, from_user_id={self.from_user_id}, my_msg={self.my_msg}")

    def download_voice(self):
        try:
            voice_data = self.client.download_voice(self.msg['Wxid'], self.msg_id)
            with open(self.content, "wb") as f:
                f.write(voice_data)
        except Exception as e:
            logger.error(f"[gewechat] Failed to download voice file: {e}")

    def download_image(self):
        try:
            try:
                # 尝试下载高清图片
                content_xml = self.msg_data['Content']['string']
                # Find the position of '<?xml' declaration and remove any prefix
                xml_start = content_xml.find('<?xml version=')
                if xml_start != -1:
                    content_xml = content_xml[xml_start:]
                image_info = self.client.download_image(app_id=self.app_id, xml=content_xml, type=1)
            except Exception as e:
                logger.warning(f"[gewechat] Failed to download high-quality image: {e}")
                # 尝试下载普通图片
                image_info = self.client.download_image(app_id=self.app_id, xml=content_xml, type=2)
            if image_info['ret'] == 200 and image_info['data']:
                file_url = image_info['data']['fileUrl']
                logger.info(f"[gewechat] Download image file from {file_url}")
                download_url = conf().get("gewechat_download_url").rstrip('/')
                full_url = download_url + '/' + file_url
                try:
                    file_data = requests.get(full_url).content
                except Exception as e:
                    logger.error(f"[gewechat] Failed to download image file: {e}")
                    return
                with open(self.content, "wb") as f:
                    f.write(file_data)
            else:
                logger.error(f"[gewechat] Failed to download image file: {image_info}")
        except Exception as e:
            logger.error(f"[gewechat] Failed to download image file: {e}")

    def prepare(self):
        if self._prepare_fn:
            self._prepare_fn()

    def _is_non_user_message(self, msg_source: str, from_user_id: str) -> bool:
        """检查消息是否来自非用户账号（如公众号、腾讯游戏、微信团队等）
        
        Args:
            msg_source: 消息的MsgSource字段内容
            from_user_id: 消息发送者的ID
            
        Returns:
            bool: 如果是非用户消息返回True，否则返回False
            
        Note:
            通过以下方式判断是否为非用户消息：
            1. 检查MsgSource中是否包含特定标签
            2. 检查发送者ID是否为特殊账号或以特定前缀开头
        """
        # 检查发送者ID
        special_accounts = ["Tencent-Games", "weixin"]
        if from_user_id in special_accounts or from_user_id.startswith("gh_"):
            logger.debug(f"[gewechat] non-user message detected by sender id: {from_user_id}")
            return True

        # 检查消息源中的标签
        # 示例:<msgsource>\n\t<tips>3</tips>\n\t<bizmsg>\n\t\t<bizmsgshowtype>0</bizmsgshowtype>\n\t\t<bizmsgfromuser><![CDATA[weixin]]></bizmsgfromuser>\n\t</bizmsg>
        non_user_indicators = [
            "<tips>3</tips>",
            "<bizmsgshowtype>",
            "</bizmsgshowtype>",
            "<bizmsgfromuser>",
            "</bizmsgfromuser>"
        ]
        if any(indicator in msg_source for indicator in non_user_indicators):
            logger.debug(f"[gewechat] non-user message detected by msg_source indicators")
            return True

        return False
