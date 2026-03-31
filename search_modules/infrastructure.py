import html
import json
import math
import re
from collections import Counter
from datetime import datetime


def patch_argos_stanza_offline_mode():
    try:
        from argostranslate import sbd as argos_sbd
    except Exception:
        return

    def split_sentences_offline(self, text):
        if text is None:
            return [""]
        return [text]

    argos_sbd.StanzaSentencizer.split_sentences = split_sentences_offline
    argos_sbd.MiniSBDSentencizer.split_sentences = split_sentences_offline


def build_highlighted_text_html(raw_text, query):
    text = raw_text if raw_text is not None else ""
    q = (query or "").strip()
    if not q:
        return text, False
    if re.fullmatch(r"[A-Za-z][A-Za-z'\-]*", q):
        pattern = re.compile(rf"(?<![A-Za-z]){re.escape(q)}(?![A-Za-z])", re.IGNORECASE)
    else:
        pattern = re.compile(re.escape(q), re.IGNORECASE)
    parts = []
    last = 0
    found = False
    for m in pattern.finditer(text):
        found = True
        start, end = m.span()
        if start > last:
            parts.append(html.escape(text[last:start]))
        parts.append(f"<span style='background-color:#6b4f00;color:#ffe9a8;border-radius:3px;'>{html.escape(text[start:end])}</span>")
        last = end
    if not found:
        return text, False
    if last < len(text):
        parts.append(html.escape(text[last:]))
    return "".join(parts).replace("\n", "<br>"), True


class LLMCacheStore:
    def __init__(self, conn):
        self.conn = conn

    def ensure_schema(self):
        cur = self.conn.cursor()
        cur.execute(
            'CREATE TABLE IF NOT EXISTS llm_translations (query TEXT NOT NULL, kind TEXT NOT NULL, content_html TEXT NOT NULL, updated_at TEXT, PRIMARY KEY(query, kind))'
        )
        self.conn.commit()

    def get_cached_html(self, query, kind):
        q = (query or "").strip()
        k = (kind or "").strip()
        if not q or not k:
            return ""
        cur = self.conn.cursor()
        cur.execute('SELECT content_html FROM llm_translations WHERE query = ? AND kind = ? LIMIT 1', (q, k))
        row = cur.fetchone()
        return row[0] if row else ""

    def save_cached_html(self, query, kind, content_html):
        q = (query or "").strip()
        k = (kind or "").strip()
        html_text = (content_html or "").strip()
        if not q or not k or not html_text:
            return
        ts = datetime.now().isoformat(timespec='seconds')
        cur = self.conn.cursor()
        cur.execute(
            'INSERT INTO llm_translations(query, kind, content_html, updated_at) VALUES(?, ?, ?, ?) ON CONFLICT(query, kind) DO UPDATE SET content_html = excluded.content_html, updated_at = excluded.updated_at',
            (q, k, html_text, ts),
        )
        self.conn.commit()


class InfrastructureMixin:
    def contains_chinese(self, text):
        return bool(re.search(r'[\u4e00-\u9fff]', text or ""))

    def vectorize_chinese_text(self, text):
        cleaned = re.sub(r'\s+', '', text or '')
        chars = [ch for ch in cleaned if '\u4e00' <= ch <= '\u9fff']
        grams = chars[:]
        grams += [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]
        return Counter(grams)

    def cosine_similarity(self, va, vb):
        if not va or not vb:
            return 0.0
        common = set(va.keys()) & set(vb.keys())
        dot = sum(va[k] * vb[k] for k in common)
        na = math.sqrt(sum(v * v for v in va.values()))
        nb = math.sqrt(sum(v * v for v in vb.values()))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    def is_english_text(self, text):
        raw = (text or "").strip()
        if not raw:
            return False
        if re.search(r'[\u4e00-\u9fff]', raw):
            return False
        return re.search(r'[A-Za-z]', raw) is not None

    def normalize_api_url(self, url):
        raw = (url or '').strip()
        if not raw:
            return raw
        lower = raw.lower()
        if lower.endswith('/chat/completions'):
            return raw
        if lower.endswith('/v1'):
            return raw + '/chat/completions'
        return raw.rstrip('/') + '/v1/chat/completions'

    def extract_text_from_response(self, resp_text):
        try:
            obj = json.loads(resp_text)
            if isinstance(obj, dict):
                choices = obj.get("choices", [])
                if choices:
                    first = choices[0]
                    if "message" in first and "content" in first["message"]:
                        return first["message"]["content"]
                    if "text" in first:
                        return first["text"]
        except Exception:
            pass
        return resp_text

    def extract_words_from_ai_result(self, text):
        raw = (text or "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
            raw = re.sub(r"\s*```$", "", raw)
        words = []
        try:
            obj = json.loads(raw)
            candidate = obj.get("words", [])
            if isinstance(candidate, list):
                words = [str(x).strip() for x in candidate]
        except Exception:
            pass
        if not words:
            words = re.findall(r"[A-Za-z][A-Za-z\-']*", raw)
        normalized = []
        seen = set()
        for w in words:
            token = w.strip().lower()
            if not token:
                continue
            if token in seen:
                continue
            seen.add(token)
            normalized.append(token)
        return normalized

    def get_mid_model_name(self):
        return (self.settings.get('model_mid', '') or '').strip()

    def get_high_model_name(self):
        high = (self.settings.get('model_high', '') or '').strip()
        if high:
            return high
        return (self.settings.get('model', '') or '').strip()
