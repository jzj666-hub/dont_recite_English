from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QFont, QGuiApplication
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QWidget,
)


class NavigationMixin:
    def on_search_text_changed(self, text):
        if not text:
            self.candidates_list.clear()
            self.current_search_text = ""
            self.all_candidates = []
            self.loaded_count = 0
            return
        self.current_search_text = text
        if self.contains_chinese(text):
            self.all_candidates = self.search_semantic_candidates(text)
        else:
            self.cursor.execute(
                """
                SELECT word
                FROM stardict
                WHERE word LIKE ? COLLATE NOCASE
                ORDER BY
                    CASE
                        WHEN INSTR(word, ' ') = 0 AND TRIM(COALESCE(definition, '')) <> '' THEN 0
                        WHEN INSTR(word, ' ') > 0 THEN 1
                        ELSE 2
                    END,
                    LENGTH(word),
                    LOWER(word)
                LIMIT 800
                """,
                (f"{text}%",)
            )
            candidates = self.cursor.fetchall()
            self.all_candidates = [candidate[0] for candidate in candidates]
        self.loaded_count = 0
        self.candidates_list.clear()
        self.load_more_candidates(20)

    def search_semantic_candidates(self, text):
        query = text.strip()
        query_vec = self.vectorize_chinese_text(query)
        cur = self.cursor
        cur.execute(
            "SELECT word, translation, detail, definition FROM stardict WHERE translation LIKE ? OR detail LIKE ? LIMIT 2500",
            (f"%{query}%", f"%{query}%")
        )
        rows = cur.fetchall()
        if len(rows) < 80:
            tokens = [ch for ch in query if '\u4e00' <= ch <= '\u9fff']
            extra = []
            for tk in list(dict.fromkeys(tokens))[:3]:
                cur.execute(
                    "SELECT word, translation, detail, definition FROM stardict WHERE translation LIKE ? OR detail LIKE ? LIMIT 1200",
                    (f"%{tk}%", f"%{tk}%")
                )
                extra.extend(cur.fetchall())
            rows.extend(extra)
        merged = {}
        for w, tr, dt, de in rows:
            if w not in merged:
                merged[w] = {
                    "zh": f"{tr or ''} {dt or ''}",
                    "has_def": bool((de or '').strip()),
                    "has_space": " " in (w or ""),
                }
        scored = []
        for w, meta in merged.items():
            zh_text = meta["zh"]
            v = self.vectorize_chinese_text(zh_text)
            score = self.cosine_similarity(query_vec, v)
            if query and query in zh_text:
                score += 0.25
            if score > 0:
                if (not meta["has_space"]) and meta["has_def"]:
                    grp = 0
                elif meta["has_space"]:
                    grp = 1
                else:
                    grp = 2
                scored.append((grp, -score, w.lower(), w))
        scored.sort()
        return [w for _, __, ___, w in scored[:500]]

    def load_more_candidates(self, count):
        start = self.loaded_count
        end = min(start + count, len(self.all_candidates))
        for i in range(start, end):
            word = self.all_candidates[i]
            item = QListWidgetItem(word)
            item.setData(Qt.ItemDataRole.UserRole, word)
            self.apply_review_style_to_item(item, word)
            self.candidates_list.addItem(item)
        self.loaded_count = end

    def on_scroll_changed(self, value):
        scroll_bar = self.candidates_list.verticalScrollBar()
        if value >= scroll_bar.maximum() - 10 and self.loaded_count < len(self.all_candidates):
            self.load_more_candidates(5)

    def on_candidate_activated(self, item):
        self.navigate_to_word(item.text())

    def on_search_key_press(self, event):
        if event.key() == Qt.Key.Key_Down:
            if self.candidates_list.count() > 0:
                self.candidates_list.setFocus()
                if self.candidates_list.currentRow() == -1:
                    self.candidates_list.setCurrentRow(0)
                else:
                    self.candidates_list.setCurrentRow(min(self.candidates_list.currentRow() + 1, self.candidates_list.count() - 1))
        elif event.key() == Qt.Key.Key_Up:
            if self.candidates_list.count() > 0:
                self.candidates_list.setFocus()
                if self.candidates_list.currentRow() <= 0:
                    self.search_input.setFocus()
                else:
                    self.candidates_list.setCurrentRow(self.candidates_list.currentRow() - 1)
        elif event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            if self.candidates_list.currentRow() >= 0:
                item = self.candidates_list.currentItem()
                if item:
                    self.navigate_to_word(item.text())
            else:
                self.on_enter_pressed()
        else:
            QLineEdit.keyPressEvent(self.search_input, event)

    def copy_current_list_item(self, list_widget):
        item = list_widget.currentItem()
        if item:
            q = item.data(Qt.ItemDataRole.UserRole)
            QGuiApplication.clipboard().setText(q if q else item.text())

    def on_candidates_key_press(self, event):
        if event.key() == Qt.Key.Key_Up:
            if self.candidates_list.currentRow() <= 0:
                self.search_input.setFocus()
            else:
                self.candidates_list.setCurrentRow(self.candidates_list.currentRow() - 1)
        elif event.key() == Qt.Key.Key_Down:
            self.candidates_list.setCurrentRow(min(self.candidates_list.currentRow() + 1, self.candidates_list.count() - 1))
        elif event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            item = self.candidates_list.currentItem()
            if item:
                self.navigate_to_word(item.text())
        else:
            QListWidget.keyPressEvent(self.candidates_list, event)

    def on_candidate_clicked(self, item):
        self.navigate_to_word(item.text())

    def on_enter_pressed(self):
        text = self.search_input.text().strip()
        if not text:
            return
        unique_word = self.find_unique_dictionary_word(text)
        if unique_word:
            self.navigate_to_word(unique_word)
            return
        if self.is_english_text(text):
            self.current_page_kind = 'sentence'
            self.translate_text(text)
            return
        self.clear_detail()
        error_label = QLabel("未找到唯一匹配词条，且当前输入不是英文句子，未触发离线翻译。")
        error_label.setFont(QFont('Segoe UI', 12))
        error_label.setStyleSheet('color: #e06c75;')
        self.detail_layout.addWidget(error_label)

    def has_query_page(self):
        return bool(self.current_query) and self.detail_layout.count() > 0

    def capture_current_page_state(self):
        if not self.has_query_page():
            return None
        note_text = ""
        if hasattr(self, 'note_edit'):
            note_text = self.note_edit.toPlainText()
        llm_visible = False
        llm_html = ""
        if getattr(self, 'llm_translation_widgets', None):
            if len(self.llm_translation_widgets) >= 2 and self.llm_translation_widgets[1] is not None:
                llm_visible = self.llm_translation_widgets[1].isVisible()
                llm_html = self.llm_translation_widgets[1].toHtml()
        return {
            "kind": self.current_page_kind,
            "query": self.current_query,
            "note_text": note_text,
            "llm_visible": llm_visible,
            "llm_html": llm_html,
            "llm_click_count": self.llm_translate_click_count,
            "scroll_value": self.detail_area.verticalScrollBar().value(),
            "search_text": self.search_input.text(),
        }

    def restore_page_state(self, state):
        if not state:
            return
        kind = state.get("kind", "")
        query = state.get("query", "")
        if kind == 'word':
            self.current_page_kind = 'word'
            self.show_word_detail(query)
        elif kind == 'sentence':
            self.current_page_kind = 'sentence'
            self.translate_text(query)
        else:
            return
        if hasattr(self, 'note_edit'):
            self.note_edit.setPlainText(state.get("note_text", ""))
            self.update_note_preview()
        if state.get("llm_visible"):
            self.show_llm_translation_in_place(state.get("llm_html", ""))
        self.llm_translate_click_count = int(state.get("llm_click_count", 0))
        self.search_input.setText(state.get("search_text", query))
        self.detail_area.verticalScrollBar().setValue(int(state.get("scroll_value", 0)))

    def navigate_to_word(self, word):
        target = (word or "").strip()
        if not target:
            return
        if self.has_query_page():
            same = self.current_page_kind == 'word' and (self.current_query or "").lower() == target.lower()
            if not same:
                state = self.capture_current_page_state()
                if state:
                    self.query_page_stack.append(state)
        self.current_page_kind = 'word'
        self.show_word_detail(target)

    def add_back_stack_button(self, header_layout):
        if not self.query_page_stack:
            return
        back_btn = QPushButton("返回上一个查询")
        back_btn.setFixedHeight(32)
        back_btn.clicked.connect(self.go_back_in_query_stack)
        header_layout.addWidget(back_btn)

    def go_back_in_query_stack(self):
        if not self.query_page_stack:
            return
        prev_state = self.query_page_stack.pop()
        self.restore_page_state(prev_state)

    def find_unique_dictionary_word(self, text):
        cur = self.cursor
        cur.execute("SELECT word FROM stardict WHERE word = ? COLLATE NOCASE LIMIT 2", (text,))
        rows = cur.fetchall()
        if len(rows) == 1:
            return rows[0][0]
        cur.execute("SELECT word FROM stardict WHERE word LIKE ? COLLATE NOCASE LIMIT 2", (f"{text}%",))
        rows = cur.fetchall()
        if len(rows) == 1:
            return rows[0][0]
        return None

    def show_word_detail(self, word):
        self.current_page_kind = 'word'
        self.cursor.execute("SELECT * FROM stardict WHERE word = ? COLLATE NOCASE", (word,))
        result = self.cursor.fetchone()
        if not result:
            return
        self.clear_detail()
        self.current_query = word
        self.increment_query_count(self.current_query)
        if self.is_in_review(self.current_query):
            self.touch_reviewing_word(self.current_query)
        word_data = {
            'word': result[1], 'sw': result[2], 'phonetic': result[3], 'definition': result[4], 'translation': result[5],
            'pos': result[6], 'collins': result[7], 'oxford': result[8], 'tag': result[9], 'bnc': result[10], 'frq': result[11],
            'exchange': result[12], 'detail': result[13], 'audio': result[14] if len(result) > 14 else None,
        }
        header_widget = QWidget()
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_widget.setLayout(header_layout)
        word_label = QLabel(word_data['word'])
        word_label.setFont(QFont('Segoe UI', 28, QFont.Weight.Bold))
        word_label.setStyleSheet('color: #61dafb; margin-bottom: 10px;')
        word_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        header_layout.addWidget(word_label)
        header_layout.addStretch()
        self.favorite_button = QPushButton()
        self.favorite_button.setFixedHeight(32)
        self.favorite_button.clicked.connect(self.toggle_favorite_current)
        header_layout.addWidget(self.favorite_button)
        self.favorite_option_btn = self.build_favorite_option_button()
        header_layout.addWidget(self.favorite_option_btn)
        self.review_button = QPushButton()
        self.review_button.setFixedHeight(32)
        self.review_button.clicked.connect(self.toggle_review_current)
        header_layout.addWidget(self.review_button)
        self.llm_translate_btn = QPushButton("对翻译不满意？试试LLM翻译？")
        self.llm_translate_btn.setFixedHeight(32)
        self.llm_translate_btn.clicked.connect(self.on_llm_translate_clicked)
        header_layout.addWidget(self.llm_translate_btn)
        self.add_back_stack_button(header_layout)
        self.detail_layout.addWidget(header_widget)
        self.update_favorite_button_state(self.current_query)
        self.update_review_button_state(self.current_query)
        self.current_word_label = word_label
        self.current_word_label_base_text = word_data['word']
        self.current_source_text_label = None
        self.update_current_query_visuals()
        if word_data['phonetic']:
            phonetic_label = QLabel(f"发音: [{word_data['phonetic']}]")
            phonetic_label.setFont(QFont('Consolas', 14))
            phonetic_label.setStyleSheet('color: #98c379; margin-bottom: 10px;')
            phonetic_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            self.detail_layout.addWidget(phonetic_label)
        if word_data['pos']:
            pos_label = QLabel(f"词性: {word_data['pos']}")
            pos_label.setFont(QFont('Segoe UI', 12))
            pos_label.setStyleSheet('color: #e06c75; margin-bottom: 5px;')
            pos_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            self.detail_layout.addWidget(pos_label)
        self.translation_primary_widgets = []
        if word_data['translation']:
            trans_label = QLabel(f"中文释义: {word_data['translation']}")
            trans_label.setFont(QFont('Segoe UI', 14))
            trans_label.setStyleSheet('margin-bottom: 10px;')
            trans_label.setWordWrap(True)
            trans_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            self.detail_layout.addWidget(trans_label)
            self.translation_primary_widgets = [trans_label]
        self.build_llm_translation_area()
        if word_data['definition']:
            def_label = QLabel(f"英文释义: {word_data['definition']}")
            def_label.setFont(QFont('Segoe UI', 12))
            def_label.setStyleSheet('color: #d19a66; margin-bottom: 10px;')
            def_label.setWordWrap(True)
            def_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            self.detail_layout.addWidget(def_label)
        if word_data['detail']:
            detail_label = QLabel(f"详细解释:\n{word_data['detail']}")
            detail_label.setFont(QFont('Segoe UI', 11))
            detail_label.setStyleSheet('color: #abb2bf; margin-bottom: 10px;')
            detail_label.setWordWrap(True)
            detail_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            self.detail_layout.addWidget(detail_label)
        if word_data['exchange']:
            exchange_label = QLabel(f"词形变化: {word_data['exchange']}")
            exchange_label.setFont(QFont('Segoe UI', 11))
            exchange_label.setStyleSheet('color: #56b6c2; margin-bottom: 10px;')
            exchange_label.setWordWrap(True)
            exchange_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            self.detail_layout.addWidget(exchange_label)
        meta_parts = []
        if word_data['collins']:
            meta_parts.append(f"柯林斯星级: {word_data['collins']}")
        if word_data['oxford']:
            meta_parts.append("牛津收录")
        if word_data['tag']:
            meta_parts.append(str(word_data['tag']))
        if word_data['bnc']:
            meta_parts.append(f"BNC: {word_data['bnc']}")
        if word_data['frq']:
            meta_parts.append(f"语料频次: {word_data['frq']}")
        if word_data.get('sw') and word_data.get('sw') != word_data['word']:
            meta_parts.append(f"词干: {word_data['sw']}")
        if meta_parts:
            tag_label = QLabel(" | ".join(meta_parts))
            tag_label.setFont(QFont('Segoe UI', 10))
            tag_label.setStyleSheet('color: #c678dd; margin-top: 10px;')
            tag_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            self.detail_layout.addWidget(tag_label)
        if word_data.get('audio'):
            audio_label = QLabel(f"音频: {word_data['audio']}")
            audio_label.setFont(QFont('Consolas', 10))
            audio_label.setStyleSheet('color: #bbbbbb; margin-top: 6px;')
            audio_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            self.detail_layout.addWidget(audio_label)
        self.build_words_link_section(word_data['word'])
        self.prepare_llm_translate_context(word_data['word'], True, 'word')
        self.build_note_section()
        save_note_btn = QPushButton("保存批注")
        save_note_btn.clicked.connect(self.save_current_note)
        self.detail_layout.addWidget(save_note_btn)
        self.add_ai_section()
        self.detail_layout.addStretch()
        self.update_current_query_visuals()

    def translate_text(self, text):
        self.current_page_kind = 'sentence'
        self.clear_detail()
        self.current_query = text
        self.increment_query_count(self.current_query)
        if self.is_in_review(self.current_query):
            self.touch_reviewing_word(self.current_query)
        try:
            if self.translator is None:
                raise Exception("未检测到可用的 Argos 英译中离线模型")
            translated = self.translator.translate(text)
            if not translated:
                raise Exception("Argos 未返回翻译结果")
            header_widget = QWidget()
            header_layout = QHBoxLayout()
            header_layout.setContentsMargins(0, 0, 0, 0)
            header_widget.setLayout(header_layout)
            header_title = QLabel("查询")
            header_title.setFont(QFont('Segoe UI', 16, QFont.Weight.Bold))
            header_title.setStyleSheet('color: #61dafb;')
            header_layout.addWidget(header_title)
            header_layout.addStretch()
            self.favorite_button = QPushButton()
            self.favorite_button.setFixedHeight(32)
            self.favorite_button.clicked.connect(self.toggle_favorite_current)
            header_layout.addWidget(self.favorite_button)
            self.favorite_option_btn = self.build_favorite_option_button()
            header_layout.addWidget(self.favorite_option_btn)
            self.review_button = QPushButton()
            self.review_button.setFixedHeight(32)
            self.review_button.clicked.connect(self.toggle_review_current)
            header_layout.addWidget(self.review_button)
            self.llm_translate_btn = QPushButton("对翻译不满意？试试LLM翻译？")
            self.llm_translate_btn.setFixedHeight(32)
            self.llm_translate_btn.clicked.connect(self.on_llm_translate_clicked)
            header_layout.addWidget(self.llm_translate_btn)
            self.add_back_stack_button(header_layout)
            self.detail_layout.addWidget(header_widget)
            self.update_favorite_button_state(self.current_query)
            self.update_review_button_state(self.current_query)
            source_label = QLabel("原文:")
            source_label.setFont(QFont('Segoe UI', 12, QFont.Weight.Bold))
            source_label.setStyleSheet('color: #61dafb; margin-bottom: 5px;')
            source_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            self.detail_layout.addWidget(source_label)
            source_text = QLabel(text)
            source_text.setFont(QFont('Segoe UI', 14))
            source_text.setStyleSheet('margin-bottom: 20px;')
            source_text.setWordWrap(True)
            source_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            self.detail_layout.addWidget(source_text)
            self.current_word_label = None
            self.current_word_label_base_text = ""
            self.current_source_text_label = source_text
            self.update_current_query_visuals()
            trans_label = QLabel("翻译:")
            trans_label.setFont(QFont('Segoe UI', 12, QFont.Weight.Bold))
            trans_label.setStyleSheet('color: #98c379; margin-bottom: 5px;')
            trans_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            self.detail_layout.addWidget(trans_label)
            self.translation_primary_widgets = []
            trans_text = QLabel(translated)
            trans_text.setFont(QFont('Segoe UI', 14))
            trans_text.setWordWrap(True)
            trans_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            self.detail_layout.addWidget(trans_text)
            self.translation_primary_widgets = [trans_text]
            self.build_llm_translation_area()
            self.prepare_llm_translate_context(text, False, 'sentence')
            self.build_note_section()
            save_note_btn = QPushButton("保存批注")
            save_note_btn.clicked.connect(self.save_current_note)
            self.detail_layout.addWidget(save_note_btn)
            self.add_ai_section()
            self.update_current_query_visuals()
        except Exception as e:
            error_label = QLabel(f"翻译失败: {str(e)}")
            error_label.setFont(QFont('Segoe UI', 12))
            error_label.setStyleSheet('color: #e06c75;')
            self.detail_layout.addWidget(error_label)
