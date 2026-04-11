import html
import json
import re
import threading
from urllib import error, request

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QLabel, QTextBrowser

from search_modules.infrastructure import build_highlighted_text_html
from search_modules.ai_prompts import default_ai_prompts, loads_prompts, prompt_text


class LLMTranslationMixin:
    def get_ai_prompts(self):
        raw = self.settings.get("ai_prompts_json", "") if hasattr(self, "settings") else ""
        merged = dict(default_ai_prompts())
        user_obj = loads_prompts(raw)
        for k, v in (user_obj or {}).items():
            if isinstance(k, str) and isinstance(v, str) and k.strip():
                merged[k.strip()] = v
        return merged
    def prepare_llm_translate_context(self, target_text, is_word, restore_kind):
        self.llm_target_text = target_text
        self.llm_target_is_word = bool(is_word)
        self.llm_restore_kind = restore_kind
        self.llm_restore_query = self.current_query
        self.llm_translate_click_count = 0
        self.hide_llm_translation_widgets()
        self.show_cached_llm_translation_if_exists()

    def show_cached_llm_translation_if_exists(self):
        if not hasattr(self, 'llm_cache_store'):
            return
        cached_html = self.llm_cache_store.get_cached_html(self.llm_target_text, self.llm_restore_kind)
        if cached_html:
            self.llm_last_response_text = ""
            self.show_llm_translation_in_place(cached_html)

    def build_llm_translation_area(self):
        title = QLabel("LLM 补充翻译")
        title.setFont(self.make_ui_font(12, True))
        title.setStyleSheet('color: #61dafb; margin-top: 8px; margin-bottom: 4px;')
        title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        result_view = QTextBrowser()
        result_view.setOpenLinks(False)
        result_view.setOpenExternalLinks(False)
        result_view.setMinimumHeight(130)
        result_view.setVisible(False)
        if hasattr(self, 'install_ai_selection_context_menu'):
            self.install_ai_selection_context_menu(result_view, "LLM补充翻译")
        title.setVisible(False)
        self.detail_info_layout.addWidget(title)
        self.detail_info_layout.addWidget(result_view)
        self.llm_translation_widgets = [title, result_view]

    def hide_llm_translation_widgets(self):
        for w in getattr(self, 'llm_translation_widgets', []):
            if w is not None:
                w.setVisible(False)
        for w in getattr(self, 'translation_primary_widgets', []):
            if w is not None:
                w.setVisible(True)

    def show_llm_translation_in_place(self, result_html):
        if not getattr(self, 'llm_translation_widgets', None):
            return
        title = self.llm_translation_widgets[0]
        result_view = self.llm_translation_widgets[1]
        title.setVisible(True)
        result_view.setVisible(True)
        result_view.setHtml(result_html)

    def on_llm_translate_clicked(self):
        if not self.llm_target_text:
            return
        url = self.normalize_api_url(self.settings.get('api_url', ''))
        key = self.settings.get('api_key', '')
        mid_model = self.get_mid_model_name()
        high_model = self.get_high_model_name()
        if not url or not key:
            self.show_llm_translation_in_place("<div style='color:#e06c75;'>LLM 配置不完整：请在设置中配置 API URL 和 API Key</div>")
            return
        if not mid_model and not high_model:
            self.show_llm_translation_in_place("<div style='color:#e06c75;'>LLM 配置不完整：请在设置中至少配置一个模型名</div>")
            return
        if self.llm_translate_click_count == 0 and mid_model:
            model = mid_model
            model_level = "中级"
        else:
            model = high_model if high_model else mid_model
            model_level = "高级" if high_model else "中级"
        self.llm_translate_click_count += 1
        self.llm_translate_request_seq = int(getattr(self, "llm_translate_request_seq", 0)) + 1
        request_seq = self.llm_translate_request_seq
        loading_html = f"<div style='color:#98c379;'>正在使用{html.escape(model_level)}模型翻译...</div>"
        self.show_llm_translation_in_place(loading_html)
        prompt = self.build_llm_translate_prompt(self.llm_target_text, self.llm_target_is_word)
        threading.Thread(target=self._llm_translate_worker, args=(url, key, model, model_level, prompt, request_seq), daemon=True).start()

    def build_llm_translate_prompt(self, text, is_word):
        meaning_rule = "字符串数组，按词性与语义分组，尽可能覆盖常见义项、引申义与高频短语义，至少 4 条。"
        if not is_word:
            meaning_rule = "字符串，给出整句自然中文翻译，可补充一句语气/语境说明。"
        tmpl = prompt_text(self.get_ai_prompts(), "llm_translate_prompt", "")
        return (tmpl or "").format(
            meaning_rule=meaning_rule,
            kind=("单词" if is_word else "句子"),
            text=text,
        )

    def format_llm_translate_output(self, text):
        raw = (text or "").strip()
        cleaned = raw
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            obj = json.loads(cleaned)
            meaning = obj.get("释义", "")
            examples = obj.get("例句", [])
            usages = obj.get("常见用法", [])
            if isinstance(meaning, list):
                meaning_items = [str(x).strip() for x in meaning if str(x).strip()]
            else:
                meaning_items = [str(meaning).strip()] if str(meaning).strip() else []
            if not isinstance(examples, list):
                examples = [str(examples)]
            if not isinstance(usages, list):
                usages = [str(usages)]
            meaning_html = "".join([f"<li>{self.highlight_llm_text(str(x))}</li>" for x in meaning_items if str(x).strip()])
            example_html = "".join([f"<li>{self.highlight_llm_text(str(x))}</li>" for x in examples if str(x).strip()])
            usage_html = "".join([f"<li>{self.highlight_llm_text(str(x))}</li>" for x in usages if str(x).strip()])
            return (
                f"<div><b>释义</b><ul>{meaning_html or '<li>无</li>'}</ul></div>"
                f"<div><b>例句</b><ul>{example_html or '<li>无</li>'}</ul></div>"
                f"<div><b>常见用法</b><ul>{usage_html or '<li>无</li>'}</ul></div>"
            )
        except Exception:
            return f"<div><b>释义</b><div style='margin-top:4px;margin-bottom:8px;'>{self.highlight_llm_text(raw)}</div></div>"

    def highlight_llm_text(self, raw_text):
        plain = str(raw_text or "")
        if not self.current_query:
            return html.escape(plain)
        if not self.is_in_review(self.current_query):
            return html.escape(plain)
        # 获取当前主题的高亮颜色
        highlight_bg = self.colors.get('highlight_bg', '#6b4f00') if hasattr(self, 'colors') else '#6b4f00'
        highlight_text = self.colors.get('highlight_text', '#ffe9a8') if hasattr(self, 'colors') else '#ffe9a8'
        highlighted_html, matched = build_highlighted_text_html(plain, self.current_query, highlight_bg, highlight_text)
        if matched:
            return highlighted_html
        return html.escape(plain)

    def refresh_llm_translation_highlight(self):
        if not self.llm_last_response_text:
            return
        if not getattr(self, 'llm_translation_widgets', None):
            return
        result_view = self.llm_translation_widgets[1]
        if result_view is None or not result_view.isVisible():
            return
        html_text = self.format_llm_translate_output(self.llm_last_response_text)
        self.show_llm_translation_in_place(html_text)

    def _llm_translate_worker(self, url, key, model, model_level, prompt, request_seq):
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": prompt_text(self.get_ai_prompts(), "translator_system", "You are a precise bilingual translator.")},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.0,
            "stream": True
        }
        try:
            data = json.dumps(payload).encode("utf-8")
            req = request.Request(url, data=data, headers={
                "Accept": "text/event-stream",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}"
            }, method="POST")
            with request.urlopen(req, timeout=60) as resp:
                content_type = (resp.headers.get("Content-Type", "") or "").lower()
                text = ""
                if "text/event-stream" in content_type:
                    for raw_line in resp:
                        line = raw_line.decode("utf-8", errors="ignore").strip()
                        if not line.startswith("data:"):
                            continue
                        data_line = line[5:].strip()
                        if not data_line:
                            continue
                        if data_line == "[DONE]":
                            break
                        try:
                            obj = json.loads(data_line)
                        except Exception:
                            continue
                        choices = obj.get("choices", [])
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {})
                        piece = delta.get("content")
                        if not piece:
                            continue
                        text += piece
                        self.llm_result_ready.emit({
                            "ok": True,
                            "text": text,
                            "level": model_level,
                            "seq": request_seq,
                            "streaming": True,
                            "done": False,
                        })
                else:
                    resp_text = resp.read().decode("utf-8", errors="ignore")
                    text = (self.extract_text_from_response(resp_text) or "").strip()
                if not text:
                    text = "模型未返回内容"
                self.llm_result_ready.emit({
                    "ok": True,
                    "text": text,
                    "level": model_level,
                    "seq": request_seq,
                    "streaming": False,
                    "done": True,
                })
        except error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8", errors="ignore")
            except Exception:
                err_body = ""
            self.llm_result_ready.emit({
                "ok": False,
                "text": f"请求失败：HTTP {e.code} {e.reason}\n{err_body}",
                "level": model_level,
                "seq": request_seq,
                "streaming": False,
                "done": True,
            })
        except Exception as e:
            self.llm_result_ready.emit({
                "ok": False,
                "text": f"请求失败：{str(e)}",
                "level": model_level,
                "seq": request_seq,
                "streaming": False,
                "done": True,
            })

    def on_llm_translate_result(self, result):
        current_seq = int(getattr(self, "llm_translate_request_seq", 0))
        event_seq = int((result or {}).get("seq", current_seq))
        if event_seq != current_seq:
            return
        text = (result or {}).get("text", "")
        self.llm_last_response_text = text
        html_text = self.format_llm_translate_output(text)
        self.show_llm_translation_in_place(html_text)
        if (result or {}).get("ok") and (result or {}).get("done", True):
            self.llm_cache_store.save_cached_html(self.llm_target_text, self.llm_restore_kind, html_text)
