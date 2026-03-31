import json
import re
import threading
from datetime import datetime
from urllib import error, request

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtGui import QTextDocument
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QTextBrowser,
    QTextEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QLineEdit,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)


class AIChatWindow(QDialog):
    chat_result_ready = pyqtSignal(dict)

    def __init__(self, app, initial_prompt="", initial_payload="", title="AI 小助手"):
        super().__init__(app)
        self.app = app
        self.messages = [
            {"role": "system", "content": "你是英语学习助手。回答需要准确、清晰、结合上下文。"}
        ]
        self.setWindowTitle(title)
        self.resize(780, 560)
        layout = QVBoxLayout()
        self.chat_view = QTextBrowser()
        self.chat_view.setOpenExternalLinks(False)
        self.chat_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        layout.addWidget(self.chat_view, 1)
        input_row = QHBoxLayout()
        self.input_host = QWidget()
        self.input_stack = QStackedLayout()
        self.input_stack.setContentsMargins(0, 0, 0, 0)
        self.input_host.setLayout(self.input_stack)
        self.input_edit = QTextEdit()
        self.input_edit.setPlaceholderText("输入你的问题...")
        self.input_edit.setFixedHeight(90)
        self.input_edit.focusInEvent = self.on_input_focus_in
        self.input_preview = QTextBrowser()
        self.input_preview.setOpenExternalLinks(False)
        self.input_preview.setFixedHeight(90)
        self.input_stack.addWidget(self.input_preview)
        self.input_stack.addWidget(self.input_edit)
        self.input_stack.setCurrentWidget(self.input_edit)
        input_row.addWidget(self.input_host, 1)
        self.send_btn = QPushButton("发送")
        self.send_btn.setFixedWidth(88)
        self.send_btn.clicked.connect(self.on_send_clicked)
        input_row.addWidget(self.send_btn)
        layout.addLayout(input_row)
        self.setLayout(layout)
        self.chat_result_ready.connect(self.on_chat_result)
        if initial_prompt:
            self.send_message(initial_prompt, payload_text=initial_payload or initial_prompt)

    def markdown_to_html(self, text):
        doc = QTextDocument()
        doc.setMarkdown(text or "")
        html_text = doc.toHtml()
        m = re.search(r"<body[^>]*>([\s\S]*)</body>", html_text, re.IGNORECASE)
        if m:
            return m.group(1)
        return html_text

    def switch_input_to_preview(self):
        raw = self.input_edit.toPlainText()
        if raw.strip():
            self.input_preview.setHtml(self.markdown_to_html(raw))
        else:
            self.input_preview.setHtml("<div style='color:#888;'>输入你的问题...</div>")
        self.input_stack.setCurrentWidget(self.input_preview)

    def switch_input_to_edit(self):
        self.input_stack.setCurrentWidget(self.input_edit)
        self.input_edit.setFocus()

    def on_input_focus_in(self, event):
        QTextEdit.focusInEvent(self.input_edit, event)
        self.switch_input_to_edit()

    def mousePressEvent(self, event):
        target = self.childAt(event.position().toPoint())
        inside_input = target is self.input_edit or target is self.input_preview
        if not inside_input:
            self.switch_input_to_preview()
        QDialog.mousePressEvent(self, event)

    def append_message(self, role, text):
        if role == "user":
            prefix = "你"
            color = "#61dafb"
        else:
            prefix = "AI"
            color = "#98c379"
        body = self.markdown_to_html(text or "")
        block = f"<div style='margin-bottom:10px;'><b style='color:{color};'>{prefix}</b><div style='margin-top:2px;white-space:pre-wrap;'>{body}</div></div>"
        self.chat_view.append(block)
        self.chat_view.verticalScrollBar().setValue(self.chat_view.verticalScrollBar().maximum())

    def send_message(self, display_text, payload_text=""):
        text = (display_text or "").strip()
        if not text:
            return
        url = self.app.normalize_api_url(self.app.settings.get('api_url', ''))
        key = self.app.settings.get('api_key', '')
        model = self.app.get_high_model_name() or self.app.get_mid_model_name()
        if not url or not key or not model:
            self.append_message("assistant", "AI 配置不完整：请先在设置中配置 API URL、API Key 和模型名。")
            return
        self.input_edit.clear()
        self.append_message("user", text)
        payload = (payload_text or text).strip()
        self.messages.append({"role": "user", "content": payload})
        self.send_btn.setEnabled(False)
        snapshot = list(self.messages)
        threading.Thread(target=self._chat_worker, args=(url, key, model, snapshot), daemon=True).start()

    def on_send_clicked(self):
        text = self.input_edit.toPlainText().strip()
        self.send_message(text, payload_text=text)

    def _chat_worker(self, url, key, model, messages):
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "stream": False
        }
        try:
            data = json.dumps(payload).encode("utf-8")
            req = request.Request(url, data=data, headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}"
            }, method="POST")
            with request.urlopen(req, timeout=60) as resp:
                resp_text = resp.read().decode("utf-8", errors="ignore")
                answer = (self.app.extract_text_from_response(resp_text) or "").strip()
                if not answer:
                    answer = "模型未返回内容"
                self.chat_result_ready.emit({"ok": True, "text": answer})
        except error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8", errors="ignore")
            except Exception:
                err_body = ""
            self.chat_result_ready.emit({"ok": False, "text": f"请求失败：HTTP {e.code} {e.reason}\n{err_body}"})
        except Exception as e:
            self.chat_result_ready.emit({"ok": False, "text": f"请求失败：{str(e)}"})

    def on_chat_result(self, result):
        answer = (result or {}).get("text", "")
        self.append_message("assistant", answer)
        self.messages.append({"role": "assistant", "content": answer})
        self.send_btn.setEnabled(True)
        self.switch_input_to_edit()


class AIAssistantMixin:
    def setup_ai_chat_shortcuts(self):
        self.ai_chat_shortcut = QShortcut(QKeySequence('Ctrl+U'), self)
        self.ai_chat_shortcut.activated.connect(self.open_ai_chat_window)

    def open_ai_chat_window(self, initial_prompt="", initial_payload="", title="AI 小助手"):
        dlg = AIChatWindow(self, initial_prompt=initial_prompt, initial_payload=initial_payload, title=title)
        self.ai_chat_windows.append(dlg)
        dlg.destroyed.connect(lambda: self._cleanup_ai_chat_windows())
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _cleanup_ai_chat_windows(self):
        self.ai_chat_windows = [w for w in self.ai_chat_windows if w is not None and w.isVisible()]

    def install_ai_selection_context_menu(self, text_widget, source_name):
        text_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        text_widget.customContextMenuRequested.connect(
            lambda pos, w=text_widget, s=source_name: self._show_ai_selection_context_menu(w, pos, s)
        )

    def _show_ai_selection_context_menu(self, text_widget, pos, source_name):
        menu = text_widget.createStandardContextMenu()
        menu.addSeparator()
        ask_action = menu.addAction("根据上下文语境询问框选内容")
        ask_action.triggered.connect(lambda: self.ask_ai_for_selected_text(text_widget, source_name))
        menu.exec(text_widget.mapToGlobal(pos))
        menu.deleteLater()

    def ask_ai_for_selected_text(self, text_widget, source_name):
        cursor = text_widget.textCursor()
        selected_text = (cursor.selectedText() or "").replace("\u2029", "\n").strip()
        if not selected_text:
            QMessageBox.information(self, "提示", "请先框选要提问的内容。")
            return
        selected_text_for_ai = self.normalize_blank_lines_to_space(selected_text)
        context_text = self.build_selection_context(text_widget, selected_text_for_ai)
        page_kind = self.current_page_kind or "unknown"
        query = self.current_query or ""
        visible_prompt = (
            f"请解释我在“{source_name}”中框选的内容，并结合当前查询给出学习建议。\n"
            f"当前查询：{query}\n"
            f"框选内容：{selected_text}"
        )
        payload_prompt = (
            "请基于给定上下文解释被框选内容，并给出学习建议。\n"
            f"来源区域：{source_name}\n"
            f"当前页面类型：{page_kind}\n"
            f"当前查询：{query}\n"
            f"上下文：\n{context_text}\n\n"
            f"框选内容：{selected_text_for_ai}\n\n"
            "回答要求：先解释含义，再说明在此语境下的作用，最后给1-2条学习建议。"
        )
        self.open_ai_chat_window(initial_prompt=visible_prompt, initial_payload=payload_prompt, title=f"AI 语境提问 - {source_name}")

    def build_selection_context(self, text_widget, selected_text):
        raw_text = ""
        if hasattr(text_widget, "toPlainText"):
            raw_text = text_widget.toPlainText() or ""
        raw_lines = raw_text.splitlines()
        normalized_lines = [(line if line.strip() else " ") for line in raw_lines]
        selected_norm = (selected_text or "").replace("\u2029", "\n")
        selected_lines = [line.strip() for line in selected_norm.splitlines() if line.strip()]
        anchor = selected_lines[0] if selected_lines else selected_norm.strip()
        center = -1
        for idx, line in enumerate(raw_lines):
            if anchor and anchor in line:
                center = idx
                break
        if center < 0:
            center = max(0, len(raw_lines) // 2)
        left = max(0, center - 3)
        right = min(len(normalized_lines) - 1, center + 3) if normalized_lines else -1
        if right < left:
            return (selected_norm if selected_norm else " ").replace("\n\n", "\n \n")
        def context_metrics(text):
            chars = len([ch for ch in text if not ch.isspace()])
            words = len(re.findall(r"[A-Za-z0-9_']+", text))
            return chars, words
        context_lines = normalized_lines[left:right + 1]
        context_text = "\n".join(context_lines)
        chars, words = context_metrics(context_text)
        while (chars < 50 and words < 50) and (left > 0 or right < len(normalized_lines) - 1):
            if left > 0:
                left -= 1
            if right < len(normalized_lines) - 1:
                right += 1
            context_lines = normalized_lines[left:right + 1]
            context_text = "\n".join(context_lines)
            chars, words = context_metrics(context_text)
            if right - left >= 120:
                break
        return self.normalize_blank_lines_to_space(context_text)

    def normalize_blank_lines_to_space(self, text):
        lines = (text or "").splitlines()
        fixed = [line if line.strip() else " " for line in lines]
        return "\n".join(fixed).strip()

    def on_ai_smart_favorite_clicked(self):
        if not self.current_query:
            return
        cur = self.user_conn.cursor()
        cur.execute('SELECT id, name FROM folders ORDER BY id')
        folders = cur.fetchall()
        if not folders:
            self.toggle_favorite_current()
            return
        folder_names = [name for _, name in folders]
        url = self.normalize_api_url(self.settings.get('api_url', ''))
        key = self.settings.get('api_key', '')
        model = self.get_mid_model_name() or self.get_high_model_name()
        if not url or not key or not model:
            self.toggle_favorite_current()
            return
        prompt = (
            "你是英语学习助手。请根据给定词条，在候选收藏夹中选择最合适的 1-3 个。"
            "只输出 JSON，不要输出任何其他文本。"
            "格式：{\"folders\":[\"收藏夹1\",\"收藏夹2\"]}。\n"
            f"词条：{self.current_query}\n"
            f"候选收藏夹：{', '.join(folder_names)}"
        )
        if self.favorite_option_btn is not None:
            self.favorite_option_btn.setEnabled(False)
        threading.Thread(
            target=self._ai_smart_favorite_worker,
            args=(url, key, model, self.current_query, folders, prompt),
            daemon=True,
        ).start()

    def _ai_smart_favorite_worker(self, url, key, model, query, folders, prompt):
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a strict JSON generator."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "stream": False
        }
        try:
            data = json.dumps(payload).encode("utf-8")
            req = request.Request(url, data=data, headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}"
            }, method="POST")
            with request.urlopen(req, timeout=60) as resp:
                resp_text = resp.read().decode("utf-8", errors="ignore")
                text = (self.extract_text_from_response(resp_text) or "").strip()
                names = self.extract_folder_names_from_ai_result(text, [name for _, name in folders])
                self.smart_favorite_ready.emit({"ok": True, "query": query, "names": names})
        except Exception as e:
            self.smart_favorite_ready.emit({"ok": False, "error": str(e), "query": query})

    def extract_folder_names_from_ai_result(self, text, candidates):
        raw = (text or "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
            raw = re.sub(r"\s*```$", "", raw)
        names = []
        try:
            obj = json.loads(raw)
            arr = obj.get("folders", [])
            if isinstance(arr, list):
                names = [str(x).strip() for x in arr if str(x).strip()]
        except Exception:
            pass
        lower_map = {name.lower(): name for name in candidates}
        valid = []
        seen = set()
        for n in names:
            key = n.lower()
            if key in lower_map and key not in seen:
                valid.append(lower_map[key])
                seen.add(key)
        if valid:
            return valid[:3]
        fallback = []
        for cand in candidates:
            if cand and cand in raw and cand.lower() not in seen:
                fallback.append(cand)
                seen.add(cand.lower())
        return fallback[:3]

    def on_ai_smart_favorite_result(self, result):
        if self.favorite_option_btn is not None:
            self.favorite_option_btn.setEnabled(True)
        if not result or not result.get("ok"):
            err = (result or {}).get("error", "未知错误")
            QMessageBox.warning(self, "AI 收藏失败", f"AI 推荐收藏夹失败：{err}")
            return
        if (result.get("query") or "") != (self.current_query or ""):
            return
        names = result.get("names", [])
        if not names:
            QMessageBox.information(self, "AI 收藏结果", "AI 未匹配到合适收藏夹，已保持当前收藏状态不变。")
            return
        cur = self.user_conn.cursor()
        placeholders = ",".join(["?"] * len(names))
        cur.execute(f"SELECT id, name FROM folders WHERE name IN ({placeholders})", tuple(names))
        folder_rows = cur.fetchall()
        if not folder_rows:
            QMessageBox.information(self, "AI 收藏结果", "AI 返回的收藏夹未命中本地目录。")
            return
        ts = datetime.now().isoformat(timespec='seconds')
        added = 0
        for folder_id, _ in folder_rows:
            cur.execute('INSERT OR IGNORE INTO favorites(query, folder_id, created_at) VALUES(?, ?, ?)', (self.current_query, int(folder_id), ts))
            if cur.rowcount > 0:
                added += 1
        self.user_conn.commit()
        self.load_favorites_list()
        self.update_favorite_button_state(self.current_query)
        names_text = "、".join([name for _, name in folder_rows])
        QMessageBox.information(self, "AI 收藏结果", f"已处理收藏夹：{names_text}\n新增收藏：{added}")

    def on_ai_suggest_links_clicked(self):
        current_word = self.lookup_dictionary_word_exact(self.current_query)
        if not current_word:
            QMessageBox.warning(self, "推荐失败", "当前词条不在词库中。")
            return
        url = self.normalize_api_url(self.settings.get('api_url', ''))
        key = self.settings.get('api_key', '')
        model = self.get_mid_model_name() or self.get_high_model_name()
        if not url or not key or not model:
            QMessageBox.warning(self, "推荐失败", "请先在设置中配置 API URL、API Key 和模型。")
            return
        prompt = (
            "你是英语学习助手。请根据给定单词输出最相关的英文关联词。"
            "只输出 JSON，不要额外文本。"
            "JSON 格式：{\"words\":[\"word1\",\"word2\",...]}"
            "要求：6-12 个词，全部英文小写，不能包含原词，不能包含短语。\n"
            f"原词：{current_word}"
        )
        self.ai_link_suggest_btn.setEnabled(False)
        threading.Thread(target=self._ai_suggest_links_worker, args=(url, key, model, current_word, prompt), daemon=True).start()

    def _ai_suggest_links_worker(self, url, key, model, current_word, prompt):
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a strict JSON generator."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2,
            "stream": False
        }
        try:
            data = json.dumps(payload).encode("utf-8")
            req = request.Request(url, data=data, headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}"
            }, method="POST")
            with request.urlopen(req, timeout=60) as resp:
                resp_text = resp.read().decode("utf-8", errors="ignore")
                text = (self.extract_text_from_response(resp_text) or "").strip()
                words = self.extract_words_from_ai_result(text)
                self.ai_links_ready.emit({"ok": True, "words": words, "current_word": current_word})
        except Exception as e:
            self.ai_links_ready.emit({"ok": False, "error": str(e), "current_word": current_word})

    def on_ai_links_result(self, result):
        if self.ai_link_suggest_btn is not None:
            self.ai_link_suggest_btn.setEnabled(True)
        if not result or not result.get("ok"):
            err = (result or {}).get("error", "未知错误")
            QMessageBox.warning(self, "推荐失败", f"AI 推荐关联词失败：{err}")
            return
        current_word = result.get("current_word", "")
        suggestions = result.get("words", [])
        valid = []
        for token in suggestions:
            found = self.lookup_dictionary_word_exact(token)
            if not found:
                continue
            if found.lower() == current_word.lower():
                continue
            if found.lower() not in [x.lower() for x in valid]:
                valid.append(found)
        if not valid:
            QMessageBox.information(self, "推荐结果", "未找到可添加的关联词（可能不在词库里）。")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("确认添加关联词")
        layout = QVBoxLayout()
        tip = QLabel(f"原词：{current_word}\n请选择要添加的关联词：")
        layout.addWidget(tip)
        list_widget = QListWidget()
        for w in valid:
            item = QListWidgetItem(w)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            list_widget.addItem(item)
        layout.addWidget(list_widget)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        dlg.setLayout(layout)
        if dlg.exec():
            added = 0
            for i in range(list_widget.count()):
                item = list_widget.item(i)
                if item.checkState() == Qt.CheckState.Checked:
                    self.add_word_link(current_word, item.text())
                    added += 1
            self.refresh_words_link_view(current_word)
            QMessageBox.information(self, "已完成", f"已添加 {added} 个关联词。")

    def add_ai_section(self):
        ai_title = QLabel("AI 服务")
        ai_title.setFont(ai_title.font())
        ai_title.setStyleSheet('color: #61dafb; margin-top: 15px; margin-bottom: 5px;')
        self.detail_layout.addWidget(ai_title)
        self.ai_options_list = QListWidget()
        self.ai_options_list.setFixedHeight(180)
        for t in ["自然解释", "相关短语列举", "固定搭配列举", "词汇变形", "英语语境词语用法", "例句用法", "AI助记", "找近义词", "找反义词"]:
            item = QListWidgetItem(t)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.ai_options_list.addItem(item)
        self.detail_layout.addWidget(self.ai_options_list)
        self.ai_free_input = QLineEdit()
        self.ai_free_input.setPlaceholderText("自由提问（可选）")
        self.detail_layout.addWidget(self.ai_free_input)
        self.ai_generate_btn = QPushButton("让 AI 生成")
        self.ai_generate_btn.clicked.connect(self.on_ai_generate_clicked)
        self.detail_layout.addWidget(self.ai_generate_btn)
        self.apply_styles()

    def on_ai_generate_clicked(self):
        if not self.current_query:
            return
        selections = []
        for i in range(self.ai_options_list.count()):
            it = self.ai_options_list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                selections.append(it.text())
        free_q = self.ai_free_input.text().strip()
        url = self.normalize_api_url(self.settings.get('api_url', ''))
        key = self.settings.get('api_key', '')
        model = self.get_high_model_name()
        if not url or not key or not model:
            self.append_ai_to_note_bottom("\n\nAI 配置不完整：请先在设置中配置 API URL、API Key 和模型名\n")
            return
        prompt = self.build_ai_prompt(self.current_query, selections, free_q)
        self.ai_generate_btn.setEnabled(False)
        threading.Thread(target=self._ai_request_worker, args=(url, key, model, prompt), daemon=True).start()

    def build_ai_prompt(self, query, selections, free_q):
        parts = []
        parts.append("你是英语学习助手。输出必须直接、准确、可执行，不要寒暄。")
        parts.append("总要求：中文说明为主；必要时给英文例子+中译；避免空泛描述。")
        if selections:
            parts.append("请严格按选中任务逐项输出，每项单独成段：")
            for s in selections:
                parts.append(f"- {s}：{self.get_ai_option_instruction(s)}")
        else:
            parts.append(f"- 自然解释：{self.get_ai_option_instruction('自然解释')}")
        if free_q:
            parts.append(f"自由提问：{free_q}")
        parts.append(f"目标词/句：{query}")
        parts.append("输出约束：每段尽量短，信息完整，不重复。")
        return "\n".join(parts)

    def get_ai_option_instruction(self, option):
        instructions = {
            "自然解释": "先给核心含义，再给常见语气/使用场景，最后给1条最自然的英文例句和中文翻译。",
            "相关短语列举": "列出4-8个高频相关短语，每个短语给中文义和1个简短例句。",
            "固定搭配列举": "列出最常用固定搭配（动词/介词/名词搭配），按“搭配+中文义+例句”格式输出。",
            "词汇变形": "给出词性与常见变形（时态、复数、比较级等），并说明每种变形最常见用法。",
            "英语语境词语用法": "分别给口语、书面语、考试/商务场景下的用法差异，并给对应例句。",
            "例句用法": "给5条从易到难的实用例句，覆盖不同句型，每句附中文翻译。",
            "AI助记": "给2-3种记忆法（词根/联想/场景记忆），并给一个可复述的记忆口诀。",
            "找近义词": "列出5-8个近义词，说明语义强弱和语境差别，并各给一个最短对比例句。",
            "找反义词": "列出3-6个反义词，说明反义关系类型（程度/方向/态度），并各给例句。"
        }
        return instructions.get(option, "围绕该任务给出简明、实用、可直接学习的答案。")

    def _ai_request_worker(self, url, key, model, prompt):
        try:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a helpful English learning assistant for Chinese users."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.2,
                "stream": True
            }
            data = json.dumps(payload).encode("utf-8")
            req = request.Request(url, data=data, headers={
                "Accept": "text/event-stream",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}"
            }, method="POST")
            with request.urlopen(req, timeout=60) as resp:
                content_type = (resp.headers.get("Content-Type", "") or "").lower()
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
                        if piece:
                            self.ai_chunk_ready.emit(piece)
                else:
                    resp_text = resp.read().decode("utf-8", errors="ignore")
                    self.ai_chunk_ready.emit(self.extract_text_from_response(resp_text))
        except error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8", errors="ignore")
            except Exception:
                err_body = ""
            self.ai_chunk_ready.emit(f"\n请求失败：HTTP {e.code} {e.reason}\n{err_body}\n")
        except Exception as e:
            self.ai_chunk_ready.emit(f"\n请求失败：{str(e)}\n")
        self.ai_done.emit()

    def append_ai_to_note_bottom(self, text):
        if not hasattr(self, 'note_edit'):
            return
        current = self.note_edit.toPlainText()
        if current:
            self.note_edit.setPlainText(current + text)
        else:
            self.note_edit.setPlainText(text.lstrip("\n"))
        self.update_note_preview()
        self.note_edit.verticalScrollBar().setValue(self.note_edit.verticalScrollBar().maximum())

    def _append_ai_chunk_to_note(self, chunk):
        self.append_ai_to_note_bottom(chunk)

    def _finish_ai_generation(self):
        if hasattr(self, 'ai_generate_btn'):
            self.ai_generate_btn.setEnabled(True)
