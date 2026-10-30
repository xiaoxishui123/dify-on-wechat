import os
import time
import json
import web
from urllib.parse import urlparse

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_channel import ChatChannel
from channel.gewechat.gewechat_message import GeWeChatMessage
from common.log import logger
from common.singleton import singleton
from common.tmp_dir import TmpDir
from common.markdown_image import render_markdown_image
from common.utils import remove_markdown_symbol
from config import conf, save_config
from lib.gewechat import GewechatClient
from voice.audio_convert import mp3_to_silk
import uuid

MAX_UTF8_LEN = 2048

@singleton
class GeWeChatChannel(ChatChannel):
    NOT_SUPPORT_REPLYTYPE = []

    def __init__(self):
        super().__init__()

        self.base_url = conf().get("gewechat_base_url")
        if not self.base_url:
            logger.error("[gewechat] base_url is not set")
            return
        self.token = conf().get("gewechat_token")
        self.client = GewechatClient(self.base_url, self.token)

        # 如果token为空，尝试获取token
        if not self.token:
            logger.warning("[gewechat] token is not set，trying to get token")
            token_resp = self.client.get_token()
            # {'ret': 200, 'msg': '执行成功', 'data': 'tokenxxx'}
            if token_resp.get("ret") != 200:
                logger.error(f"[gewechat] get token failed: {token_resp}")
                return
            self.token = token_resp.get("data")
            conf().set("gewechat_token", self.token)
            save_config()
            logger.info(f"[gewechat] new token saved: {self.token}")
            self.client = GewechatClient(self.base_url, self.token)

        self.app_id = conf().get("gewechat_app_id")
        if not self.app_id:
            logger.warning("[gewechat] app_id is not set，trying to get new app_id when login")

        self.download_url = conf().get("gewechat_download_url")
        if not self.download_url:
            logger.warning("[gewechat] download_url is not set, unable to download image")

        logger.info(f"[gewechat] init: base_url: {self.base_url}, token: {self.token}, app_id: {self.app_id}, download_url: {self.download_url}")

    def startup(self):
        # 如果app_id为空或登录后获取到新的app_id，保存配置
        app_id, error_msg = self.client.login(self.app_id)
        if error_msg:
            logger.error(f"[gewechat] login failed: {error_msg}")
            return

        # 如果原来的self.app_id为空或登录后获取到新的app_id，保存配置
        if not self.app_id or self.app_id != app_id:
            conf().set("gewechat_app_id", app_id)
            save_config()
            logger.info(f"[gewechat] new app_id saved: {app_id}")
            self.app_id = app_id

        # 获取回调地址，示例地址：http://172.17.0.1:9919/v2/api/callback/collect  
        callback_url = conf().get("gewechat_callback_url")
        if not callback_url:
            logger.error("[gewechat] callback_url is not set, unable to start callback server")
            return

        # 创建新线程设置回调地址
        import threading
        def set_callback():
            # 等待服务器启动（给予适当的启动时间）
            import time
            logger.info("[gewechat] sleep 3 seconds waiting for server to start, then set callback")
            time.sleep(3)

            # 设置回调地址，{ "ret": 200, "msg": "操作成功" }
            callback_resp = self.client.set_callback(self.token, callback_url)
            if callback_resp.get("ret") != 200:
                logger.error(f"[gewechat] set callback failed: {callback_resp}")
                return
            logger.info("[gewechat] callback set successfully")

        callback_thread = threading.Thread(target=set_callback, daemon=True)
        callback_thread.start()

        # 从回调地址中解析出端口与url path，启动回调服务器  
        parsed_url = urlparse(callback_url)
        path = parsed_url.path
        # 如果没有指定端口，使用默认端口80
        port = parsed_url.port or 80
        logger.info(f"[gewechat] start callback server: {callback_url}, using port {port}")
        urls = (path, "channel.gewechat.gewechat_channel.Query")
        app = web.application(urls, globals(), autoreload=False)
        web.httpserver.runsimple(app.wsgifunc(), ("0.0.0.0", port))

    def _need_render_image(self, text: str) -> bool:
        """判断回复是否需要在微信端渲染成图片（如行业日报）"""
        keywords = conf().get("markdown_image_keywords", ["行业日报"]) or []
        if not keywords or not text:
            return False
        return any(keyword in text for keyword in keywords)

    def send(self, reply: Reply, context: Context):
        receiver = context["receiver"]
        gewechat_message = context.get("msg")
        # 用户选择改回纯文本输出，关闭 Markdown 转图片
        # if reply.type == ReplyType.TEXT and self._need_render_image(reply.content):
        #     image = render_markdown_image(reply.content)
        #     if image:
        #         if gewechat_message and gewechat_message.is_group:
        #             # 图片消息无法携带 @，先补发一条 @ 消息
        #             try:
        #                 self.client.post_text(self.app_id, receiver, "", gewechat_message.actual_user_id)
        #             except Exception as e:
        #                 logger.error(f"[gewechat] send at before image failed: {e}")
        #         reply = Reply(ReplyType.IMAGE, image)
        if reply.type in [ReplyType.TEXT, ReplyType.ERROR, ReplyType.INFO]:
            # 个人微信不支持 markdown 渲染，发送前移除 markdown 符号
            reply_text = remove_markdown_symbol(reply.content)
            ats = ""
            if gewechat_message and gewechat_message.is_group:
                ats = gewechat_message.actual_user_id
            self.client.post_text(self.app_id, receiver, reply_text, ats)
            logger.info("[gewechat] Do send text to {}: {}".format(receiver, reply_text))
        elif reply.type == ReplyType.VOICE:
            try:
                content = reply.content
                if content.endswith('.mp3'):
                    # 如果是mp3文件，转换为silk格式
                    silk_path = content + '.silk'
                    duration = mp3_to_silk(content, silk_path)
                    callback_url = conf().get("gewechat_callback_url")
                    silk_url = callback_url + "?file=" + silk_path
                    self.client.post_voice(self.app_id, receiver, silk_url, duration)
                    logger.info(f"[gewechat] Do send voice to {receiver}: {silk_url}, duration: {duration/1000.0} seconds")
                    return
                else:
                    logger.error(f"[gewechat] voice file is not mp3, path: {content}, only support mp3")
            except Exception as e:
                logger.error(f"[gewechat] send voice failed: {e}")
        elif reply.type == ReplyType.IMAGE_URL or reply.type == ReplyType.IMAGE:
            image_storage = reply.content
            if reply.type == ReplyType.IMAGE_URL:
                import requests
                import io
                img_url = reply.content
                logger.debug(f"[gewechat]sendImage, download image start, img_url={img_url}")
                pic_res = requests.get(img_url, stream=True)
                image_storage = io.BytesIO()
                size = 0
                for block in pic_res.iter_content(1024):
                    size += len(block)
                    image_storage.write(block)
                logger.debug(f"[gewechat]sendImage, download image success, size={size}, img_url={img_url}")
                image_storage.seek(0)
                if ".webp" in img_url:
                    try:
                        from common.utils import convert_webp_to_png
                        image_storage = convert_webp_to_png(image_storage)
                    except Exception as e:
                        logger.error(f"[gewechat]sendImage, failed to convert image: {e}")
                        return
            elif reply.type == ReplyType.IMAGE:
                # 如果是本地图片文件路径，需要转换为 BytesIO 对象
                if isinstance(reply.content, str):
                    import io
                    try:
                        with open(reply.content, "rb") as f:
                            image_storage = io.BytesIO(f.read())
                    except Exception as e:
                        logger.error(f"[gewechat]sendImage, failed to read local image file: {e}")
                        return
                else:
                    image_storage = reply.content
            
            # 确保 image_storage 是 BytesIO 对象后再进行后续操作
            if not hasattr(image_storage, 'seek'):
                logger.error(f"[gewechat]sendImage, image_storage is not a seekable object: {type(image_storage)}")
                return
                
            # Save image to tmp directory 
            # Save image to tmp directory
            image_storage.seek(0)
            header = image_storage.read(6)
            image_storage.seek(0)
            img_data = image_storage.read()
            image_storage.seek(0)
            extension = ".gif" if header.startswith((b'GIF87a', b'GIF89a')) else ".png"
            img_file_name = f"img_{str(uuid.uuid4())}{extension}"
            img_file_path = TmpDir().path() + img_file_name
            with open(img_file_path, "wb") as f:
                f.write(img_data)
            # Construct callback URL
            callback_url = conf().get("gewechat_callback_url")
            img_url = callback_url + "?file=" + img_file_path
            if extension == ".gif":
                result = self.client.post_file(self.app_id, receiver, file_url=img_url, file_name=img_file_name)
                logger.info("[gewechat] sendGifAsFile, receiver={}, file_url={}, file_name={}, result={}".format(
                    receiver, img_url, img_file_name, result))
            else:
                result = self.client.post_image(self.app_id, receiver, img_url)
                logger.info("[gewechat] sendImage, receiver={}, url={}, result={}".format(receiver, img_url, result))
            if result.get('ret') == 200:
                newMsgId = result['data'].get('newMsgId')
                new_img_file_path = TmpDir().path() + str(newMsgId) + extension
                os.rename(img_file_path, new_img_file_path)
                logger.info("[gewechat] sendImage rename to {}".format(new_img_file_path))

    def _gen_join_group_context(self, msg: GeWeChatMessage) -> Context:
        logger.debug(f"[gewechat] handle join group message: {msg.content}")
        # 成员入群的原始数据格式
        # 'content': '"xxx"邀请"yyy"加入了群聊',
        # 'msg_type': 10000,
        context = self._compose_context(
            ContextType.JOIN_GROUP, 
            msg.content, 
            isgroup=True, 
            msg=msg,
            # 群名
            group_name=getattr(msg, "group_name", None) or getattr(msg, "other_user_nickname", ""),
            # 邀请人昵称（入群消息解析失败时该属性可能不存在，需兜底）
            invite_nickname=getattr(msg, "invite_nickname", ""),
            # 被邀请人昵称
            actual_user_nickname=getattr(msg, "actual_user_nickname", "")
        )
        return context

class Query:
    def GET(self):
        # 搭建简单的文件服务器，用于向gewechat服务传输语音等文件，但只允许访问tmp目录下的文件
        params = web.input(file="")
        file_path = params.file
        if file_path:
            # 使用os.path.abspath清理路径
            clean_path = os.path.abspath(file_path)
            # 获取tmp目录的绝对路径
            tmp_dir = os.path.abspath("tmp")
            # 检查文件路径是否在tmp目录下
            if not clean_path.startswith(tmp_dir):
                logger.error(f"[gewechat] Forbidden access to file outside tmp directory: file_path={file_path}, clean_path={clean_path}, tmp_dir={tmp_dir}")
                raise web.forbidden()

            if os.path.exists(clean_path):
                with open(clean_path, 'rb') as f:
                    return f.read()
            else:
                logger.error(f"[gewechat] File not found: {clean_path}")
                raise web.notfound()
        return "gewechat callback server is running"

    def POST(self):
        channel = GeWeChatChannel()
        web_data = web.data()
        logger.debug("[gewechat] receive data: {}".format(web_data))
        data = json.loads(web_data)
        
        # gewechat服务发送的回调测试消息
        if isinstance(data, dict) and 'testMsg' in data and 'token' in data:
            logger.debug(f"[gewechat] 收到gewechat服务发送的回调测试消息")
            return "success"

        # 兼容 geweapi 新版扁平回调格式（顶层直接含 eventCode/fromUser/content，无 Data 嵌套）
        if isinstance(data, dict) and 'Data' not in data and 'data' not in data \
                and ('eventCode' in data or 'fromUser' in data):
            logger.info(f"[gewechat] 检测到新版扁平回调格式，进行兼容转换: {data.get('eventCode')}")
            _mt_map = {'TEXT': 1, 'IMAGE': 3, 'VOICE': 34, 'APP': 49, 'LINK': 49, 'VIDEO': 43, 'QUOTE': 49}
            _mt = _mt_map.get(str(data.get('msgType', 'TEXT')).upper(), 0)
            _ct = data.get('createTime')
            if isinstance(_ct, int) and _ct > 10**12:  # 毫秒时间戳转秒
                _ct = _ct // 1000
            # 群系统消息(入群/退群/系统提示)在新版扁平格式下没有 msgType，需按内容识别
            _content = str(data.get('content', ''))
            if _mt in (0, 1):
                _is_sysxml = _content.strip().startswith(('<sysmsg', '<?xml', '<appmsg'))
                _is_join = (('加入了群聊' in _content) or ('加入群聊' in _content) or ('二维码' in _content and '加入' in _content) or ('扫码' in _content and '加入' in _content))
                _is_exit = '移出了群聊' in _content
                if _is_sysxml:
                    _mt = 10002
                elif _is_join and '想邀请' not in _content:
                    _mt = 10000
                elif _is_exit:
                    _mt = 10002
            # 群ID:新版放在 fromGroup 字段,也可能在 toUser/fromUser;
            # 必须从 content 之外取,因为引用消息等 content 是XML,其内部含 @chatroom 会被误判成群ID
            _room = data.get('fromGroup', '')
            if not _room:
                for _k in ('toUser', 'fromUser'):
                    _v = data.get(_k, '')
                    if isinstance(_v, str) and '@chatroom' in _v:
                        _room = _v
                        break
            if not _room:
                for _k, _v in data.items():
                    if _k != 'content' and isinstance(_v, str) and '@chatroom' in _v:
                        _room = _v
                        break
            if _room:
                # 群消息:旧格式约定 FromUserName 为群ID, ToUserName 为机器人自身wxid
                _f, _t = _room, data.get('wxid', '')
                # 群聊文本/引用消息需还原旧格式的 "发送者wxid:\n内容" 前缀,
                # 否则消息解析会把整条消息内容误当作发送者ID(导致回复时@到整句话)
                _body = f"{data.get('fromUser', '')}:\n{data.get('content', '')}" if _mt in (1, 49) else data.get('content', '')
            else:
                _f, _t = data.get('fromUser', ''), data.get('toUser', '')
                _body = data.get('content', '')
            data = {
                "TypeName": data.get("eventCode", "AddMsg"),
                "Appid": data.get("appid", ""),
                "Wxid": data.get("wxid", ""),
                "Data": {
                    "MsgId": data.get("msgId", 0),
                    "NewMsgId": data.get("newMsgId", data.get("msgId", 0)),
                    "FromUserName": {"string": _f},
                    "ToUserName": {"string": _t},
                    "MsgType": _mt,
                    "Content": {"string": _body},
                    "CreateTime": _ct or 0,
                    "Status": 3,
                    "MsgSource": data.get("msgSource", "") or "<msgsource></msgsource>",
                },
            }

        # 消息解析必须整体兜底：任何未捕获异常都会让回调返回 500，
        # 导致 gewechat 平台反复重推同一条消息（曾因 MsgType 43/48/10002 等
        # 不支持类型触发上百次 500）。
        try:
            gewechat_msg = GeWeChatMessage(data, channel.client)
        except Exception as e:
            logger.exception(f"[gewechat] Failed to parse message, ignore it: {e}")
            return "success"

        # ctype 为 None 表示不支持/无需处理的消息类型，直接忽略
        if getattr(gewechat_msg, "ctype", None) is None:
            logger.debug(f"[gewechat] ignore message with None ctype from {getattr(gewechat_msg, 'from_user_id', 'unknown')}")
            return "success"

        # 微信客户端的状态同步消息
        if gewechat_msg.ctype == ContextType.STATUS_SYNC:
            logger.debug(f"[gewechat] ignore status sync message: {gewechat_msg.content}")
            return "success"

        # 成员入群事件
        if gewechat_msg.ctype == ContextType.JOIN_GROUP:
            # 成员入群，构造context
            try:
                context = channel._gen_join_group_context(gewechat_msg)
            except Exception as e:
                logger.exception(f"[gewechat] Failed to generate join group context: {e}")
                return "success"
            if context:
                channel.produce(context)
            return "success"


        # 忽略非用户消息（如公众号、系统通知等）
        if gewechat_msg.ctype == ContextType.NON_USER_MSG:
            logger.debug(f"[gewechat] ignore non-user message from {gewechat_msg.from_user_id}: {gewechat_msg.content}")
            return "success"

        # 判断是否需要忽略语音消息
        if gewechat_msg.ctype == ContextType.VOICE:
            if conf().get("speech_recognition") != True:
                return "success"

        # 忽略来自自己的消息
        logger.info(f"[gewechat] my_msg check: my_msg={gewechat_msg.my_msg}, actual_user_id={gewechat_msg.actual_user_id}, is_group={gewechat_msg.is_group}")
        if gewechat_msg.my_msg:
            logger.info(f"[gewechat] ignore message from myself: actual_user_id={gewechat_msg.actual_user_id}, content={gewechat_msg.content}")
            return "success"

        # 忽略过期的消息
        if gewechat_msg.create_time and int(gewechat_msg.create_time) < int(time.time()) - 60 * 5: # 跳过5分钟前的历史消息
            logger.debug(f"[gewechat] ignore expired message from {gewechat_msg.actual_user_id}: {gewechat_msg.content}")
            return "success"

        logger.info(f"[gewechat] Creating context: ctype={gewechat_msg.ctype}, content={gewechat_msg.content[:50]}..., isgroup={gewechat_msg.is_group}")
        context = channel._compose_context(
            gewechat_msg.ctype,
            gewechat_msg.content,
            isgroup=gewechat_msg.is_group,
            msg=gewechat_msg,
        )
        logger.info(f"[gewechat] Context created: {context is not None}")
        if context:
            logger.info(f"[gewechat] Producing context to channel")
            channel.produce(context)
        else:
            logger.warning(f"[gewechat] Context is None, message will not be processed")
        return "success"


