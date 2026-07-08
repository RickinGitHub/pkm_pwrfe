"""Mixed-language tokenizer — English word split + Chinese character bigrams.

Handles:
  - English: "hello world" → ["hello", "world"]
  - Chinese: "查询简历" → ["查询", "询简", "简历"]
  - Mixed:   "AI 简历优化" → ["ai", "简历", "历优", "优化"]
"""

import re

# Unicode ranges for CJK characters
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")


def tokenize(text: str) -> list[str]:
    """Tokenize mixed CN/EN text into word-level + bigram-level tokens.

    English: splits on whitespace, lowercased.
    Chinese: overlapping 2-character bigrams for BM25-compatible indexing.
    """
    text = text.lower().strip()
    if not text:
        return []

    # Split into segments: CJK runs vs non-CJK
    segments: list[tuple[bool, str]] = []  # (is_cjk, text)
    buf = ""
    cjk = None
    for ch in text:
        is_cjk = bool(_CJK_RE.match(ch))
        if cjk is None:
            cjk = is_cjk
            buf = ch
        elif is_cjk == cjk:
            buf += ch
        else:
            segments.append((cjk, buf))
            cjk = is_cjk
            buf = ch
    if buf:
        segments.append((cjk, buf))

    tokens: list[str] = []
    for is_cjk, seg in segments:
        if is_cjk:
            # Chinese: character bigrams
            seg = re.sub(r"\s+", "", seg)
            if len(seg) == 1:
                tokens.append(seg)
            else:
                for i in range(len(seg) - 1):
                    tokens.append(seg[i:i + 2])
        else:
            # English/other: whitespace split, filter empty
            for word in seg.split():
                word = word.strip(".,;:!?()[]{}'\"")
                if word:
                    tokens.append(word)

    return tokens
