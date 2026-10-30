import io
import json
import os
import random
import re
import threading
import time

import plugins
import requests
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from common.tmp_dir import TmpDir
from playwright.sync_api import sync_playwright
from plugins import *

from .prompts import get_prompt


def read_file(path):
    with open(path, mode="r", encoding="utf-8") as f:
        return f.read()


def _block_external_request(route):
    """阻断外网资源请求，避免外部 CDN 卡住页面加载（字体/图标改用系统本地字体）"""
    if route.request.url.startswith(("http://", "https://")):
        route.abort()
    else:
        route.continue_()


def _ensure_closed_svg(svg):
    """补齐被 max_tokens 截断、缺少 </svg> 的 SVG"""
    if "</svg" in svg.lower():
        return svg
    return svg.rstrip().rstrip("`").rstrip() + "</svg>"


def _wrap_svg(svg_content):
    """把模型输出的裸 SVG 包进卡片页面"""
    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>汉语新解</title>
    <style>
        body, html {{
            margin: 0;
            padding: 0;
            height: 100%;
            display: flex;
            justify-content: center;
            align-items: center;
            font-family: 'Noto Sans CJK SC', 'WenQuanYi Micro Hei', sans-serif;
        }}
        .card {{
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            overflow: hidden;
            position: relative;
            display: flex;
            flex-direction: column;
        }}
    </style>
</head>
<body>
    <div class="card">
        {svg_content}
    </div>
</body>
</html>
"""


# 金句断行自适应：模型用 <br> 分好行，但每行字数可能超出容器宽度，
# 导致浏览器把行尾 1~3 个字折到下一行形成“孤字行”。
# 这里在截图前实测行数，多出来的行优先用微调字号解决，
# 字号收到下限仍放不下时，去掉硬换行改用均衡折行，保证观感整洁。
_FIT_QUOTE_LINES_JS = """
() => {
  const MIN_FONT = 13;
  const MAX_SHRINK_STEPS = 6;
  const BLOCK_TAGS = ['DIV', 'P', 'UL', 'OL', 'LI', 'SECTION', 'ARTICLE', 'TABLE',
    'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'BLOCKQUOTE', 'FIGURE', 'HEADER', 'FOOTER',
    'NAV', 'ASIDE', 'MAIN', 'FORM', 'PRE'];
  const adjustments = [];

  function visualLines(el) {
    const range = document.createRange();
    range.selectNodeContents(el);
    const rects = Array.from(range.getClientRects())
      .filter(r => r.width > 0.5 && r.height > 0.5);
    const tops = [];
    rects.forEach(r => {
      if (!tops.some(t => Math.abs(t - r.top) < 2)) tops.push(r.top);
    });
    return tops.length;
  }

  function isLeafTextBlock(el) {
    for (const child of el.children) {
      if (BLOCK_TAGS.indexOf(child.tagName) !== -1) return false;
    }
    return true;
  }

  const root = document.querySelector('.card') || document.body;
  const candidates = [];
  root.querySelectorAll('*').forEach(el => {
    const text = (el.innerText || '').trim();
    if (!text || text.length > 120) return;
    if (!isLeafTextBlock(el)) return;
    candidates.push(el);
  });

  candidates.forEach(el => {
    const brCount = (el.innerHTML.match(/<br\\s*\\/?>/gi) || []).length;
    const expected = brCount + 1;
    let lines = visualLines(el);
    if (lines <= expected) return;

    const base = parseFloat(window.getComputedStyle(el).fontSize) || 18;
    let size = base;
    for (let i = 0; i < MAX_SHRINK_STEPS && lines > expected && size - 1 >= MIN_FONT; i++) {
      size -= 1;
      el.style.fontSize = size + 'px';
      lines = visualLines(el);
    }

    let strategy = 'shrink';
    if (lines > expected) {
      el.innerHTML = el.innerHTML.replace(/<br\\s*\\/?>/gi, '');
      el.style.textWrap = 'balance';
      strategy = 'unwrap-balance';
      lines = visualLines(el);
    }

    adjustments.push({
      text: (el.innerText || '').trim().slice(0, 20),
      base: base,
      size: size,
      expected: expected,
      actual: lines,
      strategy: strategy
    });
  });

  return adjustments;
}
"""


def _extract_card_html(text):
    """从模型输出中提取可渲染的卡片页面。

    模型可能返回代码围栏包裹的 HTML/SVG（语言标记有时是 html、svg，
    有时为空），也可能直接输出裸标签，这里逐种情况兜底。
    """
    if not text:
        return ""

    # 1) 代码围栏包裹：优先整页 HTML，其次 SVG
    fences = [m.group(1).strip() for m in re.finditer(r"```[a-zA-Z]*\s*(.*?)```", text, re.DOTALL)]
    for block in fences:
        if "<html" in block.lower():
            return block
    for block in fences:
        if "<svg" in block.lower():
            return _wrap_svg(_ensure_closed_svg(block))

    # 2) 无围栏的裸输出
    html_match = re.search(r"<html.*?</html>", text, re.DOTALL | re.IGNORECASE)
    if html_match:
        return html_match.group(0).strip()

    svg_match = re.search(r"<svg.*?</svg>", text, re.DOTALL | re.IGNORECASE)
    if svg_match:
        return _wrap_svg(svg_match.group(0).strip())

    # 3) SVG 被截断（有开头无结尾）
    svg_open = re.search(r"<svg.*", text, re.DOTALL | re.IGNORECASE)
    if svg_open:
        return _wrap_svg(_ensure_closed_svg(svg_open.group(0).strip()))

    return ""


@plugins.register(
    name="chinesepua",
    desc="A plugin that generates satirical explanation cards for Chinese phrases",
    version="0.6",
    author="BenedictKing",
    desire_priority=90,
)
class ChinesePua(Plugin):
    def __init__(self):
        super().__init__()

        gconf = super().load_config()
        if not gconf:
            curdir = os.path.dirname(__file__)
            json_path = os.path.join(curdir, "config.json")
            tm_path = os.path.join(curdir, "config.json.template")
            if os.path.exists(json_path):
                gconf = json.loads(read_file(json_path))
                logger.debug("[chinesepua] 从 config.json 读取配置")
            elif os.path.exists(tm_path):
                gconf = json.loads(read_file(tm_path))
                logger.debug("[chinesepua] 从 config.json.template 读取配置")
        gconf = gconf or {}

        try:
            self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
            # 与 JinaSum 等插件保持一致：优先读取 plugins/config.json 中的 open_ai_* 配置
            self.api_key = gconf.get("open_ai_api_key") or gconf.get("api_key") or ""
            self.api_base = (
                gconf.get("open_ai_api_base") or gconf.get("api_base") or ""
            ).strip()
            self.api_model = (
                gconf.get("open_ai_model") or gconf.get("api_model") or "gpt-4o-mini"
            )
            self.max_tokens = gconf.get("max_tokens", 0)
            self.with_text = gconf.get("with_text", False)
            logger.debug(
                f"[chinesepua] inited, api_base={self.api_base}, api_model={self.api_model}, "
                f"api_key={'已设置' if self.api_key else '未设置'}"
            )
        except Exception as e:
            logger.error(f"[chinesepua] init error: {e}")

    def _chat_completions_url(self):
        """与 JinaSum 一致：api_base 直接拼接 /chat/completions，不做 /v1 推断"""
        base = (self.api_base or "https://api.openai.com/v1").rstrip("/")
        return base + "/chat/completions"

    def on_handle_context(self, e_context: EventContext):
        context = e_context["context"]
        if context.type != ContextType.TEXT:
            return

        logger.debug(f"[chinesepua] 获取到用户输入：{context.content}")

        keyword = None
        prompt = None

        # (触发词, 提示词名)，触发词按“长词优先”排列，避免前缀互相吞并
        triggers = (
            (("设计", "名片"), "card_designer"),
            (("解字", "字典", "字源"), "word_explainer"),
            (("PUA", "pua", "吐槽", "槽点", "解释", "新解"), "chinese_teacher"),
            (("翻译",), "translate_expert"),
            (("论证", "分析"), "argument_analyser"),
            (("撕考者", "思考者", "思考", "撕考"), "thinker"),
            (("深度思考者", "深度思考", "沉思", "琢磨"), "deep_thinker"),
            (("概念解释", "概念"), "concept_explainer"),
            (("哲学家", "哲学"), "philosopher"),
            (("互联网", "web2"), "web2_expert"),
            (("知识卡", "知识"), "knowledge_card"),
            (("单词卡", "单词"), "word_card"),
        )

        for prefixes, prompt_name in triggers:
            if not context.content.startswith(prefixes):
                continue
            pattern = "(" + "|".join(re.escape(p) for p in prefixes) + r")(.+)"
            match = re.search(pattern, context.content)
            if not match:
                continue
            keyword = match.group(2).strip()
            prompt = get_prompt(prompt_name)
            logger.debug(f"[chinesepua] {prompt_name}: {keyword}")
            break

        if not keyword or not prompt:
            return

        if len(keyword) > 10:
            _set_reply_text("输入太长了，简短一些吧", e_context, level=ReplyType.TEXT)
            return

        try:
            payload = {
                "model": self.api_model,
                "messages": [
                    {"role": "system", "content": prompt.content},
                    {"role": "user", "content": keyword},
                ],
            }
            if self.max_tokens and self.max_tokens > 0:
                payload["max_tokens"] = self.max_tokens

            response = requests.post(
                self._chat_completions_url(),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=payload,
                timeout=120,
            )
            response.raise_for_status()
            data = response.json()
            finish_reason = data["choices"][0].get("finish_reason")
            text = data["choices"][0]["message"].get("content") or ""
            logger.debug(f"[chinesepua] 回复: {text}")

            html_content = _extract_card_html(text)
            if not html_content:
                logger.error(
                    f"[chinesepua] 未解析到卡片内容: finish_reason={finish_reason}, "
                    f"输出长度={len(text)}, 原文开头={text[:300]!r}"
                )

            if self.with_text:
                reply_text = re.split("```", text)[-1].strip()
                if not reply_text:
                    reply_text = re.split("```", text)[0].strip()
                if not reply_text:
                    reply_text = re.split("</svg>", text)[-1].strip()
                if not reply_text:
                    reply_text = re.split("<svg", text)[0].strip()
                if not reply_text:
                    reply_text = "生成失败，请检查模型输出结果"
            else:
                reply_text = "卡片生成中..."

            if html_content:
                thread = threading.Thread(
                    target=self.render_html_to_image,
                    args=(html_content, e_context),
                )
                thread.start()
                logger.debug("[chinesepua] 卡片正在生成中...")
                if self.with_text:
                    reply_text += "\n\n卡片正在生成中..."
            elif not self.with_text:
                _set_reply_text(
                    "生成失败，请检查模型输出结果", e_context, level=ReplyType.TEXT
                )
                return

            _set_reply_text(reply_text, e_context, level=ReplyType.TEXT)

        except Exception as e:
            logger.error(f"[chinesepua] 错误: {e}")
            _set_reply_text(
                "解释失败，请稍后再试...", e_context, level=ReplyType.TEXT
            )

    def render_html_to_image(self, html_content, e_context):
        try:
            tmp_path = (
                TmpDir().path()
                + f"chinesepua_{int(time.time())}_{random.randint(1000, 9999)}.png"
            )

            with sync_playwright() as p:
                browser = p.chromium.launch(
                    args=["--no-sandbox", "--disable-dev-shm-usage"]
                )
                page = browser.new_page(
                    viewport={"width": 1080, "height": 2560},
                    device_scale_factor=2,
                )
                # 模型输出的 HTML 常引用外部 CDN（字体/图标/图片），
                # 这些资源一旦加载卡住，等待默认的 "load" 事件会直接超时报错，
                # 因此这里拦截所有外网请求，只依赖系统本地字体渲染。
                page.route("**/*", _block_external_request)
                page.set_content(html_content, wait_until="domcontentloaded")

                # 等待字体就绪，保证截图时中文已按最终字体渲染
                try:
                    page.evaluate("document.fonts.ready")
                except Exception:
                    pass

                # 修正金句折行：模型分好的行若超出容器宽度会被折成孤字行
                try:
                    adjustments = page.evaluate(_FIT_QUOTE_LINES_JS)
                    if adjustments:
                        logger.info(f"[chinesepua] 金句断行自适应: {adjustments}")
                except Exception as e:
                    logger.warning(f"[chinesepua] 金句断行自适应跳过: {e}")

                # 等待卡片元素渲染完成，失败则退化为整页截图
                try:
                    card_element = page.wait_for_selector(".card", timeout=5000)
                except Exception:
                    card_element = None

                if card_element:
                    card_element.screenshot(path=tmp_path)
                else:
                    page.screenshot(path=tmp_path)

                browser.close()

            with open(tmp_path, "rb") as image_file:
                img_byte_arr = io.BytesIO(image_file.read())

            _send_img(e_context, img_byte_arr)

        except Exception as e:
            logger.error(f"[chinesepua] HTML渲染为图片失败: {e}")
            _send_reply_text(
                "生成卡片失败，请稍后再试。。。", e_context, level=ReplyType.TEXT
            )

    def get_help_text(self, **kwargs):
        return "生成汉语新解卡片，使用方法，输入：解释 词语 / 吐槽 词语 / 解字 汉字"


def _set_reply_text(
    content: str, e_context: EventContext, level: ReplyType = ReplyType.ERROR
):
    reply = Reply(level, content)
    e_context["reply"] = reply
    e_context.action = EventAction.BREAK_PASS


def _send_reply_text(
    content: str, e_context: EventContext, level: ReplyType = ReplyType.ERROR
):
    reply = Reply(level, content)
    channel = e_context["channel"]
    channel.send(reply, e_context["context"])


def _send_img(e_context: EventContext, content: any):
    reply = Reply(ReplyType.IMAGE, content)
    channel = e_context["channel"]
    channel.send(reply, e_context["context"])
