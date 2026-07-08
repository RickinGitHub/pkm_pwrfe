# -*- coding: utf-8 -*-
"""Web → Markdown 导出工具 (零外部依赖)。

将微信公众号文章或通用网页抓取并转换为 Markdown / HTML / JSON 文件，
支持图片与文件附件下载、链接提取、批量处理。iframe / video / audio /
embed 等嵌入媒体统一转为可点击 Markdown 链接占位（保留原 URL，CDN 失效
后仍可访问原文）。

作为 ai-agent-core 的 Skill 接入时，使用 FetchWebToMd 类:

    from skills.fetch_web_to_md import FetchWebToMd
    skill = FetchWebToMd()
    out = skill.execute({
        "op": "fetch",
        "url": "https://mp.weixin.qq.com/s/xxx",
        "format": "md",              # 可选: md / json / html
        "save_img": False,           # 可选: 下载图片到 <dir>/images/ 并改写 .md URL
        "save_attachments": False,   # 可选: 下载附件到 <dir>/attachments/ 并改写 .md URL
        "output_path": None,         # 可选: 输出**目录**（相对或绝对），默认 rag/corpus/
        "timeout": 30,               # 可选
    })
    # out == {"ok": True, "result": {"filepath": ..., "title": ..., "chars": ...,
    #                                 "images_count": ..., "attachments_count": ...,
    #                                 "images_downloaded": ..., "attachments_downloaded": ...},
    #         "error": None}

CLI 用法:
  python fetch_web_to_md.py --url "https://..."
  python fetch_web_to_md.py --url "URL" --path output
  python fetch_web_to_md.py --filepath urls.txt
  python fetch_web_to_md.py --text "粘贴微信聊天记录，自动提取其中URL"

Examples:
  [1] 抓取微信文章
      fetch_web_to_md.py --url "https://mp.weixin.qq.com/s/xxx"
      fetch_web_to_md.py --url "https://mp.weixin.qq.com/s/xxx" --save-img

  [2] 抓取通用网页
      fetch_web_to_md.py --url "https://example.com/article"

  [3] 指定输出目录（相对或绝对路径）
      fetch_web_to_md.py --url "URL" --path output
      fetch_web_to_md.py --url "URL" --path rag/corpus --format json
      fetch_web_to_md.py --url "URL" --path /abs/path --format html
      # 文件名基于原文 title 自动生成：<title>.md / <title>.json / <title>.html

  [4] 批量抓取 (文件中每行一个 URL)
      fetch_web_to_md.py --filepath urls.txt

  [5] 从聊天记录提取 URL (解决转发后链接不可点击)
      fetch_web_to_md.py --text "消息1 https://xxx 消息2 https://yyy"

  [6] 仅提取链接 (不抓取正文)
      fetch_web_to_md.py --url "URL" --links-only

  [7] 下载图片 + 文件附件 (pdf/zip/docx/mp4/...) 到本地并改写 .md URL
      fetch_web_to_md.py --url "URL" --save-img --save-attachments
      # 输出目录结构:
      #   <dir>/<title>.md
      #   <dir>/images/<title>_img1.png
      #   <dir>/attachments/<title>_att1_论文.pdf

Arguments:
  (以下三选一)
    --url URL           单个网页 URL（自动检测类型）
    --filepath FILEPATH  URL 列表文件（每行一个）
    --text TEXT         粘贴文本，自动提取其中所有 http(s):// 链接

  (可选)
    --path DIR          输出目录（相对或绝对路径，默认: rag/corpus/）
                        文件名基于原文 title：<title>.<ext>
    --format FMT        输出格式: md(默认) / json / html
    --save-img          下载文章图片到 <path>/images/ 并改写 .md URL 为本地相对路径
    --save-attachments  下载文件附件 (pdf/zip/docx/xlsx/pptx/mp4/mp3/...) 到
                        <path>/attachments/ 并改写 .md URL
    --links-only        仅提取页面中的所有链接，不抓取正文
    -t, --timeout SEC    网络超时秒数（默认 30）
    -h, --help           显示完整帮助文档

Supported Sources:
  微信公众号 (weixin.qq.com)   提取 js_content + 作者(nickname)，使用微信 UA
  任意网页                     提取 body 正文，自动去除 script/style/nav/footer

HTML -> Markdown:
  h1-h6 | **bold** | *italic* | [link](url) | ![img](url)
  ul/ol | table | blockquote | p/div | br
  iframe / video / audio / embed → [📎 Video](url) 等可点击链接占位

Output Formats:
  md   : Markdown (默认)  # Title + Author + Body + 元信息 + 附件清单
  json : 结构化 JSON       # {title, author, content, links, images, attachments, meta}
  html : 原始 HTML 清理版   # 去噪后的完整 HTML (可配合图片转 base64)

Output:
  <path>/<title>.<ext>     # 默认 rag/corpus/<title>.<ext>
  <path>/images/           # --save-img 时
  <path>/attachments/      # --save-attachments 时
"""
import argparse
import base64
import os
import re
import sys
from datetime import datetime
try:
    from urllib.request import Request, urlopen, urlretrieve
    from urllib.error import URLError, HTTPError
    HAS_URLLIB = True
except ImportError:
    HAS_URLLIB = False

_HERE = os.path.dirname(os.path.abspath(__file__))
# 项目根: skills/ → ..(ai-agent-core)
_PROJECT_ROOT = os.path.normpath(os.path.join(_HERE, '..'))
# 默认输出到 rag/corpus，抓取的内容直接进入知识库
_DEFAULT_OUTPUT = os.path.join(_PROJECT_ROOT, 'rag', 'corpus')

# ══════════════════════════════════════════════════════════════
#  配置常量
# ══════════════════════════════════════════════════════════════

DEFAULT_TIMEOUT = 30
MAX_REDIRECTS = 5
IMG_DIR = 'images'
ATTACHMENT_DIR = 'attachments'

# 文件附件扩展名（识别 <a href="xxx"> 为附件）
ATTACHMENT_EXTS = (
    '.pdf', '.zip', '.rar', '.7z', '.tar', '.gz', '.bz2',
    '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.mp4', '.mp3', '.wav', '.mov', '.avi', '.mkv', '.webm',
    '.m4a', '.aac', '.flac', '.ogg',
    '.txt', '.csv', '.json', '.yaml', '.yml', '.md',
    '.epub', '.mobi',
)

# 微信公众号 UA (模拟 PC 微信内置浏览器)
WECHAT_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/120.0.0.0 Safari/537.36 '
    'MicroMessenger/7.0.20.1781 NetType/WIFI '
    'WindowsWechat/WMPF XWEB/9191'
)

# 通用浏览器 UA
BROWSER_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/120.0.0.0 Safari/537.36'
)


# ══════════════════════════════════════════════════════════════
#  核心: HTTP 抓取
# ══════════════════════════════════════════════════════════════

def http_get(url, timeout=DEFAULT_TIMEOUT, ua=None, follow_redirects=True):
    """发送 HTTP GET 请求，返回 (html, final_url, headers)。

    Args:
        url: 目标 URL
        timeout: 超时秒数
        ua: 自定义 User-Agent（None 则根据 URL 自动选择）
        follow_redirects: 是否跟随重定向

    Returns:
        tuple: (html_content, final_url, response_headers_dict)

    Raises:
        URLError: 网络错误 / 超时
    """
    if not HAS_URLLIB:
        raise ImportError('urllib 不可用')

    if ua is None:
        ua = WECHAT_UA if ('weixin.qq.com' in url
                             or 'mp.weixin.qq.com' in url) else BROWSER_UA

    req = Request(url, headers={
        'User-Agent': ua,
        'Accept': (
            'text/html,application/xhtml+xml,application/xml;q=0.9,'
            '*/*;q=0.8,image/webp,*/*;q=0.8'),
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    })

    resp = urlopen(req, timeout=timeout)
    html = resp.read().decode('utf-8', errors='ignore')
    final_url = resp.geturl()
    hdr = dict(resp.headers) if hasattr(resp, 'headers') else {}
    return html, final_url, hdr


# ══════════════════════════════════════════════════════════════
#  抓取器: 微信公众号文章
# ══════════════════════════════════════════════════════════════

def fetch_wechat_article(url, timeout=DEFAULT_TIMEOUT):
    """抓取微信公众号文章。

    Returns:
        dict: {
            title, author, content_html, content_md,
            raw_html_len, links, images,
            publish_time, account_name,
            _url, _source_type
        }
    """
    html, final_url, _headers = http_get(
        url, timeout=timeout, ua=WECHAT_UA)

    # 标题
    title = _extract_meta(html, 'og:title') or _extract_tag(html, 'title')
    title = _unescape(title).strip()

    # 作者 / 公众号名
    author = ''
    m = re.search(r'var\s+nickname\s*=\s*"([^"]*)"', html)
    if m:
        author = _unescape(m.group(1))
    if not author:
        author = _extract_meta(html, 'article:author') or ''

    # 账号名
    account_name = _extract_meta(html, 'og:site_name') or author

    # 发布时间
    pub_time = ''
    m_pt = re.search(r'var\s+ct\s*=\s*"(\d{14})"', html)
    if m_pt:
        ts = m_pt.group(1)
        try:
            pub_time = '%s-%s-%s' % (ts[:4], ts[4:6], ts[6:8])
        except Exception:
            pass

    # 正文 — 用 div 深度计数匹配正确的闭合 </div>
    content_html = ''
    m_start = re.search(
        r'<div[^>]*id=["\']js_content["\'][^>]*>',
        html, re.IGNORECASE)
    if m_start:
        body_begin = m_start.end()
        depth = 0
        i = body_begin
        while i < len(html):
            if html[i:i+4] == '<div' or html[i:i+5] == '< div':
                depth += 1
            elif html[i:i+6] == '</div>':
                if depth > 0:
                    depth -= 1
                else:
                    content_html = html[body_begin:i]
                    break
            i += 1

    # 提取链接和图片
    links = _extract_links(content_html or html)
    images = _extract_images(content_html or html)
    attachments = extract_attachments(content_html or html)

    content_md = _html_to_markdown(content_html) if content_html else ''

    return {
        'title': title,
        'author': author,
        'account_name': account_name,
        'publish_time': pub_time,
        'content_html': content_html,
        'content_md': content_md,
        'raw_html_len': len(html),
        'links': links,
        'images': images,
        'attachments': attachments,
        '_url': final_url,
        '_source_type': 'wechat',
    }


# ══════════════════════════════════════════════════════════════
#  抓取器: 通用网页
# ══════════════════════════════════════════════════════════════

def fetch_generic_page(url, timeout=DEFAULT_TIMEOUT):
    """抓取通用网页。

    Returns:
        dict: 同 fetch_wechat_article() 结构（author 为空）
    """
    html, final_url, headers = http_get(url, timeout=timeout)

    title = (_extract_meta(html, 'og:title')
             or _extract_tag(html, 'title'))
    title = _unescape(title).strip()

    # 提取 <body>
    body_m = re.search(r'<body[^>]*>(.*?)</body>',
                     html, re.DOTALL | re.IGNORECASE)
    body_html = body_m.group(1) if body_m else html

    # 去噪
    clean = re.sub(
        r'<(script|style|noscript|nav|header|footer|aside)'
        r'[^>]*>.*?</\1>',
        '', body_html, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r'<!--.*?-->', '', clean, flags=re.DOTALL)

    links = _extract_links(clean or html)
    images = _extract_images(clean or html)
    attachments = extract_attachments(clean or html)
    content_md = _html_to_markdown(clean) if clean else ''

    return {
        'title': title,
        'author': '',
        'account_name': '',
        'publish_time': '',
        'content_html': clean[:5000],
        'content_md': content_md,
        'raw_html_len': len(html),
        'links': links,
        'images': images,
        'attachments': attachments,
        '_url': final_url,
        '_source_type': 'web',
    }


# ══════════════════════════════════════════════════════════════
#  链接 / 图片提取
# ══════════════════════════════════════════════════════════════

def extract_links_from_html(html):
    """从 HTML 中提取所有链接。

    Returns:
        list[dict]: [{'href', 'text'}]
    """
    results = []
    seen = set()
    links = []
    for m in re.finditer(
            r'<a[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            html, re.DOTALL | re.IGNORECASE):
        href = _unescape(m.group(1)).strip()
        text = _strip_tags(m.group(2)).strip()
        # 过滤 javascript: / mailto: / tel: / #
        if (href and href not in seen
                and not href.startswith(('javascript:', 'mailto:', 'tel:', '#'))
                and len(href) > 5):
            seen.add(href)
            links.append({'href': href, 'text': text})
    return links


def _extract_links(html):
    """内部：提取链接列表。"""
    return [l['href'] for l in extract_links_from_text_or_html(html)]


def _extract_images(html):
    """从 HTML 中提取图片 URL。

    Returns:
        list[dict]: [{'src', 'alt'}]
    """
    imgs = []
    for m in re.finditer(
            r'<img[^>]+src=["\']([^"\']+)["\'][^>]*'
            r'(?:alt=["\']([^"\']*)["\'])?',
            html, re.IGNORECASE):
        src = m.group(1).strip()
        alt = (m.group(2) or '').strip()
        if src and src.startswith('http'):
            imgs.append({'src': src, 'alt': alt})
    return imgs


def extract_attachments(html):
    """从 HTML 中提取文件附件链接（<a href="*.pdf|zip|docx|mp4|...">）。

    Returns:
        list[dict]: [{'src', 'text', 'ext'}]
    """
    attachments = []
    seen = set()
    for m in re.finditer(
            r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([^<]*)</a>',
            html, re.IGNORECASE):
        src = m.group(1).strip()
        text = (m.group(2) or '').strip()
        if not src or not src.startswith('http'):
            continue
        lower = src.lower().split('?')[0].split('#')[0]
        ext = None
        for e in ATTACHMENT_EXTS:
            if lower.endswith(e):
                ext = e
                break
        if ext is None:
            continue
        if src in seen:
            continue
        seen.add(src)
        attachments.append({'src': src, 'text': text, 'ext': ext})
    return attachments


# ══════════════════════════════════════════════════════════════
#  文本 URL 提取 (微信聊天记录)
# ══════════════════════════════════════════════════════════════

def extract_links_from_text(text):
    """从纯文本中提取所有 URL（支持微信转发聊天记录）。

    Returns:
        list[dict]: [{'href': url, 'text': ''}]
    """
    import html as html_mod
    decoded = html_mod.unescape(text)

    patterns = [
        r'https?://[^\s<>\"]{10,}',
        r'mp\.weixin\.qq\.com/[sS]{5,40}',
        r'[a-z]+\.[a-z]{2,}\.[a-z]{2,}/[xX]/[A-Za-z0-9]+',
    ]

    # URL 尾部清理（仅清理尾部标点，不破坏 URL 内部字符）
    _TRAIL_CHARS = (
        '.,;:!?)\\\'"》』）」'
        '\u201c\u3001\u3002\uff01\uff0c\uff1b')

    seen = set()
    results = []
    for pat in patterns:
        for m in re.finditer(pat, decoded):
            url = m.group(0).strip(_TRAIL_CHARS)
            url = url.rstrip(_TRAIL_CHARS)
            if url not in seen and len(url) > 15:
                seen.add(url)
                results.append({'href': url, 'text': ''})
    return results


def extract_links_from_text_or_html(content):
    """智能判断输入是文本还是 HTML，提取其中链接。"""
    if '<' in content and '>' in content:
        return extract_links_from_html(content)
    return extract_links_from_text(content)


# ══════════════════════════════════════════════════════════════
#  HTML → Markdown 转换器
# ══════════════════════════════════════════════════════════════

def _html_to_markdown(html):
    """HTML → Markdown 转换（原文呈现模式，确保零内容丢失）。

    支持: h1-h6, strong/b, em/i, a, img, ul/ol/li, blockquote,
          table/tr/th/td, section/div, span, br, p, code/pre,
          mp(微信多媒体), iframe, hr, u/del/s(删除线), sup/sub.
    """
    import html as html_mod
    text = html_mod.unescape(html)

    # ── 代码块（优先处理，防止内部被误转义）──
    # <pre><code> → ``` 代码块 ```
    def _preserve_code(m):
        code = m.group(1)
        code = re.sub(r'<br\s*/?>', '\n', code, flags=re.IGNORECASE)
        return '\n```\n%s\n```\n' % _strip_tags(code)

    text = re.sub(
        r'<pre[^>]*>\s*<code[^>]*>(.*?)</code>\s*</pre>',
        _preserve_code, text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(
        r'<pre[^>]*>(.*?)</pre>', _preserve_code,
        text, flags=re.DOTALL | re.IGNORECASE)

    # 图片（保留所有图片）
    text = re.sub(
        r'<img[^>]*src=["\']([^"\']*)["\'][^>]*alt=["\']([^"\']*)["\'][^>]*/?\s*>',
        r'![\2](\1)', text)
    text = re.sub(
        r'<img[^>]*alt=["\']([^"\']*)["\'][^>]*src=["\']([^"\']*)["\'][^>]*/?\s*>',
        r'![\1](\2)', text)
    text = re.sub(
        r'<img[^>]*src=["\']([^"\']*)["\'][^>]*/?\s*>',
        r'![](\1)', text)

    # 链接
    text = re.sub(
        r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>',
        r'[\2](\1)', text, flags=re.DOTALL)

    # 标题 (高→低优先级避免子标题被误匹配)
    for i in range(6, 0, -1):
        text = re.sub(
            r'<h%d[^>]*>(.*?)</h%d>' % (i, i),
            '\n%s \1\n' % ('#' * i), text, flags=re.DOTALL)

    # 加粗 / 斜体 / 删除线 / 下划线
    text = re.sub(r'<strong[^>]*>(.*?)</strong>', r'**\1**', text, flags=re.DOTALL)
    text = re.sub(r'<b[^>]*>(.*?)</b>', r'**\1**', text, flags=re.DOTALL)
    text = re.sub(r'<em[^>]*>(.*?)</em>', r'*\1*', text, flags=re.DOTALL)
    text = re.sub(r'<i[^>]*>(.*?)</i>', r'*\1*', text, flags=re.DOTALL)
    text = re.sub(r'<del[^>]*>(.*?)</del>', r'~~\1~~', text, flags=re.DOTALL)
    text = re.sub(r'<s[^>]*>(.*?)</s>', r'~~\1~~', text, flags=re.DOTALL)
    text = re.sub(r'<u[^>]*>(.*?)</u>', r'<u>\1</u>', text, flags=re.DOTALL)

    # 微信多媒体标签 <mp-check-text> 等 → 提取文本
    text = re.sub(r'<mp-[\w-]+[^>]*>(.*?)</mp-[\w-]+>', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'<mp[^>]*>', '', text)  # 自闭合 mp 标签清空

    # iframe → 可点击的 Markdown 链接占位（保留原 URL，CDN 失效后仍可访问）
    text = re.sub(
        r'<iframe[^>]*src=["\']([^"\']*)["\'][^>]*>',
        r'[📎 Embedded content](\1)\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<iframe[^>]*>', '[📎 Embedded content]\n', text, flags=re.IGNORECASE)

    # <video>/<audio>/<source> → 可点击链接（不下载，仅保留原 URL）
    text = re.sub(
        r'<video[^>]*src=["\']([^"\']*)["\'][^>]*>.*?</video>',
        r'[📎 Video](\1)\n', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(
        r'<video[^>]*>.*?<source[^>]*src=["\']([^"\']*)["\'][^>]*/?>.*?</video>',
        r'[📎 Video](\1)\n', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(
        r'<audio[^>]*src=["\']([^"\']*)["\'][^>]*>.*?</audio>',
        r'[📎 Audio](\1)\n', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(
        r'<audio[^>]*>.*?<source[^>]*src=["\']([^"\']*)["\'][^>]*/?>.*?</audio>',
        r'[📎 Audio](\1)\n', text, flags=re.DOTALL | re.IGNORECASE)
    # 自闭合 video/audio/embed 标签
    text = re.sub(
        r'<(video|audio|embed)[^>]*src=["\']([^"\']*)["\'][^>]*/?\s*>',
        r'[📎 \1](\2)\n', text, flags=re.IGNORECASE)

    # 分隔线
    text = re.sub(r'<hr\s*/?>', '\n---\n', text, flags=re.IGNORECASE)

    # 上标 / 下标
    text = re.sub(r'<sup[^>]*>(.*?)</sup>', r'^\1^', text, flags=re.DOTALL)
    text = re.sub(r'<sub[^>]*>(.*?)</sub>', r'~\1~', text, flags=re.DOTALL)

    # 换行与段落结构
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</div>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</section>', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<li[^>]*>', '\n- ', text, flags=re.IGNORECASE)

    # 表格
    def _replace_table(m):
        inner = m.group(1)
        rows = re.findall(
            r'<tr[^>]*>(.*?)</tr>', inner, re.DOTALL | re.IGNORECASE)
        if not rows:
            return ''
        md_rows = []
        for ri, row in enumerate(rows):
            cells = re.findall(
                r'<t[dh][^>]*>(.*?)</t[dh]>',
                row, re.DOTALL | re.IGNORECASE)
            cells = [_strip_tags(c).strip() for c in cells]
            if cells:
                md_rows.append('| %s |' % ' | '.join(cells))
                if ri == 0 and re.match('<th', row, re.IGNORECASE):
                    md_rows.append('|%s|' % ('---|' * len(cells)))
        return '\n'.join(md_rows) + '\n'

    text = re.sub(
        r'<table[^>]*>(.*?)</table>', _replace_table, text,
        flags=re.DOTALL | re.IGNORECASE)

    # 引用块
    text = re.sub(
        r'<blockquote[^>]*>(.*?)</blockquote>',
        lambda m: '> ' + m.group(1).strip().replace('\n', '\n> ') + '\n',
        text, flags=re.DOTALL)

    # 段落内联代码
    text = re.sub(r'<code[^>]*>(.*?)</code>', r'`\1`', text, flags=re.DOTALL)

    # 清除剩余标签（保留标签内的文本内容）
    text = _strip_tags(text)

    # 清理多余空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _strip_tags(text):
    return re.sub(r'<[^>]+>', '', text)


# ══════════════════════════════════════════════════════════════
#  HTML 工具函数
# ══════════════════════════════════════════════════════════════

def _extract_meta(html, prop):
    """提取 meta 标签属性值。"""
    m = re.search(
        r'<meta[^>]*property=["\']%s["\'][^>]*content=["\']([^"]*)"' % re.escape(prop),
        html, re.IGNORECASE)
    return m.group(1) if m else None


def _extract_tag(html, tag):
    """提取指定标签的文本内容。"""
    m = re.search(r'<%s[^>]*>(.*?)</%s>' % (tag, tag), html, re.IGNORECASE | re.DOTALL)
    return _unescape(m.group(1)) if m else None


def _unescape(s):
    """HTML 实体解码。"""
    s = re.sub(r'&nbsp;', ' ', s)
    s = re.sub(r'&amp;', '&', s)
    s = re.sub(r'&lt;', '<', s)
    s = re.sub(r'&gt;', '>', s)
    s = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), s)
    s = re.sub(r'&#[xX]([0-9a-fA-F]+);',
                 lambda m: chr(int(m.group(1), 16)), s)
    return re.sub(r'\s+', ' ', s).strip()


def _safe_filename(name, max_len=60):
    """生成安全的文件名。"""
    name = re.sub(r'[\\/:*?"<>|\r\n]', '_', name)[:max_len].strip()
    return name or 'untitled'


# ══════════════════════════════════════════════════════════════
#  图片下载
# ════════════════════════════════════════════════════════════

def download_images(images, output_dir, prefix=''):
    """下载图片列表到本地目录。

    Returns:
        list[dict]: [{src, local_path, status}, ...]
    """
    if not HAS_URLLIB or not images:
        return []
    os.makedirs(output_dir, exist_ok=True)
    results = []

    for idx, img in enumerate(images):
        src = img['src']
        alt = img.get('alt', '')[:30]
        ext = _guess_ext(src)
        filename = '%s_img%d%s' % (prefix, idx + 1, ext)
        filepath = os.path.join(output_dir, filename)

        try:
            print('    [%d/%d] Downloading: %s (%s)' % (
                idx + 1, len(images), alt, src[:60]))
            urlretrieve(src, filepath)
            results.append({
                'src': src,
                'local_path': filepath,
                'status': 'ok',
            })
        except Exception as e:
            print('    [%d/%d] FAILED: %s (%s)' % (
                idx + 1, len(images), type(e).__name__, e))
            results.append({
                'src': src,
                'local_path': filepath,
                'status': 'error: %s' % e,
            })

    return results


def download_attachments(attachments, output_dir, prefix=''):
    """下载文件附件列表到本地目录。

    Args:
        attachments: list[dict] from extract_attachments()
        output_dir: 目标目录
        prefix: 文件名前缀（通常为安全标题）

    Returns:
        list[dict]: [{src, local_path, status, ext}, ...]
    """
    if not HAS_URLLIB or not attachments:
        return []
    os.makedirs(output_dir, exist_ok=True)
    results = []

    for idx, att in enumerate(attachments):
        src = att['src']
        ext = att.get('ext') or _guess_ext(src)
        text = att.get('text', '')[:30] or 'attachment'
        safe_text = _safe_filename(text, max_len=40) or 'attachment'
        filename = '%s_att%d_%s%s' % (prefix, idx + 1, safe_text, ext)
        filepath = os.path.join(output_dir, filename)

        try:
            print('    [%d/%d] Downloading attachment: %s (%s)' % (
                idx + 1, len(attachments), text, src[:60]))
            urlretrieve(src, filepath)
            results.append({
                'src': src,
                'local_path': filepath,
                'status': 'ok',
                'ext': ext,
            })
        except Exception as e:
            print('    [%d/%d] FAILED: %s (%s)' % (
                idx + 1, len(attachments), type(e).__name__, e))
            results.append({
                'src': src,
                'local_path': filepath,
                'status': 'error: %s' % e,
                'ext': ext,
            })

    return results


def rewrite_local_paths(content_md, images=None, attachments=None,
                        img_rel_dir='images', att_rel_dir='attachments'):
    """把 .md 内容里的远程 URL 改写为本地相对路径。

    Args:
        content_md: 原始 Markdown 文本
        images: list[dict] with 'src' + 'local_path' (from download_images)
        attachments: list[dict] with 'src' + 'local_path' (from download_attachments)
        img_rel_dir: .md 引用图片时的相对目录
        att_rel_dir: .md 引用附件时的相对目录

    Returns:
        str: 改写后的 Markdown 文本
    """
    if not content_md:
        return content_md

    text = content_md
    if images:
        for img in images:
            src = img.get('src')
            local = img.get('local_path')
            if not src or not local:
                continue
            if img.get('status') != 'ok':
                continue
            local_name = os.path.basename(local)
            rel_path = '%s/%s' % (img_rel_dir, local_name)
            text = text.replace(src, rel_path)

    if attachments:
        for att in attachments:
            src = att.get('src')
            local = att.get('local_path')
            if not src or not local:
                continue
            if att.get('status') != 'ok':
                continue
            local_name = os.path.basename(local)
            rel_path = '%s/%s' % (att_rel_dir, local_name)
            text = text.replace(src, rel_path)

    return text


def _guess_ext(url):
    """从 URL 或 Content-Type 推测文件扩展名。"""
    lower = url.lower().split('?')[0].split('#')[0]
    for ext_map in [
        (['.png'], ['.jpg', '.jpeg', '.png']),
        (['.gif'], ['.gif']),
        (['.svg'], ['.svg']),
        (['.ico'], ['.ico', '.png']),
        (['.webp'], ['.webp']),
    ]:
        for e in ext_map[0]:
            if e in lower:
                return e
    return '.jpg'


# ══════════════════════════════════════════════════════════════
#  多格式导出
# ══════════════════════════════════════════════════════════════

def save_as_markdown(result, output_path=None, images_local=None,
                     attachments_local=None):
    """导出为 Markdown 格式。

    Args:
        result: 抓取结果 dict
        output_path: 输出**目录**（相对或绝对路径）。None 时使用默认 _DEFAULT_OUTPUT。
                     文件名基于 title 生成：<title>.md
        images_local: list[dict] from download_images()，若提供则把 .md 里的
                      远程图片 URL 改写为本地相对路径
        attachments_local: list[dict] from download_attachments()，同上但用于附件
    """
    safe_title = _safe_filename(result['title'])
    filename = '%s.md' % safe_title

    out_dir, filepath = _resolve_output_path(output_path, filename)
    os.makedirs(out_dir, exist_ok=True)

    # 改写 .md 里的远程 URL → 本地相对路径
    content_md = result.get('content_md', '')
    if images_local or attachments_local:
        content_md = rewrite_local_paths(
            content_md,
            images=images_local,
            attachments=attachments_local,
        )

    lines = ['# %s' % result['title'], '']

    # 顶部元信息块
    meta_lines = []
    if result.get('author'):
        meta_lines.append('> **Author**: %s' % result['author'])
    if result.get('account_name') and result.get('account_name') != result.get('author', ''):
        meta_lines.append('> **Source**: %s' % result['account_name'])
    if result.get('publish_time'):
        meta_lines.append('> **Date**: %s' % result['publish_time'])
    meta_lines.append('> **URL**: <%s>' % result.get('_url', ''))
    meta_lines.append('> **Fetched**: %s' % datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    # 附件清单（若有）
    if attachments_local:
        meta_lines.append('')
        meta_lines.append('> **Attachments** (%d):' % len(attachments_local))
        for att in attachments_local:
            if att.get('status') == 'ok':
                rel = '%s/%s' % (ATTACHMENT_DIR, os.path.basename(att['local_path']))
                meta_lines.append('> - [%s](%s)' % (att.get('text') or att.get('ext', 'file'), rel))

    if meta_lines:
        lines.extend(meta_lines + [''])

    lines.append(content_md)
    lines.append('')
    lines.append('---')
    lines.append('*Exported by webfetch/fetch_web_to_md.py*')

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    return filepath


def save_as_json(result, output_path=None):
    """导出为 JSON 格式（结构化数据）。"""
    import json
    safe_title = _safe_filename(result['title'])
    filename = '%s.json' % safe_title

    out_dir, filepath = _resolve_output_path(output_path, filename)
    os.makedirs(out_dir, exist_ok=True)

    data = {
        'title': result['title'],
        'author': result.get('author', ''),
        'account_name': result.get('account_name', ''),
        'publish_time': result.get('publish_time', ''),
        'content_markdown': result.get('content_md', ''),
        'content_html': result.get('content_html', ''),
        'links': result.get('links', []),
        'images': result.get('images', []),
        'meta': {
            'source_url': result.get('_url', ''),
            'source_type': result.get('_source_type', ''),
            'raw_html_length': result.get('raw_html_len', 0),
            'fetched_at': datetime.now().isoformat(),
            'tool': 'webfetch/fetch_web_to_md.py',
        },
    }

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return filepath


def save_as_html(result, output_path=None, embed_images=False):
    """导出为 HTML 格式（清理后的正文 + 可选 base64 内嵌图片）。"""
    safe_title = _safe_filename(result['title'])
    filename = '%s.html' % safe_title

    out_dir, filepath = _resolve_output_path(output_path, filename)
    os.makedirs(out_dir, exist_ok=True)

    content = result.get('content_html', '')
    if embed_images:
        # 将图片转为 base64 data URI 内嵌
        for img in result.get('images', []):
            src = img['src']
            b64 = _image_to_base64(src)
            if b64:
                ext = _guess_ext(src).lstrip('.')
                content = content.replace(
                    'src="%s"' % src,
                    'src="data:image/%s;base64,%s"' % (ext, b64), 1)

    html_tpl = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
body {{ max-width:800px; margin:40px auto; padding:20px;
       font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
       line-height:1.6; color:#333 }}
h1 {{ border-bottom:2px solid #4472C4; padding-bottom:8px; }}
.meta {{ color:#666; font-size:0.9em; margin-bottom:20px; }}
img {{ max-width:100%; height:auto; }}
table {{ border-collapse:collapse; width:100%; margin:15px 0; }}
th,td {{ border:1px solid #ddd; padding:8px 12px; text-align:left; }}
th {{ background:#f5f5f5f5; }}
blockquote {{ border-left:4px solid #ddd; padding-left:12px; color:#666; margin:15px 0; }}
.footer {{ margin-top:40px; padding-top:15px; border-top:1px solid #eee;
             font-size:0.85em; color:#999; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="meta">
<p><strong>Author:</strong> {author} &nbsp;
<strong>Date:</strong> {date}</p>
</div>
{content}
<div class="footer">
<p><em>Fetched by webfetch/fetch_web_to_md.py @ {ts}</em></p>
<p><a href="{url}">Source</a></p>
</div>
</body>
</html>'''

    full_html = html_tpl.format(
        title=result['title'],
        author=result.get('author', 'N/A'),
        date=result.get('publish_time', 'N/A'),
        url=result.get('_url', '#'),
        content=content or '<p>(No content extracted)</p>',
        ts=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    )

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(full_html)

    return filepath


def _image_to_base64(url):
    """尝试将远程图片转为 base64（失败返回空字符串）。"""
    try:
        resp = urlopen(url, timeout=10)
        ct = resp.headers.get('Content-Type', '')
        data = resp.read()
        ext = _guess_ext(ct.split(';')[0]) if ';' in ct else '.bin'
        return base64.b64encode(data).decode('ascii')
    except Exception:
        return ''


def _resolve_output_path(output_path, default_filename):
    """解析输出路径，返回 (dir, abs_filepath)。

    Args:
        output_path: 输出**目录**（相对或绝对路径）。None 时使用默认 _DEFAULT_OUTPUT。
        default_filename: 默认文件名（基于 title 生成，无时间戳前缀）。

    Returns:
        tuple: (out_dir, abs_filepath)
    """
    if output_path:
        out_dir = os.path.abspath(output_path)
        filepath = os.path.join(out_dir, default_filename)
    else:
        out_dir = os.path.abspath(_DEFAULT_OUTPUT)
        filepath = os.path.join(out_dir, default_filename)
    return out_dir, filepath


SAVERS = {
    'md': save_as_markdown,
    'markdown': save_as_markdown,
    'json': save_as_json,
    'html': save_as_html,
}


# ══════════════════════════════════════════════════════════════
#  CLI 主入口
# ══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='Web -> Markdown Export Tool (standalone, zero dependency)',
        add_help=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('-h', '--help', action='store_true',
                        help='Show this help message and exit')
    parser.add_argument('--url', metavar='URL', help='Single URL (auto-detect WeChat/Web)')
    parser.add_argument('--path', metavar='DIR', default=None,
                        help='Output directory (relative or absolute). '
                             'Default: rag/corpus/. Filename is <title>.<ext>.')
    parser.add_argument('--format', metavar='FMT', default=None,
                        choices=['md', 'json', 'html'],
                        help='Output format: md(default) / json / html')
    parser.add_argument('--filepath', metavar='FILE', default=None,
                        help='File with URLs (one per line), batch mode')
    parser.add_argument('--text', metavar='TEXT', default=None,
                        help='Paste chat text to auto-extract URLs '
                             '(fixes non-clickable links in forwarded messages)')
    parser.add_argument('--save-img', action='store_true',
                        help='Download article images to output/images/')
    parser.add_argument('--save-attachments', action='store_true',
                        help='Download file attachments (pdf/zip/docx/mp4/mp3/...) '
                             'to output/attachments/ and rewrite .md URLs to local paths')
    parser.add_argument('--links-only', action='store_true',
                        help='Only extract links, skip content fetching')
    parser.add_argument('-t', '--timeout', metavar='SEC', type=int,
                        default=DEFAULT_TIMEOUT,
                        help='Network timeout in seconds (default: %d)' % DEFAULT_TIMEOUT)

    args = parser.parse_args()

    # --help
    if args.help:
        print(__doc__)
        sys.exit(0)

    # 收集 URLs
    urls = []
    if args.url:
        urls.append(args.url)
    if args.filepath:
        with open(args.filepath, 'r', encoding='utf-8') as f:
            for line in f:
                u = line.strip()
                if u and not u.startswith('#'):
                    urls.append(u)
    if args.text:
        extracted = extract_links_from_text(args.text)
        print('[Text] Extracted %d URLs:\n' % len(extracted))
        for i, item in enumerate(extracted):
            print('  [%d] %s' % (i + 1, item['href']))
        urls.extend(item['href'] for item in extracted)

    if not urls:
        parser.error('Provide --url / --filepath / --text')

    fmt = args.format or 'md'
    print('=' * 70)
    print('Web -> Markdown Export Tool')
    print('=' * 70)

    success = 0
    fail = 0
    all_links = []  # 全部链接汇总

    for url in urls:
        is_wechat = ('weixin.qq.com' in url
                   or 'mp.weixin.qq.com' in url)
        tag = '[WeChat]' if is_wechat else '[Web]'
        print('\n[%s] %s' % (tag, url))

        try:
            # --links-only: 只提取链接
            if args.links_only:
                if is_wechat:
                    html, _, _ = http_get(url, timeout=args.timeout, ua=WECHAT_UA)
                    links = extract_links_from_html(html)
                else:
                    html, _, _ = http_get(url, timeout=args.timeout)
                    links = extract_links_from_html(html)
                print('  Links: %d found' % len(links))
                for li in links[:10]:
                    print('    - %s (%s)' % (li['href'][:80], li['text'][:40]))
                if len(links) > 10:
                    print('    ... + %d more' % (len(links) - 10))
                all_links.extend(links)
                success += 1
                continue

            # 正常抓取
            if is_wechat:
                result = fetch_wechat_article(url, timeout=args.timeout)
            else:
                result = fetch_generic_page(url, timeout=args.timeout)

            result['_url'] = url
            print('  Title : %s' % result['title'])
            if result.get('author'):
                print('  Author: %s' % result['author'])

            n_chars = len(result.get('content_md', ''))
            n_lines = result['content_md'].count('\n') + 1 if result['content_md'] else 0
            print('  Body  : %d chars, %d lines' % (n_chars, n_lines))
            print('  Links : %d' % len(result.get('links', [])))
            print('  Images: %d' % len(result.get('images', [])))
            print('  Attachments: %d' % len(result.get('attachments', [])))

            # Determine output directory first (so img/att subdirs land next to .md)
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            safe_title = _safe_filename(result['title'])
            default_filename = '%s.md' % safe_title
            out_dir, fp = _resolve_output_path(args.path, default_filename)
            os.makedirs(out_dir, exist_ok=True)

            # Download images first (so save_as_markdown can rewrite URLs).
            images_local = None
            if args.save_img and result.get('images'):
                img_dir = os.path.join(out_dir, IMG_DIR)
                images_local = download_images(
                    result['images'], img_dir,
                    prefix=_safe_filename(result['title']))
                ok = sum(1 for r in images_local if r['status'] == 'ok')
                print('  Images: %d/%d downloaded' % (ok, len(images_local)))

            # Download attachments.
            attachments_local = None
            if args.save_attachments and result.get('attachments'):
                att_dir = os.path.join(out_dir, ATTACHMENT_DIR)
                attachments_local = download_attachments(
                    result['attachments'], att_dir,
                    prefix=_safe_filename(result['title']))
                ok = sum(1 for r in attachments_local if r['status'] == 'ok')
                print('  Attachments: %d/%d downloaded' % (ok, len(attachments_local)))

            # Export (save_as_markdown accepts local lists for URL rewriting).
            if fmt in ('md', 'markdown'):
                fp = save_as_markdown(
                    result, args.path,
                    images_local=images_local,
                    attachments_local=attachments_local,
                )
            else:
                saver = SAVERS.get(fmt, save_as_markdown)
                fp = saver(result, args.path)
            print('  Saved : %s (%s)' % (fp, fmt))

            all_links.extend(result.get('links', []))
            success += 1

        except Exception as e:
            print('  ERROR : %s: %s' % (type(e).__name__, e))
            fail += 1

    # 链接汇总（_extract_links 返回 list[str] of hrefs）
    if all_links and not args.links_only:
        unique_hrefs = sorted(set(all_links))
        print('\n' + '-' * 50)
        print('All Links Summary (%d unique):' % len(unique_hrefs))
        for href in unique_hrefs:
            print('  %s' % href[:80])

    print('\n' + '=' * 70)
    print('Done: %d OK, %d failed' % (success, fail))


if __name__ == '__main__':
    main()


# ══════════════════════════════════════════════════════════════
#  Skill 接口 (供 ai-agent-core AgentCore 调用)
# ══════════════════════════════════════════════════════════════

class FetchWebToMd:
    """Web → Markdown 导出 Skill，符合 ai-agent-core Skill 协议。

    execute(args) 接受参数:
        op               : "fetch" (必填)
        url              : 目标 URL (必填)
        format           : "md" / "json" / "html" (默认 "md")
        save_img         : bool, 下载图片到 output/images/ 并改写 .md URL (默认 False)
        save_attachments : bool, 下载文件附件 (pdf/zip/docx/mp4/...) 到 output/attachments/
                           并改写 .md URL (默认 False)
        output_path      : str, 自定义输出路径 (默认 None, 自动生成)
        timeout          : int, 网络超时秒 (默认 30)
        links_only       : bool, 仅提取链接不抓正文 (默认 False)

    返回信封:
        {"ok": True,  "result": {"filepath": ..., "title": ..., "chars": ...,
                                 "links_count": ..., "images_count": ...,
                                 "attachments_count": ...}, "error": None}
        {"ok": False, "result": None, "error": "<msg>"}
    """

    _SUPPORTED_OPS = {"fetch"}
    _SUPPORTED_FORMATS = {"md", "json", "html"}

    def __init__(self, url_registry=None):
        # P0-2: optional URL → path dedup registry. If provided, fetch checks it
        # first and returns the cached filepath instead of re-downloading.
        self._url_registry = url_registry

    def execute(self, args: dict) -> dict:
        op = args.get("op")
        if op != "fetch":
            return {"ok": False, "result": None, "error": f"unknown op: {op}"}

        url = args.get("url")
        if not isinstance(url, str) or not url.strip():
            return {"ok": False, "result": None, "error": "missing or empty 'url'"}
        url = url.strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            return {"ok": False, "result": None, "error": f"url must start with http:// or https://: {url}"}

        fmt = args.get("format", "md")
        if fmt not in self._SUPPORTED_FORMATS:
            return {"ok": False, "result": None, "error": f"unsupported format: {fmt} (supported: {sorted(self._SUPPORTED_FORMATS)})"}

        timeout = args.get("timeout", DEFAULT_TIMEOUT)
        if not isinstance(timeout, int) or timeout <= 0:
            return {"ok": False, "result": None, "error": f"invalid timeout: {timeout}"}

        output_path = args.get("output_path")
        save_img = bool(args.get("save_img", False))
        save_attachments = bool(args.get("save_attachments", False))
        links_only = bool(args.get("links_only", False))
        force = bool(args.get("force", False))

        # P0-2: dedup check. Skip if we've already fetched this URL and the file
        # still exists, unless caller passes force=True.
        if self._url_registry is not None and not force and not links_only:
            cached = self._url_registry.lookup(url)
            if cached and os.path.exists(cached["filepath"]):
                return {
                    "ok": True,
                    "result": {
                        "filepath": cached["filepath"],
                        "title": cached.get("title", ""),
                        "chars": 0,
                        "links_count": 0,
                        "images_count": 0,
                        "attachments_count": 0,
                        "images_downloaded": 0,
                        "attachments_downloaded": 0,
                        "format": fmt,
                        "source_type": "cached",
                        "deduped": True,
                        "fetched_at": cached.get("fetched_at", ""),
                    },
                    "error": None,
                }

        try:
            if links_only:
                html, _, _ = http_get(url, timeout=timeout)
                links = extract_links_from_html(html)
                return {
                    "ok": True,
                    "result": {
                        "url": url,
                        "links_count": len(links),
                        "links": [{"href": l["href"], "text": l["text"]} for l in links],
                    },
                    "error": None,
                }

            is_wechat = "weixin.qq.com" in url or "mp.weixin.qq.com" in url
            if is_wechat:
                result = fetch_wechat_article(url, timeout=timeout)
            else:
                result = fetch_generic_page(url, timeout=timeout)
            result["_url"] = url

            # Resolve output dir up-front so img/att subdirs land next to .md.
            safe_title = _safe_filename(result['title'])
            default_filename = '%s.%s' % (safe_title, fmt)
            out_dir, _resolved = _resolve_output_path(output_path, default_filename)

            # Download images first (so save_as_markdown can rewrite URLs).
            images_local = None
            if save_img and result.get("images"):
                img_dir = os.path.join(out_dir, IMG_DIR)
                images_local = download_images(
                    result["images"], img_dir,
                    prefix=_safe_filename(result["title"]))

            # Download attachments.
            attachments_local = None
            if save_attachments and result.get("attachments"):
                att_dir = os.path.join(out_dir, ATTACHMENT_DIR)
                attachments_local = download_attachments(
                    result["attachments"], att_dir,
                    prefix=_safe_filename(result["title"]))

            # Export — for Markdown, pass local lists to enable URL rewriting.
            if fmt in ("md", "markdown"):
                filepath = save_as_markdown(
                    result, output_path,
                    images_local=images_local,
                    attachments_local=attachments_local,
                )
            else:
                saver = SAVERS.get(fmt, save_as_markdown)
                filepath = saver(result, output_path)

            self._record_url(url, filepath, result.get("title", ""))

            return {
                "ok": True,
                "result": {
                    "filepath": filepath,
                    "title": result["title"],
                    "author": result.get("author", ""),
                    "chars": len(result.get("content_md", "")),
                    "links_count": len(result.get("links", [])),
                    "images_count": len(result.get("images", [])),
                    "attachments_count": len(result.get("attachments", [])),
                    "images_downloaded": sum(1 for r in (images_local or []) if r.get("status") == "ok"),
                    "attachments_downloaded": sum(1 for r in (attachments_local or []) if r.get("status") == "ok"),
                    "format": fmt,
                    "source_type": result.get("_source_type", ""),
                },
                "error": None,
            }
        except Exception as e:
            return {"ok": False, "result": None, "error": f"{type(e).__name__}: {e}"}

    def _record_url(self, url: str, filepath: str, title: str) -> None:
        if self._url_registry is not None:
            try:
                self._url_registry.record(url, filepath, title)
            except Exception:
                pass
