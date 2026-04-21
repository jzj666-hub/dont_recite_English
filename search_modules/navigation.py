import re
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

from search_modules.tts_client import get_tts_client


class NavigationMixin:
    def mark_next_reviewing_touch_active(self):
        self._reviewing_active_touch_pending = True

    def consume_reviewing_touch_active(self):
        active = bool(getattr(self, "_reviewing_active_touch_pending", False))
        self._reviewing_active_touch_pending = False
        return active

    def on_search_text_changed(self, text):
        if not text:
            self.candidates_list.clear()
            self.current_search_text = ""
            self.all_candidates = []
            self.loaded_count = 0
            return
        self.current_search_text = text
        if self.contains_chinese(text):
            # 性能优化：中文输入时跳过实时的语义向量搜索，改在按下 Enter 后进行一次性更新
            self.all_candidates = []
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
        self.mark_next_reviewing_touch_active()
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
                    self.mark_next_reviewing_touch_active()
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
                self.mark_next_reviewing_touch_active()
                self.navigate_to_word(item.text())
        else:
            QListWidget.keyPressEvent(self.candidates_list, event)

    def on_candidate_clicked(self, item):
        self.mark_next_reviewing_touch_active()
        self.navigate_to_word(item.text())

    def on_enter_pressed(self):
        text = self.search_input.text().strip()
        if not text:
            return
        self.mark_next_reviewing_touch_active()
            
        # 只要包含中文（或中英混合），直接认定为需要「中译英」长句翻译
        if self.contains_chinese(text):
            # 在按下 Enter 时才触发耗时的语义搜索，更新候选词列表
            self.all_candidates = self.search_semantic_candidates(text)
            self.loaded_count = 0
            self.candidates_list.clear()
            self.load_more_candidates(20)

            self.current_page_kind = 'sentence'
            if hasattr(self, "animate_detail_change") and callable(getattr(self, "animate_detail_change")):
                self.animate_detail_change(lambda t=text: (self.clear_detail(), self.translate_text(t, skip_clear=True)))
            else:
                self.translate_text(text)
            return
            
        # 否则（全英文等情况），先尝试匹配离线词库的精确词条
        unique_word = self.find_unique_dictionary_word(text)
        if unique_word:
            self.navigate_to_word(unique_word)
            return
            
        # 英文词典中没找到对应词条，当作长句进行「英译中」处理
        if self.is_english_text(text):
            self.current_page_kind = 'sentence'
            if hasattr(self, "animate_detail_change") and callable(getattr(self, "animate_detail_change")):
                self.animate_detail_change(lambda t=text: (self.clear_detail(), self.translate_text(t, skip_clear=True)))
            else:
                self.translate_text(text)
            return
            
        self.clear_detail()
        error_label = QLabel("未找到唯一匹配词条，且当前输入不包含可翻译内容。")
        error_label.setFont(self.make_ui_font(12, False))
        error_label.setStyleSheet('color: #e06c75;')
        self.detail_info_layout.addWidget(error_label)

    def has_query_page(self):
        if not self.current_query:
            return False
        return self.detail_info_layout.count() > 0 or self.detail_note_layout.count() > 0 or self.detail_ai_layout.count() > 0

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
        current_scroll = 0
        if hasattr(self, 'detail_tab_widget'):
            current_tab = self.detail_tab_widget.currentIndex()
            if current_tab == 0 and hasattr(self, 'detail_info_tab') and hasattr(self.detail_info_tab, 'verticalScrollBar'):
                current_scroll = self.detail_info_tab.verticalScrollBar().value()
            elif current_tab == 1 and hasattr(self, 'detail_note_tab') and hasattr(self.detail_note_tab, 'verticalScrollBar'):
                current_scroll = self.detail_note_tab.verticalScrollBar().value()
            elif current_tab == 2 and hasattr(self, 'detail_ai_tab') and hasattr(self.detail_ai_tab, 'verticalScrollBar'):
                current_scroll = self.detail_ai_tab.verticalScrollBar().value()
        return {
            "kind": self.current_page_kind,
            "query": self.current_query,
            "note_text": note_text,
            "llm_visible": llm_visible,
            "llm_html": llm_html,
            "llm_click_count": self.llm_translate_click_count,
            "scroll_value": current_scroll,
            "current_tab": current_tab if hasattr(self, 'detail_tab_widget') else 0,
            "search_text": self.search_input.text(),
        }

    def restore_page_state(self, state):
        if not state:
            return
        kind = state.get("kind", "")
        query = state.get("query", "")
        def build():
            if kind == 'word':
                self.current_page_kind = 'word'
                self.clear_detail()
                self.show_word_detail(query, skip_clear=True)
            elif kind == 'sentence':
                self.current_page_kind = 'sentence'
                self.clear_detail()
                self.translate_text(query, skip_clear=True)
            else:
                return

        if hasattr(self, "animate_detail_change") and callable(getattr(self, "animate_detail_change")):
            self.animate_detail_change(build)
        else:
            build()
        if hasattr(self, 'note_edit'):
            self.note_edit.setPlainText(state.get("note_text", ""))
            self.update_note_preview()
        if state.get("llm_visible"):
            self.show_llm_translation_in_place(state.get("llm_html", ""))
        self.llm_translate_click_count = int(state.get("llm_click_count", 0))
        self.search_input.setText(state.get("search_text", query))
        if hasattr(self, 'detail_tab_widget'):
            self.detail_tab_widget.setCurrentIndex(int(state.get("current_tab", 0)))
            scroll_val = int(state.get("scroll_value", 0))
            current_tab = self.detail_tab_widget.currentIndex()
            if current_tab == 0 and hasattr(self, 'detail_info_tab') and hasattr(self.detail_info_tab, 'verticalScrollBar'):
                self.detail_info_tab.verticalScrollBar().setValue(scroll_val)
            elif current_tab == 1 and hasattr(self, 'detail_note_tab') and hasattr(self.detail_note_tab, 'verticalScrollBar'):
                self.detail_note_tab.verticalScrollBar().setValue(scroll_val)
            elif current_tab == 2 and hasattr(self, 'detail_ai_tab') and hasattr(self.detail_ai_tab, 'verticalScrollBar'):
                self.detail_ai_tab.verticalScrollBar().setValue(scroll_val)

    def navigate_to_word(self, word):
        target = (word or "").strip()
        if not target:
            return
        self.mark_next_reviewing_touch_active()
        if self.has_query_page():
            same = self.current_page_kind == 'word' and (self.current_query or "").lower() == target.lower()
            if not same:
                state = self.capture_current_page_state()
                if state:
                    self.query_page_stack.append(state)
        self.current_page_kind = 'word'
        if hasattr(self, "animate_detail_change") and callable(getattr(self, "animate_detail_change")):
            self.animate_detail_change(lambda w=target: (self.clear_detail(), self.show_word_detail(w, skip_clear=True)))
        else:
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
        # 1. 第一优先级：完全匹配大小写（使用 COLLATE BINARY 强制区分大小写）
        cur.execute("SELECT word FROM stardict WHERE word = ? COLLATE BINARY LIMIT 2", (text,))
        rows = cur.fetchall()
        if len(rows) == 1:
            return rows[0][0]
        
        # 2. 第二优先级：前缀匹配（暂不强制大小写匹配，但可随用户习惯优化）
        # 但既然用户要求“按下 Enter 不自动切换大小写”，我们应该只在非强制模式下使用 NOCASE。
        # 综合考虑，如果没有任何完全匹配，我们返回 None 触发后续逻辑（如句子翻译）
        return None

    def show_word_detail(self, word, *, skip_clear=False):
        self.current_page_kind = 'word'
        self.cursor.execute("SELECT * FROM stardict WHERE word = ? COLLATE NOCASE", (word,))
        result = self.cursor.fetchone()
        if not result:
            return
        if not skip_clear:
            self.clear_detail()
        self.current_query = word
        self.increment_query_count(self.current_query)
        active_touch = self.consume_reviewing_touch_active()
        if self.is_in_review(self.current_query):
            self.touch_reviewing_word(self.current_query, active=active_touch)
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
        word_label.setFont(self.make_ui_font(28, True))
        word_label.setStyleSheet('color: #61dafb; margin-bottom: 10px;')
        word_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        header_layout.addWidget(word_label)

        # TTS 按钮显示在单词右侧
        tts_btn = QPushButton("🔊")
        tts_btn.setFixedSize(36, 32)
        tts_btn.setToolTip("播放发音 (Edge-TTS)")
        tts_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        tts_btn.setStyleSheet("""
            QPushButton { 
                background: transparent; 
                border: 1px solid #3d3d3d; 
                border-radius: 6px; 
                font-size: 16px; 
                color: #61dafb;
                padding-bottom: 2px;
            }
            QPushButton:hover { 
                background: #3e3e42; 
                border-color: #61dafb; 
            }
        """)
        def play_word():
            text_to_play = word_data['word']
            is_cn = self.contains_chinese(text_to_play)
            if is_cn:
                voice = self.settings.get('tts_voice_cn', 'zh-CN-XiaoxiaoNeural')
                rate = self.settings.get('tts_rate_cn', '+0%')
            else:
                voice = self.settings.get('tts_voice', 'en-US-GuyNeural')
                rate = self.settings.get('tts_rate', '+0%')
            get_tts_client().play(text_to_play, voice=voice, rate=rate)
        tts_btn.clicked.connect(play_word)
        header_layout.addWidget(tts_btn)

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
        self.detail_info_layout.addWidget(header_widget)
        self.update_favorite_button_state(self.current_query)
        self.update_review_button_state(self.current_query)
        self.current_word_label = word_label
        self.current_word_label_base_text = word_data['word']
        self.current_source_text_label = None
        self.update_current_query_visuals()
        if word_data['phonetic']:
            phonetic_label = QLabel(f"发音: [{word_data['phonetic']}]")
            # 音标建议使用等宽字体系列，在 make_ui_font 中会自动处理 fallback
            phonetic_label.setFont(self.make_ui_font(14, False))
            phonetic_label.setStyleSheet('color: #98c379; margin-bottom: 10px;')
            phonetic_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            self.detail_info_layout.addWidget(phonetic_label)
        self.translation_primary_widgets = []
        if word_data['translation']:
            trans_label = QLabel(f"中文释义: {word_data['translation']}")
            trans_label.setFont(self.make_ui_font(14, False))
            trans_label.setStyleSheet('margin-bottom: 10px;')
            trans_label.setWordWrap(True)
            trans_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            self.detail_info_layout.addWidget(trans_label)
            self.translation_primary_widgets = [trans_label]
        self.build_llm_translation_area()
        if word_data['definition']:
            def_label = QLabel(f"英文释义: {word_data['definition']}")
            def_label.setFont(self.make_ui_font(12, False))
            def_label.setStyleSheet('color: #d19a66; margin-bottom: 10px;')
            def_label.setWordWrap(True)
            def_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            self.detail_info_layout.addWidget(def_label)
        if word_data['detail']:
            detail_label = QLabel(f"详细解释:\n{word_data['detail']}")
            detail_label.setFont(self.make_ui_font(11, False))
            detail_label.setStyleSheet('color: #abb2bf; margin-bottom: 10px;')
            detail_label.setWordWrap(True)
            detail_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            self.detail_info_layout.addWidget(detail_label)
        if word_data['exchange']:
            exchange_label = QLabel(f"词形变化: {word_data['exchange']}")
            exchange_label.setFont(self.make_ui_font(11, False))
            exchange_label.setStyleSheet('color: #56b6c2; margin-bottom: 10px;')
            exchange_label.setWordWrap(True)
            exchange_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            self.detail_info_layout.addWidget(exchange_label)
        
        # 标签展示区域 - 使用小方框样式
        tag_widget = QWidget()
        tag_layout = QHBoxLayout()
        tag_layout.setContentsMargins(0, 10, 0, 0)
        tag_layout.setSpacing(8)
        tag_widget.setLayout(tag_layout)
        
        # 标签映射：英文标签 -> (中文显示, 背景颜色)
        def make_tag(text, bg_color):
            tag_label = QLabel(text)
            tag_label.setFont(self.make_ui_font(11, False))
            tag_label.setStyleSheet(f'''
                background-color: {bg_color};
                color: #ffffff;
                padding: 4px 10px;
                border-radius: 4px;
                font-weight: 500;
            ''')
            tag_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            return tag_label
        
        if word_data['collins']:
            tag_layout.addWidget(make_tag(f"柯林斯 {word_data['collins']}", "#e06c75"))
        if word_data['oxford']:
            tag_layout.addWidget(make_tag("牛津词典", "#61dafb"))
        if word_data['tag']:
            tag_text = str(word_data['tag']).strip()
            # 处理多标签情况：用空格或逗号分割
            tags = re.split(r'[,，\s]+', tag_text)
            
            for tag in tags:
                tag = tag.strip()
                if not tag:
                    continue
                # 标签映射表
                tag_map = {
                    'CET4': ('英语四级', '#98c379'),
                    'CET6': ('英语六级', '#56b6c2'),
                    'KY': ('考研', '#d19a66'),
                    'TOEFL': ('托福', '#e5c07b'),
                    'IELTS': ('雅思', '#c678dd'),
                    'GRE': ('GRE', '#e06c75'),
                }
                if tag.upper() in tag_map:
                    chinese_name, color = tag_map[tag.upper()]
                    tag_layout.addWidget(make_tag(chinese_name, color))
                else:
                    tag_layout.addWidget(make_tag(tag.upper(), "#c678dd"))
        if word_data['bnc']:
            tag_layout.addWidget(make_tag(f"BNC {word_data['bnc']}", "#c678dd"))
        
        if tag_layout.count() > 0:
            self.detail_info_layout.addWidget(tag_widget)
        if word_data.get('audio'):
            audio_label = QLabel(f"音频: {word_data['audio']}")
            audio_label.setFont(self.make_ui_font(10, False))
            audio_label.setStyleSheet('color: #bbbbbb; margin-top: 6px;')
            audio_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            self.detail_info_layout.addWidget(audio_label)
        self.build_words_link_section(word_data['word'])
        self.prepare_llm_translate_context(word_data['word'], True, 'word', original_meaning=word_data.get('translation', ''))
        self.build_note_section()
        self.add_ai_section()
        self.update_current_query_visuals()

    def translate_text(self, text, *, skip_clear=False):
        self.current_page_kind = 'sentence'
        if not skip_clear:
            self.clear_detail()
        self.current_query = text
        self.increment_query_count(self.current_query)
        active_touch = self.consume_reviewing_touch_active()
        if self.is_in_review(self.current_query):
            self.touch_reviewing_word(self.current_query, active=active_touch)
        try:
            is_chinese = self.contains_chinese(text)
            active_translator = self.zh_en_translator if is_chinese else self.translator
            
            if active_translator is None:
                direction = "中译英" if is_chinese else "英译中"
                raise Exception(f"未检测到可用的 Argos {direction} 离线模型")
            
            translated = active_translator.translate(text)
            if not translated:
                raise Exception("Argos 未返回翻译结果")
            header_widget = QWidget()
            header_layout = QHBoxLayout()
            header_layout.setContentsMargins(0, 0, 0, 0)
            header_widget.setLayout(header_layout)
            header_title = QLabel("查询")
            header_title.setFont(self.make_ui_font(16, True))
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
            self.detail_info_layout.addWidget(header_widget)
            self.update_favorite_button_state(self.current_query)
            self.update_review_button_state(self.current_query)
            source_label = QLabel("原文:")
            source_label.setFont(self.make_ui_font(12, True))
            source_label.setStyleSheet('color: #61dafb; margin-bottom: 5px;')
            source_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            self.detail_info_layout.addWidget(source_label)
            source_text = QLabel(text)
            source_text.setFont(self.make_ui_font(14, False))
            source_text.setStyleSheet('margin-bottom: 20px;')
            source_text.setWordWrap(True)
            source_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            
            # 为长难句/翻译源增加 TTS 播放
            tts_row = QHBoxLayout()
            tts_row.addWidget(source_text, 1)
            tts_btn = QPushButton("🔊 朗读原文")
            
            def play_sentence():
                is_cn = self.contains_chinese(text)
                if is_cn:
                    voice = self.settings.get('tts_voice_cn', 'zh-CN-XiaoxiaoNeural')
                    rate = self.settings.get('tts_rate_cn', '+0%')
                else:
                    voice = self.settings.get('tts_voice', 'en-US-GuyNeural')
                    rate = self.settings.get('tts_rate', '+0%')
                get_tts_client().play(text, voice=voice, rate=rate)
            
            tts_btn.setFixedSize(110, 32)
            tts_btn.setFont(self.make_ui_font(10, False))
            tts_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            tts_btn.setStyleSheet("""
                QPushButton { 
                    background: transparent; 
                    border: 1px solid #3d3d3d; 
                    border-radius: 6px; 
                    color: #98c379;
                }
                QPushButton:hover { 
                    background: #3e3e42; 
                    border-color: #98c379; 
                }
            """)
            tts_btn.clicked.connect(play_sentence)
            tts_row.addWidget(tts_btn)
            self.detail_info_layout.addLayout(tts_row)
            self.current_word_label = None
            self.current_word_label_base_text = ""
            self.current_source_text_label = source_text
            self.update_current_query_visuals()
            trans_label = QLabel("翻译:")
            trans_label.setFont(self.make_ui_font(12, True))
            trans_label.setStyleSheet('color: #98c379; margin-bottom: 5px;')
            trans_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            self.detail_info_layout.addWidget(trans_label)
            self.translation_primary_widgets = []
            trans_text = QLabel(translated)
            trans_text.setFont(self.make_ui_font(14, False))
            trans_text.setWordWrap(True)
            trans_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            self.detail_info_layout.addWidget(trans_text)
            self.translation_primary_widgets = [trans_text]
            self.build_llm_translation_area()
            self.prepare_llm_translate_context(text, False, 'sentence', original_meaning=translated)
            self.build_note_section()
            self.add_ai_section()
            self.update_current_query_visuals()
        except Exception as e:
            error_label = QLabel(f"翻译失败: {str(e)}")
            error_label.setFont(self.make_ui_font(12, False))
            error_label.setStyleSheet('color: #e06c75;')
            self.detail_info_layout.addWidget(error_label)
