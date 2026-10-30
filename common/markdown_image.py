# encoding:utf-8
"""
将 Markdown 文本渲染成图片。

个人微信等渠道只支持纯文本消息，无法渲染 Markdown。
对于日报这类排版较复杂的内容，可在发送前渲染为图片，
使其在微信中的展示效果尽量接近 Dify 预览。

依赖：pymupdf（内置中文字体，无需系统字体包）、markdown
"""
import io
import re

from common.log import logger

try:
    import markdown
    import pymupdf
except ImportError:  # 未安装依赖时降级为不渲染
    markdown = None
    pymupdf = None

# 渲染样式：尽量贴近 Dify 预览的阅读体验
CSS = """
body {
    font-family: "china-s";
    font-size: 15px;
    line-height: 1.75;
    color: #1f2328;
    background: #ffffff;
}
h1, h2, h3, h4 { color: #0b3d91; margin: 14px 0 6px 0; }
h1 { font-size: 22px; }
h2 { font-size: 19px; }
h3 { font-size: 17px; }
h4 { font-size: 16px; }
p { margin: 8px 0; }
strong { color: #0b3d91; }
a { color: #0b5cad; }
.url { color: #8c959f; }
ul, ol { margin: 8px 0 8px 8px; }
li { margin-bottom: 6px; }
blockquote {
    color: #57606a;
    border-left: 3px solid #d0d7de;
    padding-left: 10px;
    margin: 8px 0;
}
code { background: #f2f4f7; }
pre { background: #f2f4f7; padding: 8px; }
hr { border-top: 1px solid #d8dee4; margin: 12px 0; }
table { border-collapse: collapse; }
th, td { border: 1px solid #d0d7de; padding: 4px 8px; }
"""

PAGE_WIDTH = 760
PADDING = 26
MAX_PAGE_HEIGHT = 14000  # PDF 页面高度上限为 200 inch = 14400pt
MAX_PNG_BYTES = 1800000  # 单张图片字节上限，超出则降低 dpi 重渲染


def render_markdown_image(text: str):
    """
    将 markdown 文本渲染为 PNG 图片。

    :param text: markdown 文本
    :return: 成功返回 BytesIO，失败返回 None
    """
    if not text or not text.strip() or not markdown or not pymupdf:
        return None
    try:
        html = markdown.markdown(text, extensions=["extra", "sane_lists", "nl2br"])
        html = _keep_link_url(html)
    except Exception as e:
        logger.error(f"[markdown_image] markdown convert failed: {e}")
        return None

    data = None
    for dpi in (144, 110, 96):
        try:
            data = _render_html_to_png(html, dpi)
        except Exception as e:
            logger.error(f"[markdown_image] render failed: {e}")
            return None
        if data and len(data) <= MAX_PNG_BYTES:
            break
    if not data:
        return None
    logger.info(f"[markdown_image] rendered image size={len(data)} bytes")
    return io.BytesIO(data)


def _keep_link_url(html: str) -> str:
    """图片中的链接不可点击，因此在链接文字后补上 URL，避免地址丢失"""
    def _replace(match):
        url, label = match.group(1), match.group(2)
        label_text = re.sub(r"<[^>]+>", "", label).strip()
        if not label_text or label_text == url:
            return url
        return f'{label} <span class="url">({url})</span>'

    return re.sub(r'<a\s+[^>]*href="([^"]+)"[^>]*>(.*?)</a>', _replace, html, flags=re.S | re.I)


def _render_html_to_png(html: str, dpi: int) -> bytes:
    """按内容自动调整页面高度，渲染后裁剪到实际内容底部"""
    height = 800
    doc = None
    page = None
    while True:
        doc = pymupdf.open()
        page = doc.new_page(width=PAGE_WIDTH, height=height)
        rect = pymupdf.Rect(PADDING, PADDING, PAGE_WIDTH - PADDING, height - PADDING)
        result = page.insert_htmlbox(rect, html, css=CSS)
        # result 为 (剩余空间, 缩放比例)，缩放小于 1 说明内容被压缩放不下
        scale = result[1] if isinstance(result, (tuple, list)) else 1.0
        if scale >= 0.99 or height >= MAX_PAGE_HEIGHT:
            break
        doc.close()
        doc = None
        height = min(height * 2, MAX_PAGE_HEIGHT)
    try:
        words = page.get_text("words")
        bottom = max((w[3] for w in words), default=PADDING + 40)
        page.set_mediabox(pymupdf.Rect(0, 0, PAGE_WIDTH, min(bottom + PADDING, height)))
        return page.get_pixmap(dpi=dpi).tobytes("png")
    finally:
        if doc:
            doc.close()
