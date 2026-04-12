import html
import json
import os
import random
import re
import shutil
import threading
from datetime import datetime
from urllib.parse import quote, unquote
from urllib import error, request

from PyQt6.QtCore import QEvent, QPoint, QTimer, Qt, QObject, pyqtSignal

class _AIImportSignalHelper(QObject):
    update_status = pyqtSignal(str)
    finish = pyqtSignal(bool, str, str)
    save_data = pyqtSignal(str, list)


class _DocAnnotationSignalHelper(QObject):
    chunk = pyqtSignal(str)
    done = pyqtSignal(bool, str)


class _DocEditOutsideClickFilter(QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner

    def eventFilter(self, obj, event):
        owner = self.owner
        if (
            owner is not None
            and event is not None
            and event.type() == QEvent.Type.MouseButtonPress
            and owner._is_doc_editing()
            and hasattr(owner, "doc_content_edit")
            and not getattr(owner, "doc_auto_ai_dialog_open", False)
        ):
            try:
                global_pos = event.globalPosition().toPoint()
                local_pos = owner.doc_content_edit.mapFromGlobal(global_pos)
                if not owner.doc_content_edit.rect().contains(local_pos):
                    owner.on_doc_mode_preview_clicked()
            except Exception:
                pass
        return False


from PyQt6.QtGui import QBrush, QColor, QCursor, QIcon, QPainter, QPen, QPixmap, QTextDocument, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QFileDialog,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QToolButton,
    QTextBrowser,
    QTextEdit,
    QToolTip,
    QVBoxLayout,
    QWidget,
    QMenu,
    QGroupBox,
    QPlainTextEdit,
    QScrollArea,
)

from search_modules.infrastructure import build_highlighted_text_html
from search_modules.ai_prompts import default_ai_prompts, loads_prompts, prompt_text
from search_modules.tts_client import get_tts_client


class UserFeaturesMixin:
    def _install_doc_edit_outside_click_filter(self):
        app = QApplication.instance()
        if app is None:
            return
        if getattr(self, "_doc_edit_outside_filter_installed", False):
            return
        self._doc_edit_outside_click_filter = _DocEditOutsideClickFilter(self)
        app.installEventFilter(self._doc_edit_outside_click_filter)
        self._doc_edit_outside_filter_installed = True

    def _is_doc_editing(self):
        if not hasattr(self, "doc_content_stack") or not hasattr(self, "doc_content_edit"):
            return False
        try:
            return self.doc_content_stack.currentWidget() is self.doc_content_edit
        except Exception:
            return False

    def get_ai_prompts(self):
        raw = self.settings.get("ai_prompts_json", "") if hasattr(self, "settings") else ""
        merged = dict(default_ai_prompts())
        user_obj = loads_prompts(raw)
        for k, v in (user_obj or {}).items():
            if isinstance(k, str) and isinstance(v, str) and k.strip():
                merged[k.strip()] = v
        return merged

    def get_reviewing_word_records(self):
        basis = self.get_reviewing_sort_basis()
        candidates = self.get_scope_candidates("reviewing", 1)
        sorted_words = self.sort_words_by_basis(candidates, basis)
        return [(w,) for w in sorted_words]

    def get_reviewing_words(self):
        return [row[0] for row in self.get_reviewing_word_records()]

    def get_basis_options(self, include_self_select=False):
        options = [
            ("推荐（查询时间+熟练度加权）", "recommended"),
            ("根据最近查询时间", "recent"),
            ("完全随机", "random"),
            ("根据熟练度", "proficiency"),
        ]
        if include_self_select:
            options.append(("自选择", "self_select"))
        return options

    def get_reviewing_sort_basis(self):
        value = (self.settings.get("reviewing_sort_basis", "recommended") or "").strip()
        valid = {v for _, v in self.get_basis_options(include_self_select=False)}
        if value in valid:
            return value
        return "recommended"

    def init_reviewing_sort_ui(self):
        if not hasattr(self, 'reviewing_sort_combo'):
            return
        combo = self.reviewing_sort_combo
        combo.blockSignals(True)
        combo.clear()
        options = self.get_basis_options(include_self_select=False)
        for label, value in options:
            combo.addItem(label, value)
        basis = self.get_reviewing_sort_basis()
        for i in range(combo.count()):
            if combo.itemData(i) == basis:
                combo.setCurrentIndex(i)
                break
        combo.blockSignals(False)
        combo.currentIndexChanged.connect(self.on_reviewing_sort_basis_changed)

    def on_reviewing_sort_basis_changed(self, *_):
        if not hasattr(self, 'reviewing_sort_combo'):
            return
        basis = self.reviewing_sort_combo.currentData()
        if not basis:
            return
        self.set_setting("reviewing_sort_basis", basis)
        self.settings["reviewing_sort_basis"] = basis
        self.refresh_internal_page()

    def touch_reviewing_word(self, query):
        if not query:
            return
        ts = datetime.now().isoformat(timespec='seconds')
        cur = self.user_conn.cursor()
        cur.execute('UPDATE reviewing SET last_visited_at = ? WHERE query = ?', (ts, query))
        self.user_conn.commit()

    def switch_to_internal_with_focus(self, query):
        if hasattr(self, 'main_tabs'):
            self.main_tabs.setCurrentIndex(1)
        self.refresh_internal_page()
        if hasattr(self, 'reviewing_words_list'):
            for i in range(self.reviewing_words_list.count()):
                item = self.reviewing_words_list.item(i)
                item_query = item.data(Qt.ItemDataRole.UserRole) or ""
                if item_query.lower() == (query or "").lower():
                    self.reviewing_words_list.setCurrentItem(item)
                    break

    def switch_to_extension_page(self):
        if hasattr(self, 'main_tabs'):
            self.main_tabs.setCurrentIndex(0)

    def init_inner_workspace(self):
        self.inner_active_tool = ""
        self.inner_current_session_id = None
        self.wordcraft_space_highlight_on = False
        self.wordcraft_show_assist_on = False
        self.wordcraft_last_selected_text = ""
        self.wordcraft_last_result = {}
        self.wordcraft_pending_segments = []
        self.wordcraft_pending_confirm = False
        self.wordcraft_session_id = None
        self.wordcraft_annotation_cache = []
        self.wordcraft_auto_ai_last_signature = None
        self.wordcraft_auto_ai_dialog_open = False
        self.wordcraft_auto_ai_pending = None
        self.wordcraft_auto_ai_inflight_signatures = set()
        self.wordcraft_annotation_stream_buffers = {}
        self.wordcraft_last_hover_key = None
        self.wordcraft_annotation_hover_on_window = False
        self.inner_wordcraft_btn = QPushButton("选词成文")
        self.inner_wordcraft_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.inner_wordcraft_btn.setCheckable(True)
        self.inner_wordcraft_btn.setIcon(self.build_wordcraft_icon())
        self.inner_wordcraft_btn.clicked.connect(self.on_inner_wordcraft_clicked)
        self.inner_tool_bar_layout.insertWidget(1, self.inner_wordcraft_btn)

        # 随机考词
        self.inner_quiz_btn = QPushButton("随机考词")
        self.inner_quiz_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.inner_quiz_btn.clicked.connect(self.on_inner_quiz_clicked)
        self.inner_tool_bar_layout.insertWidget(2, self.inner_quiz_btn)
        self.inner_tool_settings_btn = QPushButton("设置")
        self.inner_tool_settings_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.inner_tool_settings_btn.clicked.connect(self.open_wordcraft_settings_dialog)
        self.inner_tool_settings_btn.setVisible(False)
        self.inner_tool_bar_layout.insertWidget(3, self.inner_tool_settings_btn)
        self.inner_wordcraft_listen_btn = QPushButton("🔊")
        self.inner_wordcraft_listen_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.inner_wordcraft_listen_btn.setToolTip("朗读本会话英文")
        self.inner_wordcraft_listen_btn.clicked.connect(self.on_wordcraft_listen_clicked)
        self.inner_wordcraft_listen_btn.setVisible(False)
        self.inner_tool_bar_layout.insertWidget(4, self.inner_wordcraft_listen_btn)
        self.inner_tool_action_1.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.inner_tool_action_2.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.inner_tool_action_1.clicked.connect(self.create_blank_inner_session)
        self.inner_tool_action_2.clicked.connect(self.delete_current_inner_session)
        self.inner_session_list.itemClicked.connect(self.on_inner_session_activated)
        self.inner_dialog_editor.setReadOnly(True)
        self.inner_dialog_editor.setMouseTracking(True)
        self.inner_dialog_editor.viewport().setMouseTracking(True)
        self.inner_dialog_editor.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.inner_dialog_editor.customContextMenuRequested.connect(self.on_inner_dialog_context_menu)
        self.inner_dialog_editor.selectionChanged.connect(self.on_inner_dialog_selection_changed)
        self.inner_dialog_editor._orig_key_press = self.inner_dialog_editor.keyPressEvent
        self.inner_dialog_editor._orig_mouse_press = self.inner_dialog_editor.mousePressEvent
        self.inner_dialog_editor._orig_mouse_move = self.inner_dialog_editor.mouseMoveEvent
        self.inner_dialog_editor._orig_leave_event = self.inner_dialog_editor.leaveEvent
        self.inner_dialog_editor.keyPressEvent = self.on_inner_dialog_key_press
        self.inner_dialog_editor.mousePressEvent = self.on_inner_dialog_mouse_press
        self.inner_dialog_editor.mouseMoveEvent = self.on_inner_dialog_mouse_move
        self.inner_dialog_editor.leaveEvent = self.on_inner_dialog_leave
        if hasattr(self, 'inner_confirm_btn'):
            self.inner_confirm_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.inner_confirm_btn.clicked.connect(self.on_confirm_wordcraft_segments)
            self.inner_confirm_btn.setVisible(False)
        self.load_wordcraft_config()
        self.load_inner_sessions()
        self.update_inner_toolbar_visual()
        self._init_quiz_panel()
        if hasattr(self, 'init_export_ui'):
            self.init_export_ui()

    def _init_quiz_panel(self):
        if not hasattr(self, "inner_quiz_panel") or self.inner_quiz_panel is None:
            return
        # 防止重复初始化导致布局叠加（例如某些情况下重复调用 init_inner_workspace）
        if self.inner_quiz_panel.layout() is not None:
            return
        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        self.inner_quiz_panel.setLayout(root)

        title = QLabel("随机考词（最多 5 个）")
        title.setFont(self.make_ui_font(12, True))
        root.addWidget(title)

        self.quiz_tip = QLabel("点击工具栏“随机考词”开始。每个单词可点“AI 提示”。完成后提交，让 AI 评档并自动更新熟练度。")
        self.quiz_tip.setWordWrap(True)
        root.addWidget(self.quiz_tip)

        self.quiz_scroll = QScrollArea()
        self.quiz_scroll.setWidgetResizable(True)
        self.quiz_scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        self.quiz_items_host = QWidget()
        self.quiz_items_layout = QVBoxLayout()
        self.quiz_items_layout.setContentsMargins(0, 0, 0, 0)
        self.quiz_items_layout.setSpacing(10)
        self.quiz_items_host.setLayout(self.quiz_items_layout)
        self.quiz_scroll.setWidget(self.quiz_items_host)
        root.addWidget(self.quiz_scroll, 1)

        btn_row = QWidget()
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_row.setLayout(btn_layout)
        self.quiz_back_btn = QPushButton("返回会话")
        self.quiz_back_btn.clicked.connect(self._exit_quiz_panel)
        btn_layout.addWidget(self.quiz_back_btn)
        btn_layout.addStretch()
        self.quiz_submit_btn = QPushButton("提交考核并评档")
        self.quiz_submit_btn.clicked.connect(self.on_quiz_submit_clicked)
        btn_layout.addWidget(self.quiz_submit_btn)
        root.addWidget(btn_row)

        self.quiz_state = {"items": []}

    def _enter_quiz_panel(self):
        if hasattr(self, "inner_dialog_stack"):
            self.inner_dialog_stack.setCurrentWidget(self.inner_quiz_panel)

    def _exit_quiz_panel(self):
        if hasattr(self, "inner_dialog_stack"):
            self.inner_dialog_stack.setCurrentWidget(self.inner_dialog_editor)

    def get_quiz_candidates(self):
        cur = self.user_conn.cursor()
        # 优先 reviewing，其次 favorites，最后 queries
        cur.execute("SELECT query FROM reviewing")
        rows = [r[0] for r in cur.fetchall() if (r and r[0])]
        if len(rows) < 5:
            cur.execute("SELECT query FROM favorites")
            rows.extend([r[0] for r in cur.fetchall() if (r and r[0])])
        if len(rows) < 5:
            cur.execute("SELECT query FROM queries")
            rows.extend([r[0] for r in cur.fetchall() if (r and r[0])])
        seen = set()
        out = []
        for q in rows:
            key = (q or "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(q.strip())
        return out

    def get_word_profile(self, word):
        cur = self.user_conn.cursor()
        cur.execute("SELECT proficiency, last_visited_at FROM reviewing WHERE query = ? COLLATE NOCASE", (word,))
        row = cur.fetchone()
        proficiency = (row[0] if row else "") or "人上人"
        cur.execute("SELECT last_at FROM queries WHERE query = ? COLLATE NOCASE", (word,))
        row2 = cur.fetchone()
        last_at = (row2[0] if row2 else "") or ""
        return proficiency, last_at

    def on_inner_quiz_clicked(self):
        candidates = self.get_quiz_candidates()
        if not candidates:
            QMessageBox.information(self, "随机考词", "暂无可考核的单词（reviewing/favorites/queries 都为空）。")
            return
        picked = random.sample(candidates, k=min(5, len(candidates)))
        self.build_quiz_items(picked)
        self._enter_quiz_panel()

    def build_quiz_items(self, words):
        # 清空旧 items
        for i in reversed(range(self.quiz_items_layout.count())):
            w = self.quiz_items_layout.itemAt(i).widget()
            if w is not None:
                w.setParent(None)
        items = []
        for w in words:
            p, last_at = self.get_word_profile(w)
            rel_time = self.format_relative_time(self.parse_iso_ts(last_at)) if last_at else "从未查询"
            
            # 使用 QGroupBox 包装每个词的考核项，增加层次感
            box = QGroupBox(w)
            box.setFont(self.make_ui_font(12, True))
            lay = QVBoxLayout()
            lay.setContentsMargins(15, 20, 15, 15)
            lay.setSpacing(10)
            box.setLayout(lay)
            
            meta = QLabel(f"原熟练度：{p}    最近查询：{rel_time}")
            meta.setStyleSheet("color: #999; font-size: 11px; border: none;")
            lay.addWidget(meta)

            ans = QPlainTextEdit()
            ans.setPlaceholderText("请输入你对该词的中文释义/解释（越全面越好）")
            ans.setFixedHeight(70)
            ans.setStyleSheet("QPlainTextEdit{background: #252526; border: 1px solid #3e3e42; border-radius: 4px; padding: 6px; color: #d4d4d4;}")
            lay.addWidget(ans)

            hint_row = QWidget()
            hint_lay = QHBoxLayout()
            hint_lay.setContentsMargins(0, 0, 0, 0)
            hint_row.setLayout(hint_lay)
            hint_btn = QPushButton("💡 AI 提示")
            hint_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            hint_btn.setStyleSheet("QPushButton{padding: 4px 12px;}")
            hint_lay.addWidget(hint_btn)
            hint_lay.addStretch()
            lay.addWidget(hint_row)

            hint_view = QTextBrowser()
            hint_view.setOpenExternalLinks(False)
            hint_view.setVisible(False)
            hint_view.setMinimumHeight(72)
            hint_view.setStyleSheet("QTextBrowser{border:1px solid #3d3d3d;border-radius:6px;padding:8px;color:#98c379;background: #1a1a1a;}")
            lay.addWidget(hint_view)

            item = {
                "word": w,
                "before": p,
                "last_at": last_at,
                "answer_widget": ans,
                "hint_used": False,
                "hint_view": hint_view,
                "hint_btn": hint_btn,
            }
            hint_btn.clicked.connect(lambda _=False, it=item: self.on_quiz_hint_clicked(it))
            items.append(item)
            self.quiz_items_layout.addWidget(box)
        self.quiz_state = {"items": items}

    def on_quiz_hint_clicked(self, item):
        word = item.get("word", "")
        ans_text = item.get("answer_widget").toPlainText().strip() if item.get("answer_widget") else ""
        url = self.normalize_api_url(self.settings.get('api_url', ''))
        key = self.settings.get('api_key', '')
        model = self.get_mid_model_name() or self.get_high_model_name()
        if not url or not key or not model:
            QMessageBox.warning(self, "AI 提示失败", "AI 配置不完整：请先在设置中配置 API URL、API Key 和模型。")
            return
        tmpl = prompt_text(self.get_ai_prompts(), "quiz_hint_prompt", "")
        prompt = (tmpl or "").format(word=word, answer=ans_text)
        item["hint_btn"].setEnabled(False)
        threading.Thread(target=self._quiz_hint_worker, args=(url, key, model, prompt, word), daemon=True).start()
        item["hint_used"] = True

    def _quiz_hint_worker(self, url, key, model, prompt, word):
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": prompt_text(self.get_ai_prompts(), "note_ai_system", "You are a helpful English learning assistant for Chinese users.")},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
        }
        try:
            text = (self.request_ai_stream_text(url, key, payload, timeout=60) or "").strip()
            self.inner_tool_result_ready.emit({"ok": True, "tool": "quiz", "stage": "hint", "word": word, "text": text})
        except Exception as e:
            self.inner_tool_result_ready.emit({"ok": False, "tool": "quiz", "stage": "hint", "word": word, "error": str(e)})

    def on_quiz_submit_clicked(self):
        items = self.quiz_state.get("items", [])
        if not items:
            return
        payload_items = []
        for it in items:
            ans = it["answer_widget"].toPlainText().strip()
            payload_items.append({
                "word": it["word"],
                "before": it["before"],
                "hint_used": bool(it.get("hint_used")),
                "last_at": it.get("last_at", ""),
                "answer": ans,
            })
        self.quiz_state["user_answers"] = payload_items
        url = self.normalize_api_url(self.settings.get('api_url', ''))
        key = self.settings.get('api_key', '')
        model = self.get_high_model_name() or self.get_mid_model_name()
        if not url or not key or not model:
            QMessageBox.warning(self, "评档失败", "AI 配置不完整：请先在设置中配置 API URL、API Key 和模型。")
            return
        tmpl = prompt_text(self.get_ai_prompts(), "quiz_grade_prompt", "")
        prompt = (tmpl or "").format(items_json=json.dumps(payload_items, ensure_ascii=False))
        self.quiz_submit_btn.setEnabled(False)
        threading.Thread(target=self._quiz_grade_worker, args=(url, key, model, prompt), daemon=True).start()

    def _quiz_grade_worker(self, url, key, model, prompt):
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": prompt_text(self.get_ai_prompts(), "json_system", "You are a strict JSON generator.")},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2,
        }
        try:
            text = (self.request_ai_stream_text(url, key, payload, timeout=90) or "").strip()
            self.inner_tool_result_ready.emit({"ok": True, "tool": "quiz", "stage": "grade", "text": text})
        except Exception as e:
            self.inner_tool_result_ready.emit({"ok": False, "tool": "quiz", "stage": "grade", "error": str(e)})

    def on_quiz_hint_result(self, result):
        word = (result or {}).get("word", "")
        ok = bool((result or {}).get("ok"))
        text = (result or {}).get("text", "") if ok else f"提示失败：{(result or {}).get('error', '未知错误')}"
        for it in self.quiz_state.get("items", []):
            if (it.get("word") or "").lower() == (word or "").lower():
                if it.get("hint_view") is not None:
                    it["hint_view"].setVisible(True)
                    it["hint_view"].setPlainText(text)
                if it.get("hint_btn") is not None:
                    it["hint_btn"].setEnabled(True)
                break

    def apply_quiz_proficiency_updates(self, results):
        if not results:
            return
        levels = set(self.get_proficiency_levels())
        cur = self.user_conn.cursor()
        ts = datetime.now().isoformat(timespec='seconds')
        for row in results:
            word = (row.get("word") or "").strip()
            final = (row.get("final") or "").strip()
            if not word or final not in levels:
                continue
            cur.execute("SELECT 1 FROM reviewing WHERE query = ? COLLATE NOCASE", (word,))
            exists = cur.fetchone() is not None
            if exists:
                cur.execute("UPDATE reviewing SET proficiency = ?, last_visited_at = ? WHERE query = ? COLLATE NOCASE", (final, ts, word))
            else:
                cur.execute(
                    "INSERT INTO reviewing(query, proficiency, created_at, last_visited_at) VALUES(?, ?, ?, ?)",
                    (word, final, ts, ts),
                )
        self.user_conn.commit()
        self.refresh_internal_page()

    def on_quiz_grade_result(self, result):
        if hasattr(self, "quiz_submit_btn") and self.quiz_submit_btn is not None:
            self.quiz_submit_btn.setEnabled(True)
        if not result or not result.get("ok"):
            QMessageBox.warning(self, "评档失败", (result or {}).get("error", "未知错误"))
            return
        raw = (result.get("text") or "").strip()
        cleaned = raw
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            obj = json.loads(cleaned)
        except Exception:
            QMessageBox.warning(self, "评档失败", "AI 返回内容不是合法 JSON。")
            return
        results = obj.get("results", [])
        overall = obj.get("overall_comment", "")
        final_lines = obj.get("final_lines", [])
        if not isinstance(results, list):
            results = []
        self.apply_quiz_proficiency_updates(results)

        # 生成会话记录
        lines = []
        lines.append("【随机考词-评档结果】")
        
        # 添加用户的回答记录
        user_answers = self.quiz_state.get("user_answers", [])
        if user_answers:
            lines.append("\n【用户回答】")
            for ans in user_answers:
                word = ans.get("word", "")
                answer = ans.get("answer", "")
                hint_used = "使用了提示" if ans.get("hint_used") else "未使用提示"
                lines.append(f"{word}: {answer} ({hint_used})")
        
        # 添加AI评价
        if isinstance(final_lines, list) and final_lines:
            lines.append("\n【评档结果】")
            lines.append("\n".join([str(x) for x in final_lines if str(x).strip()]))
        else:
            lines.append("\n【评档结果】")
            for r in results:
                if isinstance(r, dict) and r.get("word") and r.get("final"):
                    lines.append(f"{r['word']}: {r['final']}")
        if overall:
            lines.append("\n【总体评价】")
            lines.append(str(overall))
        text = "\n".join([x for x in lines if x is not None])
        
        # 保存到会话历史
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        title = f"随机考词 [{ts}]"
        self.create_inner_session(title, "quiz", text, None)
        self.load_inner_sessions()
        
        # 选中新创建的会话
        if hasattr(self, 'inner_session_list') and self.inner_session_list.count() > 0:
            self.inner_session_list.setCurrentRow(0)
            self.on_inner_session_activated(self.inner_session_list.currentItem())
        
        self._exit_quiz_panel()


    def build_wordcraft_icon(self):
        pix = QPixmap(18, 18)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#61dafb"), 2))
        painter.drawRoundedRect(1, 1, 16, 16, 4, 4)
        painter.setPen(QPen(QColor("#61dafb"), 1))
        painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "文")
        painter.end()
        return QIcon(pix)

    def update_inner_toolbar_visual(self):
        if not hasattr(self, 'inner_wordcraft_btn'):
            return
        active = self.inner_active_tool == "wordcraft"
        self.inner_wordcraft_btn.setChecked(active)
        self.inner_tool_settings_btn.setVisible(active)
        if hasattr(self, "inner_wordcraft_listen_btn"):
            self.inner_wordcraft_listen_btn.setVisible(active)
            self.inner_wordcraft_listen_btn.setEnabled(bool((self.wordcraft_last_result or {}).get("english_clean", "").strip()))

    def load_wordcraft_config(self):
        raw = self.settings.get("wordcraft_config", "")
        cfg = {}
        if raw:
            try:
                cfg = json.loads(raw)
            except Exception:
                cfg = {}
        self.wordcraft_config = {
            "scope": cfg.get("scope", "reviewing"),
            "basis": cfg.get("basis", "recommended"),
            "folder_id": int(cfg.get("folder_id", 1) or 1),
            "word_count": int(cfg.get("word_count", 8) or 8),
            "difficulty": cfg.get("difficulty", "CET-4"),
            "selected_words": list(cfg.get("selected_words", [])),
        }

    def save_wordcraft_config(self):
        text = json.dumps(self.wordcraft_config, ensure_ascii=False)
        self.set_setting("wordcraft_config", text)
        self.settings["wordcraft_config"] = text

    def get_proficiency_levels(self):
        return ["拉完了", "NPC", "夯", "人上人", "顶级"]

    def get_proficiency_index(self, level):
        levels = self.get_proficiency_levels()
        token = (level or "").strip()
        if token not in levels:
            token = "人上人"
        return levels.index(token)

    def shift_reviewing_proficiency(self, words, delta):
        if not words or delta == 0:
            return
        levels = self.get_proficiency_levels()
        cur = self.user_conn.cursor()
        changed = 0
        for w in words:
            token = (w or "").strip()
            if not token:
                continue
            cur.execute("SELECT proficiency FROM reviewing WHERE query = ? COLLATE NOCASE", (token,))
            row = cur.fetchone()
            if not row:
                continue
            idx = self.get_proficiency_index(row[0] if row else "人上人")
            new_idx = min(max(idx + delta, 0), len(levels) - 1)
            if new_idx == idx:
                continue
            cur.execute("UPDATE reviewing SET proficiency = ? WHERE query = ? COLLATE NOCASE", (levels[new_idx], token))
            changed += 1
        if changed > 0:
            self.user_conn.commit()

    def strip_special_markers(self, text):
        raw = text or ""
        special_words = []
        seen = set()

        def repl(m):
            word = m.group(1)
            key = word.lower()
            if key not in seen:
                seen.add(key)
                special_words.append(word)
            return word

        cleaned = re.sub(r"([A-Za-z][A-Za-z'\-]*)\)", repl, raw)
        return cleaned, special_words

    def render_wordcraft_english_html(self):
        english = self.wordcraft_last_result.get("english_clean", "")
        special_set = {w.lower() for w in self.wordcraft_last_result.get("special_words", [])}
        chinese = self.wordcraft_last_result.get("chinese", "")
        if not english:
            return ""
        token_pattern = re.compile(r"[A-Za-z][A-Za-z'\-]*|[\s]+|[^\sA-Za-z]+")
        parts = []
        for token in token_pattern.findall(english):
            if token.isspace():
                parts.append(html.escape(token))
                continue
            low = token.lower()
            if self.wordcraft_show_assist_on and low in special_set:
                parts.append(f"<span style='background:#6b4f00;color:#ffe9a8;border-radius:3px;padding:1px 2px;'>{html.escape(token)}</span>")
            else:
                parts.append(html.escape(token))
        body = "".join(parts).replace("\n", "<br>")
        tip = "提示：按空格键可切换“中文+特殊词高亮”显示。"
        chinese_block = ""
        if self.wordcraft_show_assist_on and chinese:
            chinese_block = (
                "<div style='margin-top:12px;color:#98c379;'>"
                "<div style='margin-bottom:4px;'>中文：</div>"
                f"<div>{html.escape(chinese)}</div>"
                "</div>"
            )
        return (
            "<div style='line-height:1.7;'>"
            f"<div style='color:#61dafb;margin-bottom:8px;'>{tip}</div>"
            f"<div>{body}</div>"
            f"{chinese_block}"
            "</div>"
        )

    def refresh_wordcraft_display(self):
        html_text = self.render_wordcraft_english_html()
        if html_text:
            self.inner_dialog_editor.setHtml(html_text)
        self.apply_wordcraft_annotation_highlights()

    def markdown_to_html_fragment(self, text):
        doc = QTextDocument()
        doc.setMarkdown(text or "")
        html_text = doc.toHtml()
        m = re.search(r"<body[^>]*>([\s\S]*)</body>", html_text, re.IGNORECASE)
        if m:
            return m.group(1)
        return html_text

    def set_inner_markdown_preview(self, text):
        self.inner_dialog_editor.setHtml(self.markdown_to_html_fragment(text or ""))

    def on_inner_dialog_key_press(self, event):
        if self.inner_active_tool == "wordcraft" and event.key() == Qt.Key.Key_Space and self.wordcraft_last_result.get("english_clean"):
            self.wordcraft_show_assist_on = not self.wordcraft_show_assist_on
            self.refresh_wordcraft_display()
            return
        handler = getattr(self.inner_dialog_editor, "_orig_key_press", None)
        if handler is not None:
            handler(event)

    def on_inner_dialog_mouse_press(self, event):
        handler = getattr(self.inner_dialog_editor, "_orig_mouse_press", None) if hasattr(self, "inner_dialog_editor") else None
        if self.inner_active_tool == "wordcraft" and event is not None and event.button() == Qt.MouseButton.LeftButton:
            cursor = self.inner_dialog_editor.cursorForPosition(event.pos())
            line_text = (cursor.block().text() or "").strip()
            if line_text == "🔊":
                self.on_wordcraft_listen_clicked()
                return
        if handler is not None:
            handler(event)

    def on_inner_dialog_context_menu(self, pos):
        menu = self.inner_dialog_editor.createStandardContextMenu()
        if self.inner_active_tool == "wordcraft":
            menu.addSeparator()
            tts_act = menu.addAction("🔊 朗读本会话英文")
            tts_act.triggered.connect(self.on_wordcraft_listen_clicked)
            selected = (self.inner_dialog_editor.textCursor().selectedText() or "").replace("\u2029", "\n").strip()
            if selected:
                act = menu.addAction("AI 注释选中片段")
                act.triggered.connect(lambda: self.on_wordcraft_ai_annotate_selected(selected_text=selected, silent=False))
        menu.exec(self.inner_dialog_editor.mapToGlobal(pos))

    def on_inner_dialog_selection_changed(self):
        selected = (self.inner_dialog_editor.textCursor().selectedText() or "").replace("\u2029", "\n").strip()
        if selected:
            self.wordcraft_last_selected_text = selected
        if self.inner_active_tool != "wordcraft":
            return
        session_id = self._active_wordcraft_session_id()
        if session_id <= 0:
            return
        if not selected:
            self.wordcraft_auto_ai_last_signature = None
            return
        cursor = self.inner_dialog_editor.textCursor()
        start_pos = min(cursor.selectionStart(), cursor.selectionEnd())
        end_pos = max(cursor.selectionStart(), cursor.selectionEnd())
        self._queue_wordcraft_auto_ai_annotation(selected, start_pos, end_pos)

    def _active_wordcraft_session_id(self):
        if self.inner_active_tool != "wordcraft":
            return 0
        sid = self.inner_current_session_id or self.wordcraft_session_id
        try:
            sid = int(sid or 0)
        except Exception:
            sid = 0
        return sid if sid > 0 else 0

    def _queue_wordcraft_auto_ai_annotation(self, selected_text, start_pos, end_pos):
        selected = (selected_text or "").strip()
        if not selected:
            return
        session_id = self._active_wordcraft_session_id()
        if session_id <= 0:
            return
        signature = (
            "wordcraft",
            int(session_id),
            selected,
            int(start_pos),
            int(end_pos),
        )
        self.wordcraft_auto_ai_pending = {
            "session_id": int(session_id),
            "selected": selected,
            "start_pos": int(start_pos),
            "end_pos": int(end_pos),
            "signature": signature,
        }
        timer = getattr(self, "wordcraft_auto_ai_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._fire_wordcraft_auto_ai_annotation)
            self.wordcraft_auto_ai_timer = timer
        timer.start(520)

    def _fire_wordcraft_auto_ai_annotation(self):
        pending = getattr(self, "wordcraft_auto_ai_pending", None) or {}
        if not pending:
            return
        if getattr(self, "wordcraft_auto_ai_dialog_open", False):
            return
        if QApplication.mouseButtons() & Qt.MouseButton.LeftButton:
            timer = getattr(self, "wordcraft_auto_ai_timer", None)
            if timer is not None:
                timer.start(260)
            return
        signature = pending.get("signature")
        if signature and signature == getattr(self, "wordcraft_auto_ai_last_signature", None):
            return
        selected = (pending.get("selected") or "").strip()
        if not selected:
            return
        start_pos = int(pending.get("start_pos", -1))
        end_pos = int(pending.get("end_pos", -1))
        if start_pos < 0 or end_pos <= start_pos:
            start_pos, end_pos = self._resolve_wordcraft_selection_range(selected)
        self.wordcraft_auto_ai_last_signature = signature
        self.on_wordcraft_ai_annotate_selected(
            selected_text=selected,
            start_pos=start_pos,
            end_pos=end_pos,
            silent=True,
        )

    def _resolve_wordcraft_selection_range(self, selected_text):
        selected = (selected_text or "").strip()
        if not selected or not hasattr(self, "inner_dialog_editor"):
            return -1, -1
        text = self.inner_dialog_editor.toPlainText() or ""
        if not text:
            return -1, -1
        idx = text.find(selected)
        if idx >= 0:
            return idx, idx + len(selected)
        return -1, -1

    def _build_wordcraft_annotation_context(self, selected_text, start_pos, end_pos):
        full_text = self.inner_dialog_editor.toPlainText() if hasattr(self, "inner_dialog_editor") else ""
        token = (selected_text or "").strip()
        if not full_text:
            return token
        try:
            start = int(start_pos)
            end = int(end_pos)
        except Exception:
            start, end = -1, -1
        if start < 0 or end <= start:
            start, end = self._resolve_wordcraft_selection_range(token)
        if start < 0 or end <= start:
            return token
        start = max(0, min(start, len(full_text)))
        end = max(start + 1, min(end, len(full_text)))
        window = 420
        left = max(0, start - window)
        right = min(len(full_text), end + window)
        context = full_text[left:right].strip()
        return context or token

    def on_wordcraft_ai_annotate_selected(self, selected_text, start_pos=-1, end_pos=-1, silent=False):
        session_id = self._active_wordcraft_session_id()
        selected = (selected_text or "").strip()
        if session_id <= 0 or not selected:
            return
        url = self.normalize_api_url(self.settings.get("api_url", ""))
        key = self.settings.get("api_key", "")
        model = self.get_high_model_name() or self.get_mid_model_name()
        if not url or not key or not model:
            if not silent:
                QMessageBox.warning(self, "AI 注释失败", "AI 配置不完整：请先在设置中配置 API URL、API Key 和模型。")
            return
        context_text = self._build_wordcraft_annotation_context(selected, start_pos, end_pos)
        tmpl = prompt_text(
            self.get_ai_prompts(),
            "doc_reader_explain_prompt",
            (
                "你是英语学习助手。请结合上下文解释用户圈选文本的含义。\n"
                "输出纯文本，不要小标题、序号或 Markdown。\n\n"
                "待解读上下文：\n{source_context}\n\n"
                "待解读内容：\n{selected_text}"
            ),
        )
        try:
            prompt = (tmpl or "").format(
                selected_text=selected,
                source_context=context_text,
                file_path=f"wordcraft_session:{session_id}",
            )
        except Exception:
            prompt = (
                "你是英语学习助手。请结合上下文解释用户选中片段在此处的意思。"
                "输出纯文本，不要标题。\n\n"
                f"上下文：\n{context_text}\n\n"
                f"片段：\n{selected}"
            )
        signature = (
            "wordcraft",
            int(session_id),
            int(start_pos),
            int(end_pos),
            selected,
        )
        inflight = getattr(self, "wordcraft_auto_ai_inflight_signatures", None)
        if inflight is None:
            inflight = set()
            self.wordcraft_auto_ai_inflight_signatures = inflight
        if signature in inflight:
            return
        inflight.add(signature)
        self.wordcraft_auto_ai_dialog_open = True
        self._begin_wordcraft_annotation_stream(signature, selected, start_pos, end_pos)
        threading.Thread(
            target=self._wordcraft_annotation_worker_stream,
            args=(url, key, model, prompt, session_id, selected, start_pos, end_pos, signature, bool(silent)),
            daemon=True,
        ).start()

    def _begin_wordcraft_annotation_stream(self, signature, selected_text, start_pos, end_pos):
        buffers = getattr(self, "wordcraft_annotation_stream_buffers", None)
        if buffers is None:
            buffers = {}
            self.wordcraft_annotation_stream_buffers = buffers
        buffers[signature] = ""
        anchor = {
            "session_id": self._active_wordcraft_session_id(),
            "start_pos": int(start_pos),
            "end_pos": int(end_pos),
            "selected_text": (selected_text or "").strip(),
        }
        self.open_wordcraft_annotation_window(row=anchor)
        if hasattr(self, "wordcraft_annotation_window_detail"):
            self.wordcraft_annotation_window_detail.setPlainText("AI 正在生成注释...\n")

    def _wordcraft_annotation_worker_stream(self, url, key, model, prompt, session_id, selected_text, start_pos, end_pos, signature, silent):
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": prompt_text(self.get_ai_prompts(), "note_ai_system", "You are a helpful English learning assistant for Chinese users.")},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "stream": True,
        }
        pieces = []
        try:
            data = json.dumps(payload).encode("utf-8")
            req = request.Request(
                url,
                data=data,
                headers={
                    "Accept": "text/event-stream",
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {key}",
                },
                method="POST",
            )
            with request.urlopen(req, timeout=90) as resp:
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
                        if not piece:
                            continue
                        pieces.append(piece)
                        self.inner_tool_result_ready.emit(
                            {
                                "ok": True,
                                "tool": "wordcraft_annotation",
                                "stage": "chunk",
                                "signature": signature,
                                "session_id": int(session_id),
                                "selected_text": selected_text,
                                "start_pos": int(start_pos),
                                "end_pos": int(end_pos),
                                "silent": bool(silent),
                                "piece": piece,
                            }
                        )
                else:
                    resp_text = resp.read().decode("utf-8", errors="ignore")
                    text_piece = self.extract_text_from_response(resp_text) or ""
                    if text_piece:
                        pieces.append(text_piece)
                        self.inner_tool_result_ready.emit(
                            {
                                "ok": True,
                                "tool": "wordcraft_annotation",
                                "stage": "chunk",
                                "signature": signature,
                                "session_id": int(session_id),
                                "selected_text": selected_text,
                                "start_pos": int(start_pos),
                                "end_pos": int(end_pos),
                                "silent": bool(silent),
                                "piece": text_piece,
                            }
                        )
            self.inner_tool_result_ready.emit(
                {
                    "ok": True,
                    "tool": "wordcraft_annotation",
                    "stage": "done",
                    "signature": signature,
                    "session_id": int(session_id),
                    "selected_text": selected_text,
                    "start_pos": int(start_pos),
                    "end_pos": int(end_pos),
                    "silent": bool(silent),
                    "text": "".join(pieces).strip(),
                }
            )
        except Exception as e:
            self.inner_tool_result_ready.emit(
                {
                    "ok": False,
                    "tool": "wordcraft_annotation",
                    "stage": "done",
                    "signature": signature,
                    "session_id": int(session_id),
                    "selected_text": selected_text,
                    "start_pos": int(start_pos),
                    "end_pos": int(end_pos),
                    "silent": bool(silent),
                    "error": str(e),
                }
            )

    def on_wordcraft_annotation_result(self, result):
        stage = (result or {}).get("stage", "done")
        signature = (result or {}).get("signature")
        if stage == "chunk":
            piece = (result or {}).get("piece", "")
            if not piece:
                return
            buffers = getattr(self, "wordcraft_annotation_stream_buffers", None)
            if buffers is None:
                buffers = {}
                self.wordcraft_annotation_stream_buffers = buffers
            buffers[signature] = (buffers.get(signature, "") or "") + piece
            if hasattr(self, "wordcraft_annotation_window_detail"):
                self.wordcraft_annotation_window_detail.setPlainText(buffers[signature])
            return
        inflight = getattr(self, "wordcraft_auto_ai_inflight_signatures", None)
        if isinstance(inflight, set) and signature in inflight:
            inflight.discard(signature)
        self.wordcraft_auto_ai_dialog_open = False
        if not result or not result.get("ok"):
            if not (result or {}).get("silent"):
                QMessageBox.warning(self, "AI 注释失败", (result or {}).get("error", "未知错误"))
            return
        buffers = getattr(self, "wordcraft_annotation_stream_buffers", None)
        streamed = ""
        if isinstance(buffers, dict):
            streamed = buffers.pop(signature, "")
        note = (streamed or (result or {}).get("text", "") or "").strip()
        if note.startswith("```"):
            note = re.sub(r"^```(?:text|markdown)?\s*", "", note, flags=re.IGNORECASE)
            note = re.sub(r"\s*```$", "", note)
            note = note.strip()
        if not note:
            if not (result or {}).get("silent"):
                QMessageBox.information(self, "AI 注释", "模型未返回有效注释内容。")
            return
        row = self.save_wordcraft_annotation(
            int((result or {}).get("session_id", 0)),
            int((result or {}).get("start_pos", -1)),
            int((result or {}).get("end_pos", -1)),
            (result or {}).get("selected_text", ""),
            note,
        )
        if not row:
            return
        self.apply_wordcraft_annotation_highlights()
        self.open_wordcraft_annotation_window(row=row)

    def save_wordcraft_annotation(self, session_id, start_pos, end_pos, selected_text, annotation):
        sid = int(session_id or 0)
        token = (selected_text or "").strip()
        note = (annotation or "").strip()
        if sid <= 0 or not token or not note:
            return None
        s_pos = int(start_pos)
        e_pos = int(end_pos)
        if s_pos < 0 or e_pos <= s_pos:
            s_pos, e_pos = self._resolve_wordcraft_selection_range(token)
        if s_pos < 0 or e_pos <= s_pos:
            s_pos, e_pos = 0, 0
        ts = datetime.now().isoformat(timespec="seconds")
        cur = self.user_conn.cursor()
        cur.execute(
            "INSERT INTO wordcraft_annotations(session_id, start_pos, end_pos, selected_text, annotation, created_at, updated_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?)",
            (sid, int(s_pos), int(e_pos), token, note, ts, ts),
        )
        ann_id = int(cur.lastrowid)
        self.user_conn.commit()
        return {
            "id": ann_id,
            "session_id": sid,
            "start_pos": int(s_pos),
            "end_pos": int(e_pos),
            "selected_text": token,
            "annotation": note,
            "created_at": ts,
            "updated_at": ts,
        }

    def get_wordcraft_annotations(self, session_id):
        sid = int(session_id or 0)
        if sid <= 0:
            return []
        cur = self.user_conn.cursor()
        cur.execute(
            "SELECT id, session_id, start_pos, end_pos, selected_text, annotation, created_at, updated_at "
            "FROM wordcraft_annotations WHERE session_id = ? ORDER BY id DESC",
            (sid,),
        )
        out = []
        for r in cur.fetchall():
            out.append(
                {
                    "id": int(r[0]),
                    "session_id": int(r[1]),
                    "start_pos": int(r[2]),
                    "end_pos": int(r[3]),
                    "selected_text": r[4] or "",
                    "annotation": r[5] or "",
                    "created_at": r[6] or "",
                    "updated_at": r[7] or "",
                }
            )
        return out

    def _build_wordcraft_annotation_cache(self, text):
        sid = self._active_wordcraft_session_id()
        cache = []
        if sid <= 0 or not text:
            return cache
        for row in self.get_wordcraft_annotations(sid):
            start_pos = int(row.get("start_pos", -1))
            end_pos = int(row.get("end_pos", -1))
            selected_text = row.get("selected_text", "")
            if not (selected_text and start_pos >= 0 and end_pos > start_pos and end_pos <= len(text) and text[start_pos:end_pos] == selected_text):
                continue
            resolved_start = start_pos
            resolved_end = end_pos
            cache.append(
                {
                    "id": int(row.get("id", 0)),
                    "session_id": sid,
                    "start_pos": resolved_start,
                    "end_pos": resolved_end,
                    "selected_text": selected_text,
                    "annotation": row.get("annotation", "") or "",
                    "created_at": row.get("created_at", "") or "",
                }
            )
        return cache

    def apply_wordcraft_annotation_highlights(self):
        if not hasattr(self, "inner_dialog_editor"):
            return
        if self.inner_active_tool != "wordcraft":
            self.wordcraft_annotation_cache = []
            self.inner_dialog_editor.setExtraSelections([])
            return
        text = self.inner_dialog_editor.toPlainText() or ""
        self.wordcraft_annotation_cache = self._build_wordcraft_annotation_cache(text)
        self.inner_dialog_editor.setExtraSelections(
            self._build_doc_extra_selections(self.inner_dialog_editor, self.wordcraft_annotation_cache)
        )

    def _get_wordcraft_annotation_by_pos(self, pos):
        for row in getattr(self, "wordcraft_annotation_cache", []) or []:
            start_pos = int(row.get("start_pos", -1))
            end_pos = int(row.get("end_pos", -1))
            if start_pos <= pos < end_pos:
                return row
        return None

    def _get_wordcraft_annotations_for_fragment(self, row):
        if not row:
            return []
        sid = int(row.get("session_id", self._active_wordcraft_session_id()) or 0)
        token = (row.get("selected_text", "") or "").strip()
        start_pos = int(row.get("start_pos", -1))
        end_pos = int(row.get("end_pos", -1))
        if sid <= 0 or not token:
            return []
        cur = self.user_conn.cursor()
        if start_pos >= 0 and end_pos > start_pos:
            cur.execute(
                "SELECT id, session_id, start_pos, end_pos, selected_text, annotation, created_at, updated_at "
                "FROM wordcraft_annotations WHERE session_id = ? AND start_pos = ? AND end_pos = ? AND selected_text = ? "
                "ORDER BY id DESC",
                (sid, start_pos, end_pos, token),
            )
        else:
            cur.execute(
                "SELECT id, session_id, start_pos, end_pos, selected_text, annotation, created_at, updated_at "
                "FROM wordcraft_annotations WHERE session_id = ? AND selected_text = ? ORDER BY id DESC",
                (sid, token),
            )
        out = []
        for r in cur.fetchall():
            out.append(
                {
                    "id": int(r[0]),
                    "session_id": int(r[1]),
                    "start_pos": int(r[2]),
                    "end_pos": int(r[3]),
                    "selected_text": r[4] or "",
                    "annotation": r[5] or "",
                    "created_at": r[6] or "",
                    "updated_at": r[7] or "",
                }
            )
        return out

    def open_wordcraft_annotation_window(self, row=None, global_pos=None):
        dlg = getattr(self, "wordcraft_annotation_window", None)
        if dlg is None:
            dlg = QDialog(self)
            dlg.setWindowTitle("选词成文注释")
            dlg.resize(700, 430)
            dlg.installEventFilter(self)
            root = QVBoxLayout()
            hint = QLabel("当前片段的所有注释：")
            hint.setWordWrap(True)
            root.addWidget(hint)
            token_label = QLabel("")
            token_label.setWordWrap(True)
            token_label.setStyleSheet("color:#61dafb;")
            root.addWidget(token_label)
            list_widget = QListWidget()
            root.addWidget(list_widget, 1)
            detail = QTextBrowser()
            detail.setOpenExternalLinks(False)
            detail.setPlaceholderText("选择一条注释查看完整内容")
            root.addWidget(detail, 1)
            btn_row = QHBoxLayout()
            delete_btn = QPushButton("删除选中注释")
            close_btn = QPushButton("关闭")
            btn_row.addWidget(delete_btn)
            btn_row.addStretch()
            btn_row.addWidget(close_btn)
            root.addLayout(btn_row)
            dlg.setLayout(root)
            self.wordcraft_annotation_window = dlg
            self.wordcraft_annotation_window_list = list_widget
            self.wordcraft_annotation_window_detail = detail
            self.wordcraft_annotation_window_token = token_label
            delete_btn.clicked.connect(self.on_wordcraft_annotation_delete_clicked)
            close_btn.clicked.connect(dlg.close)
            list_widget.currentItemChanged.connect(self.on_wordcraft_annotation_item_changed)
        if row is None:
            row = getattr(self, "wordcraft_annotation_window_anchor", None)
            if row is None:
                sid = self._active_wordcraft_session_id()
                items = self.get_wordcraft_annotations(sid) if sid > 0 else []
                row = items[0] if items else None
            if row is None:
                QMessageBox.information(self, "选词成文注释", "当前会话还没有可展示的注释。")
                return
        self.wordcraft_annotation_window_anchor = dict(row)
        rows = self._get_wordcraft_annotations_for_fragment(row)
        if hasattr(self, "wordcraft_annotation_window_token"):
            token = (row.get("selected_text", "") or "").strip()
            self.wordcraft_annotation_window_token.setText(token if token else "（未识别片段）")
        if hasattr(self, "wordcraft_annotation_window_list"):
            box = self.wordcraft_annotation_window_list
            box.blockSignals(True)
            box.clear()
            for item_row in rows:
                text = (item_row.get("annotation", "") or "").strip()
                preview = text if len(text) <= 80 else (text[:80] + "...")
                stamp = (item_row.get("created_at", "") or "").replace("T", " ")[:19]
                label = f"{stamp}  {preview}" if stamp else preview
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, item_row)
                box.addItem(item)
            box.blockSignals(False)
            if box.count() > 0:
                box.setCurrentRow(0)
        if hasattr(self, "wordcraft_annotation_window_detail") and not rows:
            self.wordcraft_annotation_window_detail.setPlainText("该片段暂无注释。")
        if global_pos is not None:
            self.wordcraft_annotation_window.move(self._clamp_wordcraft_annotation_pos(global_pos, self.wordcraft_annotation_window))
        self._cancel_wordcraft_annotation_close()
        self.wordcraft_annotation_window.show()
        self.wordcraft_annotation_window.raise_()
        self.wordcraft_annotation_window.activateWindow()

    def on_wordcraft_annotation_item_changed(self, current, _previous):
        if not hasattr(self, "wordcraft_annotation_window_detail"):
            return
        if current is None:
            self.wordcraft_annotation_window_detail.clear()
            return
        row = current.data(Qt.ItemDataRole.UserRole) or {}
        self.wordcraft_annotation_window_detail.setPlainText((row.get("annotation", "") or "").strip())

    def on_wordcraft_annotation_delete_clicked(self):
        if not hasattr(self, "wordcraft_annotation_window_list"):
            return
        item = self.wordcraft_annotation_window_list.currentItem()
        if item is None:
            QMessageBox.information(self, "删除注释", "请先选择要删除的注释。")
            return
        row = item.data(Qt.ItemDataRole.UserRole) or {}
        ann_id = int(row.get("id", 0))
        if ann_id <= 0:
            return
        cur = self.user_conn.cursor()
        cur.execute("DELETE FROM wordcraft_annotations WHERE id = ?", (ann_id,))
        self.user_conn.commit()
        self.apply_wordcraft_annotation_highlights()
        anchor = getattr(self, "wordcraft_annotation_window_anchor", None)
        self.open_wordcraft_annotation_window(row=anchor)

    def on_wordcraft_annotation_manage_clicked(self):
        self.open_wordcraft_annotation_window()

    def _cancel_wordcraft_annotation_close(self):
        timer = getattr(self, "wordcraft_annotation_close_timer", None)
        if timer is not None:
            timer.stop()

    def _clamp_wordcraft_annotation_pos(self, pos, dlg):
        if pos is None:
            return None
        target = QPoint(int(pos.x()) + 14, int(pos.y()) + 14)
        screen = QApplication.screenAt(target)
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return target
        rect = screen.availableGeometry()
        width = max(int(dlg.width()), int(dlg.sizeHint().width()))
        height = max(int(dlg.height()), int(dlg.sizeHint().height()))
        max_x = max(rect.left(), rect.right() - width + 1)
        max_y = max(rect.top(), rect.bottom() - height + 1)
        x = min(max(target.x(), rect.left()), max_x)
        y = min(max(target.y(), rect.top()), max_y)
        return QPoint(x, y)

    def _schedule_wordcraft_annotation_close(self, delay_ms=500):
        timer = getattr(self, "wordcraft_annotation_close_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._close_wordcraft_annotation_window_if_needed)
            self.wordcraft_annotation_close_timer = timer
        timer.start(max(1, int(delay_ms)))

    def _is_mouse_on_wordcraft_annotated_fragment(self):
        if self.inner_active_tool != "wordcraft" or not hasattr(self, "inner_dialog_editor"):
            return False
        local_pos = self.inner_dialog_editor.mapFromGlobal(QCursor.pos())
        if not self.inner_dialog_editor.rect().contains(local_pos):
            return False
        cursor = self.inner_dialog_editor.cursorForPosition(local_pos)
        return self._get_wordcraft_annotation_by_pos(cursor.position()) is not None

    def _close_wordcraft_annotation_window_if_needed(self):
        dlg = getattr(self, "wordcraft_annotation_window", None)
        if dlg is None or not dlg.isVisible():
            return
        in_window = dlg.frameGeometry().contains(QCursor.pos())
        if in_window or getattr(self, "wordcraft_annotation_hover_on_window", False):
            return
        if self._is_mouse_on_wordcraft_annotated_fragment():
            return
        dlg.hide()

    def eventFilter(self, obj, event):
        dlg = getattr(self, "wordcraft_annotation_window", None)
        if dlg is not None and obj is dlg and event is not None:
            if event.type() in (QEvent.Type.Enter, QEvent.Type.HoverEnter):
                self.wordcraft_annotation_hover_on_window = True
                self._cancel_wordcraft_annotation_close()
            elif event.type() in (QEvent.Type.Leave, QEvent.Type.HoverLeave):
                self.wordcraft_annotation_hover_on_window = False
                self._schedule_wordcraft_annotation_close(500)
        return False

    def on_inner_dialog_mouse_move(self, event):
        handler = getattr(self.inner_dialog_editor, "_orig_mouse_move", None) if hasattr(self, "inner_dialog_editor") else None
        if handler is not None:
            handler(event)
        if self.inner_active_tool != "wordcraft" or not hasattr(self, "inner_dialog_editor"):
            return
        cursor = self.inner_dialog_editor.cursorForPosition(event.pos())
        row = self._get_wordcraft_annotation_by_pos(cursor.position())
        if not row:
            self.wordcraft_last_hover_key = None
            self._schedule_wordcraft_annotation_close(500)
            return
        key = (
            int(row.get("start_pos", -1)),
            int(row.get("end_pos", -1)),
            (row.get("selected_text", "") or "").strip(),
        )
        if key == getattr(self, "wordcraft_last_hover_key", None):
            self._cancel_wordcraft_annotation_close()
            return
        self.wordcraft_last_hover_key = key
        self.open_wordcraft_annotation_window(row=row, global_pos=self.inner_dialog_editor.mapToGlobal(event.pos()))

    def on_inner_dialog_leave(self, event):
        handler = getattr(self.inner_dialog_editor, "_orig_leave_event", None) if hasattr(self, "inner_dialog_editor") else None
        if handler is not None:
            handler(event)
        self.wordcraft_last_hover_key = None
        self._schedule_wordcraft_annotation_close(500)

    def add_wordcraft_pending_segment(self, text):
        token = (text or "").strip()
        if not token:
            return
        if token not in self.wordcraft_pending_segments:
            self.wordcraft_pending_segments.append(token)
        if hasattr(self, 'inner_confirm_btn') and self.wordcraft_pending_confirm:
            self.inner_confirm_btn.setText(f"确认讲解（已选 {len(self.wordcraft_pending_segments)} 段）")

    def get_scope_candidates(self, scope, folder_id):
        cur = self.user_conn.cursor()
        if scope == "reviewing":
            cur.execute(
                "SELECT r.query, COALESCE(q.last_at, ''), COALESCE(r.proficiency, '人上人') FROM reviewing r LEFT JOIN queries q ON q.query = r.query"
            )
        else:
            cur.execute(
                "SELECT f.query, COALESCE(q.last_at, ''), COALESCE(r.proficiency, '人上人') FROM favorites f LEFT JOIN queries q ON q.query = f.query LEFT JOIN reviewing r ON r.query = f.query WHERE f.folder_id = ?",
                (folder_id,),
            )
        rows = cur.fetchall()
        seen = set()
        unique = []
        for q, last_at, proficiency in rows:
            key = (q or "").lower()
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append((q, last_at or "", proficiency or "人上人"))
        return unique

    def parse_iso_ts(self, text):
        raw = (text or "").strip()
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except Exception:
            return None

    def format_relative_time(self, dt):
        if not dt:
            return ""
        now = datetime.now()
        diff = now - dt
        seconds = diff.total_seconds()
        if seconds < 3600:
            return "不久前"
        elif seconds < 86400:
            hours = int(seconds // 3600)
            return f"{hours}小时前"
        else:
            days = int(seconds // 86400)
            return f"{days}天前"

    def sort_words_by_basis(self, candidates, basis, count=None):
        rows = list(candidates or [])
        if not rows:
            return []
        limit = len(rows) if count is None else max(1, int(count))
        max_idx = max(len(self.get_proficiency_levels()) - 1, 1)
        now = datetime.now()
        if basis == "random":
            random.shuffle(rows)
            return [w for w, _, _ in rows[:limit]]
        if basis == "recent":
            sorted_rows = sorted(
                rows,
                key=lambda x: self.parse_iso_ts(x[1]) or datetime(1970, 1, 1),
            )
            return [w for w, _, _ in sorted_rows[:limit]]
        if basis == "proficiency":
            sorted_rows = sorted(
                rows,
                key=lambda x: (
                    self.get_proficiency_index(x[2] or "人上人"),
                    self.parse_iso_ts(x[1]) or datetime(1970, 1, 1),
                ),
            )
            return [w for w, _, _ in sorted_rows[:limit]]
        scored = []
        for w, last_at, proficiency in rows:
            ts = self.parse_iso_ts(last_at)
            days = 365 if ts is None else max((now - ts).total_seconds() / 86400.0, 0.0)
            stale_score = min(days, 60.0) / 60.0
            prof_idx = self.get_proficiency_index(proficiency or "人上人")
            weak_score = 1.0 - (prof_idx / max_idx)
            score = stale_score * 0.65 + weak_score * 0.35
            scored.append((score, w))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [w for _, w in scored[:limit]]

    def select_words_for_wordcraft(self, cfg):
        scope = cfg.get("scope", "reviewing")
        folder_id = int(cfg.get("folder_id", 1) or 1)
        basis = cfg.get("basis", "recommended")
        count = max(1, int(cfg.get("word_count", 8) or 8))
        candidates = self.get_scope_candidates(scope, folder_id)
        if not candidates:
            return []
        if basis == "self_select":
            selected = [w for w in cfg.get("selected_words", []) if isinstance(w, str)]
            chosen = []
            exists = {w.lower(): w for w, _, _ in candidates}
            for token in selected:
                key = token.strip().lower()
                if key in exists and exists[key] not in chosen:
                    chosen.append(exists[key])
            return chosen
        return self.sort_words_by_basis(candidates, basis, count=count)

    def build_wordcraft_scope_options(self):
        options = [("在背单词", "reviewing", 1)]
        cur = self.user_conn.cursor()
        cur.execute("SELECT id, name FROM folders ORDER BY id")
        for folder_id, folder_name in cur.fetchall():
            options.append((f"收藏夹：{folder_name}", "favorites", int(folder_id)))
        return options

    def open_wordcraft_settings_dialog(self):
        self.load_wordcraft_config()
        cfg = dict(self.wordcraft_config)
        dlg = QDialog(self)
        dlg.setWindowTitle("选词成文设置")
        root = QVBoxLayout()
        form = QFormLayout()
        scope_combo = QComboBox()
        scope_options = self.build_wordcraft_scope_options()
        for label, scope, folder_id in scope_options:
            scope_combo.addItem(label, (scope, folder_id))
        for idx, (_, scope, folder_id) in enumerate(scope_options):
            if scope == cfg.get("scope", "reviewing") and int(folder_id) == int(cfg.get("folder_id", 1)):
                scope_combo.setCurrentIndex(idx)
                break
        basis_combo = QComboBox()
        basis_options = self.get_basis_options(include_self_select=True)
        for label, value in basis_options:
            basis_combo.addItem(label, value)
        for idx, (_, value) in enumerate(basis_options):
            if value == cfg.get("basis", "recommended"):
                basis_combo.setCurrentIndex(idx)
                break
        count_spin = QSpinBox()
        count_spin.setRange(1, 30)
        count_spin.setValue(max(1, int(cfg.get("word_count", 8) or 8)))
        difficulty_combo = QComboBox()
        for d in ["高考", "CET-4", "CET-6", "考研", "专八", "GRE"]:
            difficulty_combo.addItem(d)
        diff_idx = difficulty_combo.findText(cfg.get("difficulty", "CET-4"))
        if diff_idx >= 0:
            difficulty_combo.setCurrentIndex(diff_idx)
        self_select_list = QListWidget()
        self_select_list.setMinimumHeight(180)
        self_select_list.itemClicked.connect(
            lambda item: item.setCheckState(Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked)
        )

        def refresh_self_select_list():
            self_select_list.clear()
            scope_val, folder_val = scope_combo.currentData()
            rows = self.get_scope_candidates(scope_val, int(folder_val))
            sorted_words = self.sort_words_by_basis(rows, basis_combo.currentData() or "recommended")
            selected_set = {str(x).strip().lower() for x in cfg.get("selected_words", [])}
            if not selected_set:
                default_count = max(1, int(cfg.get("word_count", 8) or 8))
                selected_set = {w.lower() for w in sorted_words[:default_count]}
            for w in sorted_words:
                item = QListWidgetItem(w)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if w.lower() in selected_set else Qt.CheckState.Unchecked)
                self_select_list.addItem(item)

        def sync_basis_state():
            is_self = basis_combo.currentData() == "self_select"
            self_select_list.setVisible(is_self)
            count_spin.setEnabled(not is_self)

        refresh_self_select_list()
        sync_basis_state()
        scope_combo.currentIndexChanged.connect(refresh_self_select_list)
        basis_combo.currentIndexChanged.connect(refresh_self_select_list)
        basis_combo.currentIndexChanged.connect(sync_basis_state)
        form.addRow("词汇范围", scope_combo)
        form.addRow("选择依据", basis_combo)
        form.addRow("串词数量", count_spin)
        form.addRow("难度", difficulty_combo)
        form.addRow("自选择词汇", self_select_list)
        root.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        root.addWidget(buttons)
        dlg.setLayout(root)
        if not dlg.exec():
            return
        scope_value, folder_value = scope_combo.currentData()
        basis_value = basis_combo.currentData()
        selected_words = []
        if basis_value == "self_select":
            for i in range(self_select_list.count()):
                item = self_select_list.item(i)
                if item.checkState() == Qt.CheckState.Checked:
                    selected_words.append(item.text())
            if not selected_words:
                QMessageBox.warning(self, "设置未保存", "自选择模式下至少选择 1 个词。")
                return
        self.wordcraft_config = {
            "scope": scope_value,
            "basis": basis_value,
            "folder_id": int(folder_value),
            "word_count": len(selected_words) if basis_value == "self_select" else int(count_spin.value()),
            "difficulty": difficulty_combo.currentText(),
            "selected_words": selected_words,
        }
        self.save_wordcraft_config()

    def on_inner_wordcraft_clicked(self):
        if self.inner_active_tool != "wordcraft":
            self.inner_active_tool = "wordcraft"
            self.update_inner_toolbar_visual()
            self.inner_dialog_editor.setPlainText("已激活“选词成文”。再次点击按钮将进入 AI 交互模式。")
            self.apply_wordcraft_annotation_highlights()
            return
        self.run_wordcraft_ai_generation()

    def create_blank_inner_session(self):
        self.inner_current_session_id = None
        self.wordcraft_session_id = None
        self.wordcraft_last_result = {}
        self.inner_session_list.clearSelection()
        self.inner_dialog_editor.clear()
        self.wordcraft_pending_confirm = False
        self.wordcraft_pending_segments = []
        self.apply_wordcraft_annotation_highlights()
        if hasattr(self, 'inner_confirm_btn'):
            self.inner_confirm_btn.setVisible(False)

    def create_inner_session(self, title, tool, content, config_json):
        cur = self.user_conn.cursor()
        ts = datetime.now().isoformat(timespec='seconds')
        cur.execute(
            'INSERT INTO inner_sessions(title, tool, content, config_json, rating, created_at, updated_at) VALUES(?, ?, ?, ?, NULL, ?, ?)',
            (title, tool, content, config_json, ts, ts),
        )
        self.user_conn.commit()
        return int(cur.lastrowid)

    def update_inner_session_rating(self, session_id, rating):
        if not session_id:
            return
        cur = self.user_conn.cursor()
        ts = datetime.now().isoformat(timespec='seconds')
        cur.execute('UPDATE inner_sessions SET rating = ?, updated_at = ? WHERE id = ?', (int(rating), ts, int(session_id)))
        self.user_conn.commit()

    def load_inner_sessions(self):
        if not hasattr(self, 'inner_session_list'):
            return
        self.inner_session_list.clear()
        cur = self.user_conn.cursor()
        cur.execute('SELECT id, title, updated_at FROM inner_sessions ORDER BY COALESCE(updated_at, created_at) DESC, id DESC')
        for sid, title, updated_at in cur.fetchall():
            dt = self.parse_iso_ts(updated_at)
            time_str = self.format_relative_time(dt) if dt else (updated_at or '')[:16].replace('T', ' ')
            text = f"{title}  [{time_str}]"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, int(sid))
            self.inner_session_list.addItem(item)

    def on_inner_session_activated(self, item):
        session_id = item.data(Qt.ItemDataRole.UserRole)
        if not session_id:
            return
        self.inner_current_session_id = int(session_id)
        cur = self.user_conn.cursor()
        cur.execute('SELECT content, tool, config_json FROM inner_sessions WHERE id = ?', (self.inner_current_session_id,))
        row = cur.fetchone()
        if not row:
            return
        content, tool, config_json = row
        self.wordcraft_show_assist_on = False
        display_content = content or ""
        if (tool or "") == "wordcraft" and not (display_content or "").lstrip().startswith("🔊"):
            display_content = f"🔊\n{display_content}"
        self.set_inner_markdown_preview(display_content)
        self.inner_active_tool = tool or ""
        self.wordcraft_session_id = int(self.inner_current_session_id) if self.inner_active_tool == "wordcraft" else None
        if self.inner_active_tool == "wordcraft":
            self.wordcraft_last_result = self.parse_wordcraft_session_payload(content or "", config_json)
        else:
            self.wordcraft_last_result = {}
        self.update_inner_toolbar_visual()
        self.apply_wordcraft_annotation_highlights()
        if tool == "wordcraft":
            cfg = self.wordcraft_last_result.get("config", {})
            if isinstance(cfg, dict) and cfg:
                self.wordcraft_config = cfg

    def delete_current_inner_session(self):
        item = self.inner_session_list.currentItem() if hasattr(self, 'inner_session_list') else None
        if not item:
            return
        session_id = item.data(Qt.ItemDataRole.UserRole)
        if not session_id:
            return
        cur = self.user_conn.cursor()
        cur.execute('DELETE FROM wordcraft_annotations WHERE session_id = ?', (int(session_id),))
        cur.execute('DELETE FROM inner_sessions WHERE id = ?', (int(session_id),))
        self.user_conn.commit()
        self.inner_current_session_id = None
        self.wordcraft_session_id = None
        self.wordcraft_last_result = {}
        self.inner_dialog_editor.clear()
        self.wordcraft_pending_confirm = False
        self.wordcraft_pending_segments = []
        self.apply_wordcraft_annotation_highlights()
        if hasattr(self, 'inner_confirm_btn'):
            self.inner_confirm_btn.setVisible(False)
        self.load_inner_sessions()

    def build_wordcraft_prompt(self, words, cfg):
        joined = ", ".join(words)
        mode_name = {
            "recommended": "推荐（查询时间+熟练度加权）",
            "recent": "最近查询时间",
            "random": "完全随机",
            "proficiency": "熟练度",
            "self_select": "自选择",
        }.get(cfg.get("basis", "recommended"), "推荐")
        tmpl = prompt_text(
            self.get_ai_prompts(),
            "wordcraft_generate_prompt",
            (
                "你是英语学习助手。请用给定目标词写一段自然英文短文，并给出中文译文。\n"
                "输出严格 JSON：{\"english\":\"...\",\"chinese\":\"...\",\"special_words\":[\"w1\",\"w2\"]}\n"
                "special_words 只保留正文里出现且来自目标词的单词。\n"
                "目标难度：{difficulty}\n选词依据：{basis}\n目标词：{words}"
            ),
        )
        text = tmpl or ""
        return (
            text.replace("{difficulty}", str(cfg.get("difficulty", "CET-4")))
            .replace("{basis}", mode_name)
            .replace("{words}", joined)
        )

    def run_wordcraft_ai_generation(self):
        self.load_wordcraft_config()
        words = self.select_words_for_wordcraft(self.wordcraft_config)
        if not words:
            QMessageBox.warning(self, "选词成文", "当前设置下没有可用词汇，请先调整设置。")
            return
        url = self.normalize_api_url(self.settings.get('api_url', ''))
        key = self.settings.get('api_key', '')
        model = self.get_high_model_name() or self.get_mid_model_name()
        if not url or not key or not model:
            QMessageBox.warning(self, "选词成文", "AI 配置不完整：请先在设置中配置 API URL、API Key 和模型。")
            return
        prompt = self.build_wordcraft_prompt(words, self.wordcraft_config)
        self.set_inner_markdown_preview("正在生成，请稍候...")
        self.wordcraft_space_highlight_on = False
        self.wordcraft_show_assist_on = False
        self.wordcraft_pending_segments = []
        self.wordcraft_pending_confirm = False
        if hasattr(self, 'inner_confirm_btn'):
            self.inner_confirm_btn.setVisible(False)
            self.inner_confirm_btn.setText("确认已选中不懂片段")
        self.inner_wordcraft_btn.setEnabled(False)
        threading.Thread(
            target=self._wordcraft_worker,
            args=(url, key, model, prompt, words, dict(self.wordcraft_config)),
            daemon=True,
        ).start()

    def _wordcraft_worker(self, url, key, model, prompt, words, cfg):
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "你是英语学习助手。请严格按用户要求输出。"},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.5,
        }
        try:
            answer = (self.request_ai_stream_text(url, key, payload, timeout=90) or "").strip()
            if not answer:
                answer = "模型未返回内容。"
            english_text = ""
            chinese_text = ""
            try:
                obj = json.loads(answer)
                if isinstance(obj, dict):
                    english_text = str(obj.get("english", "")).strip()
                    chinese_text = str(obj.get("chinese", "")).strip()
            except Exception:
                pass
            if not english_text:
                english_text = answer
            special_words = []
            try:
                obj = json.loads(answer)
                raw_special = obj.get("special_words", []) if isinstance(obj, dict) else []
                if isinstance(raw_special, list):
                    special_words = [str(x).strip() for x in raw_special if str(x).strip()]
            except Exception:
                pass
            self.inner_tool_result_ready.emit(
                {
                    "ok": True,
                    "tool": "wordcraft",
                    "stage": "generate",
                    "english": english_text,
                    "chinese": chinese_text,
                    "special_words": special_words,
                    "words": words,
                    "config": cfg,
                }
            )
        except error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8", errors="ignore")
            except Exception:
                err_body = ""
            self.inner_tool_result_ready.emit({"ok": False, "tool": "wordcraft", "error": f"HTTP {e.code} {e.reason}\n{err_body}"})
        except Exception as e:
            self.inner_tool_result_ready.emit({"ok": False, "tool": "wordcraft", "error": str(e)})

    def on_inner_tool_result(self, result):
        tool = (result or {}).get("tool", "")
        if tool == "quiz":
            stage = (result or {}).get("stage", "")
            if stage == "hint":
                self.on_quiz_hint_result(result)
                return
            if stage == "grade":
                self.on_quiz_grade_result(result)
                return
        if tool == "doc_annotation":
            self.on_doc_annotation_result(result)
            return
        if tool == "wordcraft_annotation":
            self.on_wordcraft_annotation_result(result)
            return
        if tool != "wordcraft":
            return
        stage = (result or {}).get("stage", "generate")
        if stage == "explain":
            self.on_wordcraft_explain_result(result)
            return
        if hasattr(self, 'inner_wordcraft_btn'):
            self.inner_wordcraft_btn.setEnabled(True)
        if not result.get("ok"):
            self.set_inner_markdown_preview(f"生成失败：{result.get('error', '未知错误')}")
            return
        words = result.get("words", [])
        cfg = result.get("config", {})
        english_raw = result.get("english", "")
        chinese_text = result.get("chinese", "")
        english_clean, fallback_special = self.strip_special_markers(english_raw)
        chinese_clean, _ = self.strip_special_markers(chinese_text)
        special_words = result.get("special_words", [])
        if not isinstance(special_words, list):
            special_words = []
        if not special_words:
            special_words = fallback_special
        if special_words:
            words_lower = {w.lower(): w for w in words}
            deduped = []
            seen = set()
            for token in special_words:
                low = (token or "").strip().lower()
                if not low or low in seen:
                    continue
                seen.add(low)
                deduped.append(words_lower.get(low, token))
            special_words = deduped
        self.wordcraft_last_result = {
            "words": words,
            "config": cfg,
            "english_raw": english_raw,
            "english_clean": english_clean,
            "chinese": chinese_clean,
            "special_words": special_words,
        }
        self.update_inner_toolbar_visual()
        self.refresh_wordcraft_display()
        self.touch_words_query_time(words)
        title = f"选词成文 {datetime.now().strftime('%m-%d %H:%M')}"
        header_text = f"🔊\n【选词成文】\n词汇：{', '.join(words)}\n难度：{cfg.get('difficulty', 'CET-4')}\n\n"
        session_content = header_text + english_clean + f"\n\n【中文】\n{chinese_clean}"
        session_payload = {
            "wordcraft_config": dict(cfg),
            "wordcraft_session": {
                "words": list(words),
                "english_clean": english_clean,
                "chinese": chinese_clean,
            },
        }
        sid = self.create_inner_session(title, "wordcraft", session_content, json.dumps(session_payload, ensure_ascii=False))
        self.wordcraft_session_id = sid
        self.inner_current_session_id = sid
        self.load_inner_sessions()
        for i in range(self.inner_session_list.count()):
                item = self.inner_session_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == sid:
                    self.inner_session_list.setCurrentItem(item)
                    break
        if hasattr(self, "inner_confirm_btn"):
            self.inner_confirm_btn.setVisible(False)

    def append_wordcraft_chinese_and_save(self):
        english_clean = self.wordcraft_last_result.get("english_clean", "")
        chinese = self.wordcraft_last_result.get("chinese", "")
        cfg = self.wordcraft_last_result.get("config", {})
        words = self.wordcraft_last_result.get("words", [])
        final_text = (
            f"🔊\n【选词成文】\n词汇：{', '.join(words)}\n难度：{cfg.get('difficulty', 'CET-4')}\n\n"
            f"{english_clean}\n\n【中文】\n{chinese}"
        )
        self.set_inner_markdown_preview(final_text)
        if self.wordcraft_session_id:
            cur = self.user_conn.cursor()
            ts = datetime.now().isoformat(timespec='seconds')
            cur.execute('UPDATE inner_sessions SET content = ?, updated_at = ? WHERE id = ?', (final_text, ts, int(self.wordcraft_session_id)))
            self.user_conn.commit()
            self.load_inner_sessions()

    def on_confirm_wordcraft_segments(self):
        if not self.wordcraft_pending_confirm:
            return
        if not self.wordcraft_pending_segments:
            QMessageBox.information(self, "提示", "请先右键选择至少一段不懂片段。")
            return
        self.append_wordcraft_chinese_and_save()
        if hasattr(self, 'inner_confirm_btn'):
            self.inner_confirm_btn.setEnabled(False)
        self.run_wordcraft_explain_flow()

    def build_wordcraft_explain_prompt(self, segments, words, cfg):
        joined_segments = "\n".join([f"{idx + 1}. {s}" for idx, s in enumerate(segments)])
        return (
            "你是英语学习助手。请逐一讲解用户看不懂的英文片段。\n"
            f"原始目标词：{', '.join(words)}\n"
            f"目标难度：{cfg.get('difficulty', 'CET-4')}\n"
            f"待讲解片段：\n{joined_segments}\n\n"
            "输出要求：\n"
            "1) 按片段编号逐一解释，包含词义、语法或语境难点。\n"
            "2) 最后单独一行输出：DOWNGRADE_WORDS: w1, w2\n"
            "3) DOWNGRADE_WORDS 只从原始目标词中选 0-5 个，不要输出其它格式。"
        )

    def run_wordcraft_explain_flow(self):
        url = self.normalize_api_url(self.settings.get('api_url', ''))
        key = self.settings.get('api_key', '')
        model = self.get_high_model_name() or self.get_mid_model_name()
        if not url or not key or not model:
            QMessageBox.warning(self, "讲解失败", "AI 配置不完整：请先在设置中配置 API URL、API Key 和模型。")
            if hasattr(self, 'inner_confirm_btn'):
                self.inner_confirm_btn.setEnabled(True)
            return
        prompt = self.build_wordcraft_explain_prompt(
            self.wordcraft_pending_segments,
            self.wordcraft_last_result.get("words", []),
            self.wordcraft_last_result.get("config", {}),
        )
        threading.Thread(
            target=self._wordcraft_explain_worker,
            args=(url, key, model, prompt),
            daemon=True,
        ).start()

    def _wordcraft_explain_worker(self, url, key, model, prompt):
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "你是英语学习助手。"},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
        }
        try:
            answer = (self.request_ai_stream_text(url, key, payload, timeout=90) or "").strip()
            self.inner_tool_result_ready.emit({"ok": True, "tool": "wordcraft", "stage": "explain", "answer": answer})
        except error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8", errors="ignore")
            except Exception:
                err_body = ""
            self.inner_tool_result_ready.emit({"ok": False, "tool": "wordcraft", "stage": "explain", "error": f"HTTP {e.code} {e.reason}\n{err_body}"})
        except Exception as e:
            self.inner_tool_result_ready.emit({"ok": False, "tool": "wordcraft", "stage": "explain", "error": str(e)})

    def parse_downgrade_words(self, answer):
        line = ""
        for row in (answer or "").splitlines():
            if row.strip().upper().startswith("DOWNGRADE_WORDS:"):
                line = row.strip()
                break
        if not line:
            return []
        payload = line.split(":", 1)[-1]
        words = []
        for token in payload.split(","):
            t = token.strip()
            if t:
                words.append(t)
        return words

    def strip_downgrade_line(self, answer):
        lines = (answer or "").splitlines()
        kept = [line for line in lines if not line.strip().upper().startswith("DOWNGRADE_WORDS:")]
        return "\n".join(kept).strip()

    def on_wordcraft_explain_result(self, result):
        if hasattr(self, 'inner_confirm_btn'):
            self.inner_confirm_btn.setEnabled(True)
            self.inner_confirm_btn.setVisible(False)
        self.wordcraft_pending_confirm = False
        if not result.get("ok"):
            QMessageBox.warning(self, "讲解失败", result.get("error", "未知错误"))
            return
        answer = result.get("answer", "")
        downgrade_words = self.parse_downgrade_words(answer)
        origin_words = {w.lower(): w for w in self.wordcraft_last_result.get("words", [])}
        final_downgrade = []
        for w in downgrade_words:
            key = w.lower()
            if key in origin_words and origin_words[key] not in final_downgrade:
                final_downgrade.append(origin_words[key])
        explain_text = self.strip_downgrade_line(answer)
        if final_downgrade:
            self.shift_reviewing_proficiency(final_downgrade, -1)
        merged = self.inner_dialog_editor.toPlainText() + "\n\n【逐一讲解】\n" + explain_text
        self.set_inner_markdown_preview(merged)
        if self.wordcraft_session_id:
            cur = self.user_conn.cursor()
            ts = datetime.now().isoformat(timespec='seconds')
            cur.execute('UPDATE inner_sessions SET content = ?, updated_at = ? WHERE id = ?', (merged, ts, int(self.wordcraft_session_id)))
            self.user_conn.commit()
            self.load_inner_sessions()

    def refresh_internal_page(self):
        if hasattr(self, 'inner_favorites_list'):
            self.inner_favorites_list.clear()
            f_id = self.get_current_folder_id()
            basis = self.fav_sort_combo.currentData() if hasattr(self, 'fav_sort_combo') else "recent"
            candidates = self.get_scope_candidates("favorites", f_id)
            sorted_words = self.sort_words_by_basis(candidates, basis)
            lookup = {c[0]: c[1] for c in candidates}
            for q in sorted_words:
                last_at = lookup.get(q, "")
                dt = self.parse_iso_ts(last_at)
                rel_time = self.format_relative_time(dt) if dt else ""
                suffix = f"  [{rel_time}]" if rel_time else ""
                item = QListWidgetItem(f"{q}{suffix}")
                item.setData(Qt.ItemDataRole.UserRole, q)
                self.apply_review_style_to_item(item, q)
                self.inner_favorites_list.addItem(item)
        if hasattr(self, 'reviewing_words_list'):
            self.reviewing_words_list.clear()
            basis = self.get_reviewing_sort_basis()
            candidates = self.get_scope_candidates("reviewing", 1) # returns (q, last_at, proficiency)
            sorted_words = self.sort_words_by_basis(candidates, basis)
            # 给在背单词也加上相对于“查询时间”的显示
            lookup = {c[0]: c[1] for c in candidates}
            for q in sorted_words:
                last_at = lookup.get(q, "")
                dt = self.parse_iso_ts(last_at)
                rel_time = self.format_relative_time(dt) if dt else ""
                suffix = f"  [{rel_time}]" if rel_time else ""
                item = QListWidgetItem(f"{q}{suffix}")
                item.setData(Qt.ItemDataRole.UserRole, q)
                self.apply_review_style_to_item(item, q)
                self.reviewing_words_list.addItem(item)

    def touch_words_query_time(self, words):
        if not words:
            return
        ts = datetime.now().isoformat(timespec="seconds")
        cur = self.user_conn.cursor()
        seen = set()
        for word in words:
            token = (word or "").strip()
            low = token.lower()
            if not token or low in seen:
                continue
            seen.add(low)
            cur.execute(
                "INSERT INTO queries(query, count, last_at) VALUES(?, 1, ?) "
                "ON CONFLICT(query) DO UPDATE SET count = count + 1, last_at = excluded.last_at",
                (token, ts),
            )
        self.user_conn.commit()
        self.refresh_internal_page()

    def on_wordcraft_listen_clicked(self):
        if self.inner_active_tool != "wordcraft":
            return
        english = (self.wordcraft_last_result.get("english_clean", "") or "").strip()
        if not english and self.inner_current_session_id:
            cur = self.user_conn.cursor()
            cur.execute('SELECT content, config_json FROM inner_sessions WHERE id = ?', (int(self.inner_current_session_id),))
            row = cur.fetchone()
            if row:
                parsed = self.parse_wordcraft_session_payload(row[0] or "", row[1])
                english = (parsed.get("english_clean", "") or "").strip()
                if english:
                    self.wordcraft_last_result = parsed
        if not english:
            QMessageBox.information(self, "听力", "当前没有可朗读的英文内容。")
            return
        voice = self.settings.get("tts_voice", "en-US-GuyNeural")
        rate = self.settings.get("tts_rate", "+0%")
        get_tts_client().play(english, voice=voice, rate=rate)

    def parse_wordcraft_session_payload(self, content, config_json):
        text = (content or "").replace("\r\n", "\n")
        cfg = {}
        words = []
        english = ""
        chinese = ""
        if config_json:
            try:
                data = json.loads(config_json)
            except Exception:
                data = None
            if isinstance(data, dict):
                if isinstance(data.get("wordcraft_config"), dict):
                    cfg = dict(data.get("wordcraft_config") or {})
                elif "scope" in data or "basis" in data or "difficulty" in data:
                    cfg = dict(data)
                meta = data.get("wordcraft_session")
                if isinstance(meta, dict):
                    english = (meta.get("english_clean", "") or "").strip()
                    chinese = (meta.get("chinese", "") or "").strip()
                    raw_words = meta.get("words", [])
                    if isinstance(raw_words, list):
                        words = [str(x).strip() for x in raw_words if str(x).strip()]
        lines = text.split("\n")
        if lines and lines[0].strip().startswith("🔊"):
            lines = lines[1:]
        for line in lines:
            if line.startswith("词汇：") and not words:
                words = [w.strip() for w in line.split("：", 1)[-1].split(",") if w.strip()]
            if line.startswith("难度：") and not cfg.get("difficulty"):
                cfg["difficulty"] = line.split("：", 1)[-1].strip() or cfg.get("difficulty", "CET-4")
        joined = "\n".join(lines)
        if not english:
            parts = joined.split("【中文】", 1)
            before = parts[0].strip() if parts else ""
            if before:
                before_lines = []
                for line in before.splitlines():
                    token = line.strip()
                    if token.startswith("【选词成文】") or token.startswith("词汇：") or token.startswith("难度："):
                        continue
                    before_lines.append(line)
                english = "\n".join(before_lines).strip()
        if not chinese and "【中文】" in joined:
            after = joined.split("【中文】", 1)[-1]
            chinese = after.split("【逐一讲解】", 1)[0].strip()
        return {
            "config": cfg,
            "words": words,
            "english_clean": english,
            "chinese": chinese,
            "special_words": [],
        }

    def build_favorite_option_button(self):
        option_btn = QToolButton()
        option_btn.setText("▾")
        option_btn.setFixedHeight(32)
        option_btn.setFixedWidth(30)
        option_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(option_btn)
        act_default = menu.addAction("默认收藏（当前文件夹）")
        act_default.triggered.connect(self.toggle_favorite_current)
        act_ai = menu.addAction("AI 推荐收藏夹并收藏")
        act_ai.triggered.connect(self.on_ai_smart_favorite_clicked)
        option_btn.setMenu(menu)
        return option_btn

    def lookup_dictionary_word_exact(self, raw_word):
        text = (raw_word or "").strip()
        if not text:
            return None
        self.cursor.execute("SELECT word FROM stardict WHERE word = ? COLLATE NOCASE LIMIT 1", (text,))
        row = self.cursor.fetchone()
        return row[0] if row else None

    def normalize_link_pair(self, left_word, right_word):
        if left_word.lower() <= right_word.lower():
            return left_word, right_word
        return right_word, left_word

    def add_word_link(self, current_word, linked_word):
        word_a, word_b = self.normalize_link_pair(current_word, linked_word)
        ts = datetime.now().isoformat(timespec='seconds')
        cur = self.user_conn.cursor()
        cur.execute('INSERT OR IGNORE INTO word_links(word_a, word_b, created_at) VALUES(?, ?, ?)', (word_a, word_b, ts))
        self.user_conn.commit()

    def delete_word_link(self, current_word, linked_word):
        word_a, word_b = self.normalize_link_pair(current_word, linked_word)
        cur = self.user_conn.cursor()
        cur.execute('DELETE FROM word_links WHERE word_a = ? COLLATE NOCASE AND word_b = ? COLLATE NOCASE', (word_a, word_b))
        self.user_conn.commit()

    def get_word_links(self, current_word):
        cur = self.user_conn.cursor()
        cur.execute('SELECT word_a, word_b FROM word_links WHERE word_a = ? COLLATE NOCASE OR word_b = ? COLLATE NOCASE ORDER BY id DESC', (current_word, current_word))
        links = []
        seen = set()
        for a, b in cur.fetchall():
            linked = b if a.lower() == current_word.lower() else a
            key = linked.lower()
            if key in seen:
                continue
            seen.add(key)
            links.append(linked)
        links.sort(key=lambda x: x.lower())
        return links

    def build_words_link_section(self, word):
        title = QLabel("words link")
        title.setFont(title.font())
        title.setStyleSheet('color: #61dafb; margin-top: 15px; margin-bottom: 5px;')
        self.detail_info_layout.addWidget(title)
        add_row = QWidget()
        add_layout = QHBoxLayout()
        add_layout.setContentsMargins(0, 0, 0, 0)
        add_row.setLayout(add_layout)
        self.word_link_input = QLineEdit()
        self.word_link_input.setPlaceholderText("输入要关联的词")
        add_layout.addWidget(self.word_link_input)
        add_btn = QPushButton("添加关联")
        add_btn.clicked.connect(self.on_add_word_link_clicked)
        add_layout.addWidget(add_btn)
        self.ai_link_suggest_btn = QPushButton("AI 推荐关联词")
        self.ai_link_suggest_btn.clicked.connect(self.on_ai_suggest_links_clicked)
        add_layout.addWidget(self.ai_link_suggest_btn)
        self.detail_info_layout.addWidget(add_row)
        self.word_links_browser = QTextBrowser()
        self.word_links_browser.setOpenLinks(False)
        self.word_links_browser.setOpenExternalLinks(False)
        self.word_links_browser.anchorClicked.connect(self.on_word_link_clicked)
        self.word_links_browser.setMinimumHeight(120)
        self.word_links_browser.setMaximumHeight(220)
        self.word_links_browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.detail_info_layout.addWidget(self.word_links_browser)
        self.refresh_words_link_view(word)

    def refresh_words_link_view(self, word):
        if not hasattr(self, 'word_links_browser'):
            return
        links = self.get_word_links(word)
        if not links:
            self.word_links_browser.setHtml("<div style='color:#888;'>暂无关联词，可手动添加。</div>")
            return
        rows = []
        for linked_word in links:
            token = html.escape(linked_word)
            go_href = html.escape(f"go:{quote(linked_word, safe='')}", quote=True)
            del_href = html.escape(f"del:{quote(linked_word, safe='')}", quote=True)
            if self.is_in_review(linked_word):
                token = f"<span style='background-color:#6b4f00;color:#ffe9a8;border-radius:3px;padding:1px 4px;'>{token}</span>"
            rows.append(
                "<tr>"
                f"<td style='padding:6px;border:1px solid #3d3d3d;'><a href='{go_href}'>{token}</a></td>"
                f"<td style='padding:6px;border:1px solid #3d3d3d;text-align:center;'><a href='{del_href}' style='color:#e06c75;'>删除</a></td>"
                "</tr>"
            )
        table_html = "<table style='border-collapse:collapse;width:100%;'><tr><th style='text-align:left;padding:6px;border:1px solid #3d3d3d;'>关联词</th><th style='text-align:center;padding:6px;border:1px solid #3d3d3d;'>操作</th></tr>" + "".join(rows) + "</table>"
        self.word_links_browser.setHtml(table_html)

    def on_add_word_link_clicked(self):
        if not self.current_query or not hasattr(self, 'word_link_input'):
            return
        current_word = self.lookup_dictionary_word_exact(self.current_query)
        if not current_word:
            QMessageBox.warning(self, "添加关联失败", "当前词条不在词库中，无法建立关联。")
            return
        target_raw = self.word_link_input.text().strip()
        target_word = self.lookup_dictionary_word_exact(target_raw)
        if not target_word:
            QMessageBox.warning(self, "添加关联失败", "目标词在词库中未找到，请输入词库里的完整词条。")
            return
        if current_word.lower() == target_word.lower():
            QMessageBox.warning(self, "添加关联失败", "不能把一个词关联到自己。")
            return
        self.add_word_link(current_word, target_word)
        self.word_link_input.clear()
        self.refresh_words_link_view(current_word)

    def on_word_link_clicked(self, link_url):
        raw_target = link_url.toString() if hasattr(link_url, "toString") else str(link_url)
        payload = (raw_target or "").strip()
        if not payload:
            return
        if payload.startswith("del:"):
            linked_word = unquote(payload[4:].strip())
            current_word = self.lookup_dictionary_word_exact(self.current_query)
            if current_word and linked_word:
                self.delete_word_link(current_word, linked_word)
                self.refresh_words_link_view(current_word)
            return
        target_payload = payload[3:] if payload.startswith("go:") else payload
        target = unquote(target_payload).strip().strip("/")
        if "://" in target:
            target = target.split("://", 1)[-1].strip().strip("/")
        if not target:
            return
        resolved = self.lookup_dictionary_word_exact(target) or self.find_unique_dictionary_word(target) or target
        self.search_input.setText(resolved)
        QTimer.singleShot(0, lambda w=resolved: self.safe_navigate_to_linked_word(w))

    def on_import_txt_clicked(self, file_path=None):
        if not file_path:
            file_path, _ = QFileDialog.getOpenFileName(self, "选择单词本", "", "Text Files (*.txt);;All Files (*)")
        if not file_path:
            return
        
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        cur = self.user_conn.cursor()
        
        # 查找可用文件夹名称（处理重名）
        cur.execute('SELECT id FROM folders WHERE name = ?', (base_name,))
        if not cur.fetchone():
            final_name = base_name
        else:
            i = 1
            while True:
                candidate = f"{base_name}({i})"
                cur.execute('SELECT id FROM folders WHERE name = ?', (candidate,))
                if not cur.fetchone():
                    final_name = candidate
                    break
                i += 1

        # 创建文件夹
        cur.execute('INSERT INTO folders(name) VALUES(?)', (final_name,))
        f_id = cur.rowcount and cur.lastrowid
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            
            ts = datetime.now().isoformat(timespec='seconds')
            added = 0
            for line in lines:
                raw_line = line.strip()
                if not raw_line:
                    continue
                # 提取每行开头的第一个单词/短语
                # 如果是 "apple - adj. 苹果"，提取 "apple"
                # 如果是 "stand up for", 且没有后续备注，提取整行
                parts = raw_line.split(None, 1)
                word = parts[0]
                if word:
                    # 简单清理末尾符号
                    word = word.strip('.,;:!?')
                    if word:
                        cur.execute('INSERT OR IGNORE INTO favorites(query, folder_id, created_at) VALUES(?, ?, ?)', (word, f_id, ts))
                        if cur.rowcount > 0:
                            added += 1
            
            self.user_conn.commit()
            QMessageBox.information(self, "引泾成功", f"文件：{base_name}\n已创建文件夹：{final_name}\n新增条目：{added}")
            # 如果提供了 load_favorites_list 就刷新界面
            if hasattr(self, 'load_favorites_list'):
                self.load_favorites_list()
        except Exception as e:
            QMessageBox.warning(self, "引泾失败", f"处理外部词库时报错：{str(e)}")

    def on_import_ai_clicked(self, file_path=None):
        """AI 智能解析：读取文件样本 -> AI 分析结构 -> 生成提取代码 -> 执行并导入"""
        if not file_path:
            file_path, _ = QFileDialog.getOpenFileName(self, "选择任意格式词库文件", "", "All Files (*)")
        if not file_path:
            return
        url = self.normalize_api_url(self.settings.get('api_url', ''))
        key = self.settings.get('api_key', '')
        model = self.get_high_model_name() or self.get_mid_model_name()
        if not url or not key or not model:
            QMessageBox.warning(self, "AI 配置不完整", "请先在设置中配置 API URL、API Key 和模型名。")
            return
        # 读取文件样本（前 500 字符）
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                sample = f.read(500)
        except Exception as e:
            QMessageBox.warning(self, "读取失败", f"无法读取文件：{str(e)}")
            return
        if not sample.strip():
            QMessageBox.warning(self, "文件为空", "所选文件没有可读内容。")
            return
        if hasattr(self, 'import_status_label'):
            self.import_status_label.setText("⏳ [1/4] 正在准备并启动后台任务...")
            self.import_status_label.setStyleSheet('color: #61dafb;')
        print(f"[AI Import] 发起后台解析线程: {file_path}")
        if hasattr(self, 'import_ai_btn'):
            self.import_ai_btn.setEnabled(False)
            
        # 确保 helper 跨线程可用
        if not hasattr(self, '_ai_import_signal_helper'):
            self._ai_import_signal_helper = _AIImportSignalHelper()
            self._ai_import_signal_helper.update_status.connect(self._set_import_status_text)
            self._ai_import_signal_helper.finish.connect(self._ai_import_finish)
            self._ai_import_signal_helper.save_data.connect(self._ai_import_save)
            
        helper = self._ai_import_signal_helper
            
        threading.Thread(
            target=self._ai_import_worker,
            args=(url, key, model, file_path, sample, helper),
            daemon=True
        ).start()

    def _ai_import_worker(self, url, key, model, file_path, sample, helper):
        try:
            print("[AI Import] [DEBUG] 线程运行中，开始构建 Prompt")
            helper.update_status.emit("⏳ [1/4] 正在构建 AI 提示词与请求...")
            
            prompt = (
                "你是一个文件解析助手。用户给你一个文件的前 500 字符样本，你需要分析这个文件的存储结构，"
                "然后写出一段 Python 代码来提取其中所有的英语单词或短语。\n\n"
                "**要求：**\n"
                "1. 你的回复中必须包含且仅包含一个 Python 代码块（用 ```python ... ``` 包裹）\n"
                "2. 代码必须定义一个函数 `extract_words(file_path: str) -> list[str]`\n"
                "3. 该函数接收完整的文件路径，返回一个字符串列表，每个元素是一个英语单词或短语\n"
                "4. 不要导入任何第三方库，只用 Python 标准库（如 re, csv, json, xml 等）\n"
                "5. 尽可能智能地识别文件结构，提取出所有英语词汇/短语，去除重复\n"
                "6. 如果文件中有中文释义、音标等附加信息，只提取英文单词部分\n\n"
                f"**文件名：** {os.path.basename(file_path)}\n\n"
                f"**文件样本（前 500 字符）：**\n```\n{sample}\n```"
            )
            print("[AI Import] [DEBUG] Prompt 构建成功")
            
            messages = [
                {"role": "system", "content": "你是一个精通文件格式解析的 Python 编程助手。只用代码块回答，不要多余解释。"},
                {"role": "user", "content": prompt}
            ]
            
            print("[AI Import] [DEBUG] 正在构造 Payload")
            payload = {"model": model, "messages": messages, "temperature": 0.1}
            
            helper.update_status.emit("⏳ [2/4] 正在等待 AI 响应（可能需要 10~30 秒）...")
            print("[AI Import] [DEBUG] 正在执行流式请求...")
            answer = (self.request_ai_stream_text(url, key, payload, timeout=120) or "").strip()
            
            print(f"[AI Import] [DEBUG] AI 原始响应长度: {len(answer)}")
            if not answer:
                print("[AI Import] [DEBUG] 响应为空，终止并提示")
                helper.finish.emit(False, "AI 未返回内容", file_path)
                return
            
            print("[AI Import] [DEBUG] 开始提取代码块")
            helper.update_status.emit("⏳ [3/4] AI 已响应，正在提取代码并执行...")
            code = self._extract_code_block(answer)
            
            if not code:
                print("[AI Import] [DEBUG] 未提取到有效的 Python 代码块")
                helper.finish.emit(False, f"AI 未返回有效的 Python 代码块。\n\nAI 原文：\n{answer[:500]}", file_path)
                return
                
            print(f"[AI Import] [DEBUG] 提取到代码，长度: {len(code)}\n--- AI 回复代码 ---\n{code}\n-------------------")
            print("[AI Import] [DEBUG] 开始在沙箱中执行文件提取逻辑")
            words = self._execute_extract_code(code, file_path)
            
            if words is None:
                print("[AI Import] [DEBUG] 沙箱执行失败 (返回了 None)")
                helper.finish.emit(False, "AI 生成的代码执行失败，请重试。", file_path)
                return
                
            print(f"[AI Import] [DEBUG] 沙箱执行成功，识别单词列表长度: {len(words)}")
            if not words:
                print("[AI Import] [DEBUG] 单词列表为空")
                helper.finish.emit(False, "AI 解析后未提取到任何单词。", file_path)
                return
                
            print("[AI Import] [DEBUG] 开始将单词写入收藏夹 (转主线程)")
            helper.update_status.emit(f"⏳ [4/4] 提取到 {len(words)} 个单词，正在写入收藏夹...")
            helper.save_data.emit(file_path, words)
            print("[AI Import] [DEBUG] 后台线程工作全量完成")
            
        except Exception as e:
            import traceback
            trace_str = traceback.format_exc()
            print(f"[AI Import] [ERROR] 线程异常:\n{trace_str}")
            helper.finish.emit(False, f"AI 导入异常：{type(e).__name__}: {str(e)}", file_path)



    def _set_import_status_text(self, text):
        if hasattr(self, 'import_status_label'):
            self.import_status_label.setText(text)
            self.import_status_label.setStyleSheet('color: #61dafb;')

    def _extract_code_block(self, text):
        m = re.search(r'```python\s*\n(.*?)```', text, re.DOTALL)
        if m:
            return m.group(1).strip()
        m2 = re.search(r'```\s*\n(.*?)```', text, re.DOTALL)
        if m2:
            return m2.group(1).strip()
        return None

    def _execute_extract_code(self, code, file_path):
        try:
            namespace = {}
            exec(code, namespace)
            extract_fn = namespace.get('extract_words')
            if not callable(extract_fn):
                return None
            result = extract_fn(file_path)
            if not isinstance(result, list):
                return None
            cleaned = []
            seen = set()
            for item in result:
                w = str(item).strip()
                if not w:
                    continue
                key = w.lower()
                if key not in seen:
                    seen.add(key)
                    cleaned.append(w)
            return cleaned
        except Exception as e:
            print(f"[AI Import] 代码执行出错: {e}")
            return None

    def _ai_import_save(self, file_path, words):
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        cur = self.user_conn.cursor()
        cur.execute('SELECT id FROM folders WHERE name = ?', (base_name,))
        if not cur.fetchone():
            final_name = base_name
        else:
            i = 1
            while True:
                candidate = f"{base_name}({i})"
                cur.execute('SELECT id FROM folders WHERE name = ?', (candidate,))
                if not cur.fetchone():
                    final_name = candidate
                    break
                i += 1
        cur.execute('INSERT INTO folders(name) VALUES(?)', (final_name,))
        f_id = cur.lastrowid
        ts = datetime.now().isoformat(timespec='seconds')
        added = 0
        for word in words:
            cur.execute('INSERT OR IGNORE INTO favorites(query, folder_id, created_at) VALUES(?, ?, ?)', (word, f_id, ts))
            if cur.rowcount > 0:
                added += 1
        self.user_conn.commit()
        if hasattr(self, 'load_favorites_list'):
            self.load_favorites_list()
        self._ai_import_finish(True, f"AI 智能解析成功！\n文件：{base_name}\n已创建文件夹：{final_name}\n识别单词：{len(words)} 个\n新增条目：{added} 个", file_path)

    def _ai_import_finish(self, success, message, file_path):
        if hasattr(self, 'import_status_label'):
            color = '#98c379' if success else '#e06c75'
            self.import_status_label.setText(message)
            self.import_status_label.setStyleSheet(f'color: {color};')
        if hasattr(self, 'import_ai_btn'):
            self.import_ai_btn.setEnabled(True)
        if not success:
            QMessageBox.warning(self, "AI 智能解析", message)

    def _normalize_doc_note_path(self, file_path):
        return os.path.abspath(file_path or "").strip()

    def _project_root_dir(self):
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _get_doc_personal_dir(self):
        target_dir = os.path.join(self._project_root_dir(), "personal_files", "markdown_docs")
        os.makedirs(target_dir, exist_ok=True)
        return target_dir

    def _read_markdown_file(self, file_path):
        with open(file_path, "r", encoding="utf-8", errors="strict") as f:
            return f.read()

    def refresh_doc_markdown_file_list(self):
        if not hasattr(self, "doc_files_list"):
            return
        file_list = self.doc_files_list
        file_list.blockSignals(True)
        file_list.clear()
        base_dir = self._get_doc_personal_dir()
        entries = []
        for root, _, files in os.walk(base_dir):
            for name in files:
                if not name.lower().endswith(".md"):
                    continue
                abs_path = self._normalize_doc_note_path(os.path.join(root, name))
                rel_path = os.path.relpath(abs_path, base_dir)
                entries.append((rel_path.replace("\\", "/"), abs_path))
        entries.sort(key=lambda x: x[0].lower())
        current_path = self._normalize_doc_note_path(getattr(self, "current_doc_reader_path", ""))
        current_row = -1
        for idx, (rel_path, abs_path) in enumerate(entries):
            item = QListWidgetItem(rel_path)
            item.setData(Qt.ItemDataRole.UserRole, abs_path)
            item.setToolTip(abs_path)
            file_list.addItem(item)
            if current_path and abs_path.lower() == current_path.lower():
                current_row = idx
        if current_row >= 0:
            file_list.setCurrentRow(current_row)
        file_list.blockSignals(False)

    def on_doc_file_item_activated(self, item):
        if item is None:
            return
        file_path = item.data(Qt.ItemDataRole.UserRole)
        if not file_path:
            return
        self.on_import_document_clicked(file_path)

    def update_doc_markdown_preview(self):
        if not hasattr(self, "doc_content_edit") or not hasattr(self, "doc_md_preview"):
            return
        md = self.doc_content_edit.toPlainText()
        html_fragment = self.markdown_to_html_fragment(md)
        self.doc_md_preview.setHtml(html_fragment)

    def on_doc_mode_preview_clicked(self):
        self.update_doc_markdown_preview()
        if hasattr(self, "doc_content_stack") and hasattr(self, "doc_md_preview"):
            self.doc_content_stack.setCurrentWidget(self.doc_md_preview)

    def on_doc_mode_edit_clicked(self):
        if hasattr(self, "doc_content_stack") and hasattr(self, "doc_content_edit"):
            self.doc_content_stack.setCurrentWidget(self.doc_content_edit)
            self.doc_content_edit.setFocus()

    def on_doc_preview_mouse_press(self, event):
        handler = getattr(self.doc_md_preview, "_orig_mouse_press", None) if hasattr(self, "doc_md_preview") else None
        if handler is not None:
            handler(event)

    def on_doc_preview_double_click(self, event):
        self.on_doc_mode_edit_clicked()
        handler = getattr(self.doc_md_preview, "_orig_mouse_double_click", None) if hasattr(self, "doc_md_preview") else None
        if handler is not None:
            handler(event)

    def on_doc_content_text_changed(self):
        self.update_doc_markdown_preview()
        self.apply_doc_annotation_highlights()

    def on_doc_selection_changed(self):
        if not hasattr(self, "doc_content_edit"):
            return
        cursor = self.doc_content_edit.textCursor()
        selected = (cursor.selectedText() or "").replace("\u2029", "\n").strip()
        if not selected:
            self.doc_last_selected_text = ""
            self.doc_last_selection_start = -1
            self.doc_last_selection_end = -1
            self.doc_auto_ai_last_signature = None
            return
        start_pos = min(cursor.selectionStart(), cursor.selectionEnd())
        end_pos = max(cursor.selectionStart(), cursor.selectionEnd())
        self.doc_last_selected_text = selected
        self.doc_last_selection_start = start_pos
        self.doc_last_selection_end = end_pos
        self._queue_doc_auto_ai_annotation("edit", selected, start_pos, end_pos)

    def on_doc_preview_selection_changed(self):
        if not hasattr(self, "doc_md_preview"):
            return
        if hasattr(self, "doc_content_stack") and self.doc_content_stack.currentWidget() is not self.doc_md_preview:
            return
        cursor = self.doc_md_preview.textCursor()
        selected = (cursor.selectedText() or "").replace("\u2029", "\n").strip()
        if not selected:
            self.doc_auto_ai_last_signature = None
            return
        self._queue_doc_auto_ai_annotation("preview", selected, -1, -1)

    def _queue_doc_auto_ai_annotation(self, source, selected_text, start_pos, end_pos):
        selected = (selected_text or "").strip()
        if not selected:
            return
        signature = (
            source,
            self._normalize_doc_note_path(getattr(self, "current_doc_reader_path", "")),
            selected,
            int(start_pos),
            int(end_pos),
        )
        self.doc_auto_ai_pending = {
            "source": source,
            "selected": selected,
            "start_pos": int(start_pos),
            "end_pos": int(end_pos),
            "signature": signature,
        }
        timer = getattr(self, "doc_auto_ai_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._fire_doc_auto_ai_annotation)
            self.doc_auto_ai_timer = timer
        timer.start(520)

    def _resolve_doc_selection_range(self, selected_text):
        if not hasattr(self, "doc_content_edit"):
            return -1, -1
        selected = (selected_text or "").strip()
        if not selected:
            return -1, -1
        text = self.doc_content_edit.toPlainText()
        if not text:
            return -1, -1
        idx = text.find(selected)
        if idx >= 0:
            return idx, idx + len(selected)

        # 预览区选中内容可能在空白字符上与编辑区不一致，这里做一次“空白归一化”匹配。
        def normalize_with_map(raw):
            out = []
            pos_map = []
            i = 0
            n = len(raw)
            while i < n:
                ch = raw[i]
                if ch.isspace():
                    out.append(" ")
                    pos_map.append(i)
                    while i < n and raw[i].isspace():
                        i += 1
                    continue
                out.append(ch)
                pos_map.append(i)
                i += 1
            pos_map.append(n)
            return "".join(out), pos_map

        norm_text, text_map = normalize_with_map(text)
        norm_sel, _ = normalize_with_map(selected)
        norm_sel = norm_sel.strip()
        if not norm_sel:
            return -1, -1
        norm_idx = norm_text.find(norm_sel)
        if norm_idx < 0:
            return -1, -1
        start = text_map[norm_idx]
        end_norm = norm_idx + len(norm_sel)
        if end_norm >= len(text_map):
            end = len(text)
        else:
            end = text_map[end_norm]
        if end <= start:
            end = min(len(text), start + len(selected))
        return start, end

    def _build_doc_annotation_context(self, selected_text, start_pos, end_pos):
        if not hasattr(self, "doc_content_edit"):
            return (selected_text or "").strip()
        full_text = self.doc_content_edit.toPlainText() or ""
        token = (selected_text or "").strip()
        if not full_text:
            return token
        try:
            start = int(start_pos)
            end = int(end_pos)
        except Exception:
            start, end = -1, -1
        if start < 0 or end <= start:
            start, end = self._resolve_doc_selection_range(token)
        if start < 0 or end <= start:
            return token
        start = max(0, min(start, len(full_text)))
        end = max(start + 1, min(end, len(full_text)))
        window = 420
        left = max(0, start - window)
        right = min(len(full_text), end + window)
        left_line = full_text.rfind("\n", 0, left)
        if left_line >= 0:
            left = left_line + 1
        right_line = full_text.find("\n", right)
        if right_line >= 0:
            right = right_line
        context = full_text[left:right].strip()
        if not context:
            context = token
        return context

    def _fire_doc_auto_ai_annotation(self):
        pending = getattr(self, "doc_auto_ai_pending", None) or {}
        if not pending:
            return
        if getattr(self, "doc_auto_ai_dialog_open", False):
            return
        if QApplication.mouseButtons() & Qt.MouseButton.LeftButton:
            timer = getattr(self, "doc_auto_ai_timer", None)
            if timer is not None:
                timer.start(260)
            return
        signature = pending.get("signature")
        if signature and signature == getattr(self, "doc_auto_ai_last_signature", None):
            return
        selected = (pending.get("selected") or "").strip()
        if not selected:
            return
        start_pos = int(pending.get("start_pos", -1))
        end_pos = int(pending.get("end_pos", -1))
        if start_pos < 0 or end_pos <= start_pos:
            start_pos, end_pos = self._resolve_doc_selection_range(selected)
        self.doc_auto_ai_last_signature = signature
        self.on_doc_ai_explain_clicked(
            use_selection=True,
            selected_override=selected,
            start_pos_override=start_pos,
            end_pos_override=end_pos,
            silent_when_no_selection=True,
        )

    def on_doc_edit_focus_out(self, event):
        QTextEdit.focusOutEvent(self.doc_content_edit, event)
        if getattr(self, "doc_auto_ai_dialog_open", False):
            return
        if hasattr(self, "doc_content_stack") and hasattr(self, "doc_md_preview"):
            self.on_doc_mode_preview_clicked()

    def _highlight_text_brush_color(self):
        if hasattr(self, "colors"):
            return QColor(self.colors.get("highlight_bg", "#6b4f00"))
        return QColor("#6b4f00")

    def _doc_annotation_text_color(self):
        if hasattr(self, "colors"):
            return QColor(self.colors.get("highlight_text", "#ffe9a8"))
        return QColor("#ffe9a8")

    def _build_doc_annotation_cache(self, text):
        file_path = self._normalize_doc_note_path(getattr(self, "current_doc_reader_path", ""))
        cache = []
        if not file_path:
            return cache
        if not text:
            return cache
        for row in self.get_doc_annotations(file_path):
            start_pos = int(row.get("start_pos", -1))
            end_pos = int(row.get("end_pos", -1))
            selected_text = row.get("selected_text", "")
            annotation = row.get("annotation", "")
            if selected_text and start_pos >= 0 and end_pos > start_pos and end_pos <= len(text) and text[start_pos:end_pos] == selected_text:
                resolved_start = start_pos
                resolved_end = end_pos
            else:
                found_at = text.find(selected_text)
                if found_at < 0:
                    continue
                resolved_start = found_at
                resolved_end = found_at + len(selected_text)
            cache.append(
                {
                    "id": int(row.get("id", 0)) if row.get("id") is not None else 0,
                    "start_pos": resolved_start,
                    "end_pos": resolved_end,
                    "selected_text": selected_text,
                    "annotation": annotation,
                    "created_at": row.get("created_at", "") or "",
                }
            )
        return cache

    def _build_doc_extra_selections(self, target_widget, rows):
        out = []
        for row in rows:
            start_pos = int(row.get("start_pos", -1))
            end_pos = int(row.get("end_pos", -1))
            if start_pos < 0 or end_pos <= start_pos:
                continue
            cursor = target_widget.textCursor()
            cursor.setPosition(start_pos)
            cursor.setPosition(end_pos, QTextCursor.MoveMode.KeepAnchor)
            sel = QTextEdit.ExtraSelection()
            sel.cursor = cursor
            sel.format.setUnderlineStyle(sel.format.UnderlineStyle.SingleUnderline)
            sel.format.setUnderlineColor(self._highlight_text_brush_color())
            bg = QColor(self._highlight_text_brush_color())
            bg.setAlpha(110)
            sel.format.setBackground(bg)
            sel.format.setForeground(self._doc_annotation_text_color())
            out.append(sel)
        return out

    def _get_doc_annotation_by_pos(self, pos):
        for row in getattr(self, "doc_annotation_cache", []) or []:
            start_pos = int(row.get("start_pos", -1))
            end_pos = int(row.get("end_pos", -1))
            if start_pos <= pos < end_pos:
                return row
        return None

    def _show_doc_annotation_tooltip(self, global_pos, row):
        if not row:
            self.doc_last_tooltip_key = None
            return
        key = (
            int(row.get("start_pos", -1)),
            int(row.get("end_pos", -1)),
            (row.get("selected_text", "") or "").strip(),
        )
        if key == getattr(self, "doc_last_tooltip_key", None):
            return
        self.open_doc_annotation_window(row=row, global_pos=global_pos)
        self.doc_last_tooltip_key = key

    def on_doc_edit_mouse_move(self, event):
        handler = getattr(self.doc_content_edit, "_orig_mouse_move", None) if hasattr(self, "doc_content_edit") else None
        if handler is not None:
            handler(event)
        if not hasattr(self, "doc_content_edit"):
            return
        cursor = self.doc_content_edit.cursorForPosition(event.pos())
        pos = cursor.position()
        row = self._get_doc_annotation_by_pos(pos)
        self._show_doc_annotation_tooltip(self.doc_content_edit.mapToGlobal(event.pos()), row)

    def on_doc_edit_leave(self, event):
        handler = getattr(self.doc_content_edit, "_orig_leave_event", None) if hasattr(self, "doc_content_edit") else None
        if handler is not None:
            handler(event)
        self.doc_last_tooltip_key = None

    def _get_doc_annotation_by_preview_word(self, word):
        token = (word or "").strip().lower()
        if not token:
            return None
        for row in getattr(self, "doc_annotation_cache", []) or []:
            selected_text = (row.get("selected_text", "") or "").lower()
            if token in selected_text:
                return row
        return None

    def on_doc_preview_mouse_move(self, event):
        handler = getattr(self.doc_md_preview, "_orig_mouse_move", None) if hasattr(self, "doc_md_preview") else None
        if handler is not None:
            handler(event)
        if not hasattr(self, "doc_md_preview"):
            return
        cursor = self.doc_md_preview.cursorForPosition(event.pos())
        row = None
        pos = cursor.position()
        for item in getattr(self, "doc_preview_annotation_cache", []) or []:
            start_pos = int(item.get("start_pos", -1))
            end_pos = int(item.get("end_pos", -1))
            if start_pos <= pos < end_pos:
                row = item
                break
        self._show_doc_annotation_tooltip(self.doc_md_preview.mapToGlobal(event.pos()), row)

    def on_doc_preview_leave(self, event):
        handler = getattr(self.doc_md_preview, "_orig_leave_event", None) if hasattr(self, "doc_md_preview") else None
        if handler is not None:
            handler(event)
        self.doc_last_tooltip_key = None

    def get_doc_annotations(self, file_path):
        if not file_path:
            return []
        cur = self.user_conn.cursor()
        cur.execute(
            "SELECT id, start_pos, end_pos, selected_text, annotation, created_at, updated_at FROM doc_annotations "
            "WHERE file_path = ? ORDER BY id DESC",
            (file_path,),
        )
        rows = cur.fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "id": int(r[0]),
                    "start_pos": int(r[1]),
                    "end_pos": int(r[2]),
                    "selected_text": r[3] or "",
                    "annotation": r[4] or "",
                    "created_at": r[5] or "",
                    "updated_at": r[6] or "",
                }
            )
        return out

    def apply_doc_annotation_highlights(self):
        if not hasattr(self, "doc_content_edit"):
            return
        file_path = self._normalize_doc_note_path(getattr(self, "current_doc_reader_path", ""))
        if not file_path:
            self.doc_annotation_cache = []
            self.doc_preview_annotation_cache = []
            self.doc_content_edit.setExtraSelections([])
            if hasattr(self, "doc_md_preview"):
                self.doc_md_preview.setExtraSelections([])
            return
        edit_text = self.doc_content_edit.toPlainText()
        self.doc_annotation_cache = self._build_doc_annotation_cache(edit_text)
        self.doc_content_edit.setExtraSelections(self._build_doc_extra_selections(self.doc_content_edit, self.doc_annotation_cache))
        if hasattr(self, "doc_md_preview"):
            preview_text = self.doc_md_preview.toPlainText()
            self.doc_preview_annotation_cache = self._build_doc_annotation_cache(preview_text)
            self.doc_md_preview.setExtraSelections(self._build_doc_extra_selections(self.doc_md_preview, self.doc_preview_annotation_cache))

    def on_import_document_clicked(self, file_path=None):
        if not file_path:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "选择 Markdown 文档",
                "",
                "Markdown Files (*.md)",
            )
        if not file_path:
            return
        if not file_path.lower().endswith(".md"):
            QMessageBox.warning(self, "导入文档失败", "析文仅支持 .md 文件。")
            return
        try:
            src_abs = self._normalize_doc_note_path(file_path)
            personal_dir = self._get_doc_personal_dir()
            base_name = os.path.basename(src_abs)
            target_path = os.path.join(personal_dir, base_name)
            if os.path.abspath(src_abs).lower() != os.path.abspath(target_path).lower():
                name, ext = os.path.splitext(base_name)
                candidate = target_path
                idx = 1
                while os.path.exists(candidate):
                    candidate = os.path.join(personal_dir, f"{name}_{idx}{ext}")
                    idx += 1
                shutil.copy2(src_abs, candidate)
                target_path = candidate
            text = self._read_markdown_file(target_path)
        except Exception as e:
            QMessageBox.warning(self, "导入文档失败", f"无法解析文档：{str(e)}")
            return
        if not text.strip():
            QMessageBox.warning(self, "导入文档失败", "文档内容为空或不可读。")
            return
        normalized_path = self._normalize_doc_note_path(target_path)
        self.current_doc_reader_path = normalized_path
        self.current_doc_reader_text = text
        if hasattr(self, "doc_current_path_label"):
            self.doc_current_path_label.setText(f"当前文档：{normalized_path}")
        if hasattr(self, "doc_content_edit"):
            self.doc_content_edit.setPlainText(text)
        self.update_doc_markdown_preview()
        self.apply_doc_annotation_highlights()
        self.refresh_doc_markdown_file_list()
        self.on_doc_mode_preview_clicked()

    def on_doc_create_markdown_clicked(self):
        base_dir = self._get_doc_personal_dir()
        default_name = "untitled.md"
        name, ok = QInputDialog.getText(self, "新建 Markdown", "请输入新文件名（.md）：", text=default_name)
        if not ok:
            return
        file_name = (name or "").strip()
        if not file_name:
            QMessageBox.information(self, "提示", "文件名不能为空。")
            return
        if re.search(r'[<>:"/\\|?*]', file_name):
            QMessageBox.warning(self, "新建失败", "文件名包含非法字符：<>:\"/\\|?*")
            return
        if not file_name.lower().endswith(".md"):
            file_name += ".md"
        target_path = self._normalize_doc_note_path(os.path.join(base_dir, file_name))
        if os.path.exists(target_path):
            overwrite = QMessageBox.question(
                self,
                "文件已存在",
                f"文件已存在，是否覆盖？\n{target_path}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if overwrite != QMessageBox.StandardButton.Yes:
                return
        template = f"# {os.path.splitext(file_name)[0]}\n\n"
        try:
            with open(target_path, "w", encoding="utf-8", errors="strict") as f:
                f.write(template)
        except Exception as e:
            QMessageBox.warning(self, "新建失败", f"无法创建 Markdown：{str(e)}")
            return
        self.current_doc_reader_path = target_path
        self.current_doc_reader_text = template
        if hasattr(self, "doc_current_path_label"):
            self.doc_current_path_label.setText(f"当前文档：{target_path}")
        if hasattr(self, "doc_content_edit"):
            self.doc_content_edit.setPlainText(template)
        self.update_doc_markdown_preview()
        self.apply_doc_annotation_highlights()
        self.refresh_doc_markdown_file_list()
        self.on_doc_mode_edit_clicked()

    def on_doc_content_context_menu(self, pos):
        if not hasattr(self, "doc_content_edit"):
            return
        menu = self.doc_content_edit.createStandardContextMenu()
        cursor = self.doc_content_edit.textCursor()
        selected = (cursor.selectedText() or "").replace("\u2029", "\n").strip()
        menu.addSeparator()
        if selected:
            action = menu.addAction("AI 划线注解选中片段")
            action.triggered.connect(self.on_doc_ai_explain_clicked)
        menu.exec(self.doc_content_edit.mapToGlobal(pos))
        menu.deleteLater()

    def on_doc_annotation_manage_clicked(self):
        self.open_doc_annotation_window()

    def on_doc_ai_explain_clicked(
        self,
        use_selection=True,
        selected_override=None,
        start_pos_override=None,
        end_pos_override=None,
        silent_when_no_selection=False,
    ):
        if not hasattr(self, "doc_content_edit"):
            return
        source_text = self.doc_content_edit.toPlainText().strip()
        if not source_text:
            QMessageBox.information(self, "提示", "请先导入文档。")
            return
        selected = (selected_override or "").replace("\u2029", "\n").strip()
        if selected:
            start_pos = int(start_pos_override if start_pos_override is not None else -1)
            end_pos = int(end_pos_override if end_pos_override is not None else -1)
            if start_pos < 0 or end_pos <= start_pos:
                start_pos, end_pos = self._resolve_doc_selection_range(selected)
        else:
            tc = self.doc_content_edit.textCursor()
            selected = (tc.selectedText() or "").replace("\u2029", "\n").strip()
            if use_selection and not selected:
                selected = (getattr(self, "doc_last_selected_text", "") or "").strip()
                start_pos = int(getattr(self, "doc_last_selection_start", -1))
                end_pos = int(getattr(self, "doc_last_selection_end", -1))
            else:
                start_pos = min(tc.selectionStart(), tc.selectionEnd())
                end_pos = max(tc.selectionStart(), tc.selectionEnd())
        if not (use_selection and selected):
            if not silent_when_no_selection:
                QMessageBox.information(self, "提示", "请先在 Markdown 编辑区选中要注解的片段。")
            return
        target_text = selected
        context_text = self._build_doc_annotation_context(target_text, start_pos, end_pos)
        file_path = self._normalize_doc_note_path(getattr(self, "current_doc_reader_path", ""))
        url = self.normalize_api_url(self.settings.get("api_url", ""))
        key = self.settings.get("api_key", "")
        model = self.get_high_model_name() or self.get_mid_model_name()
        if not url or not key or not model:
            QMessageBox.warning(self, "AI 解读失败", "AI 配置不完整：请先在设置中配置 API URL、API Key 和模型。")
            return
        tmpl = prompt_text(
            self.get_ai_prompts(),
            "doc_reader_explain_prompt",
            (
                "你是英语学习助手。请结合上下文解释用户圈选文本的含义。\n"
                "输出纯文本，不要小标题、序号或 Markdown。\n\n"
                "文档路径：\n{file_path}\n\n"
                "待解读上下文：\n{source_context}\n\n"
                "待解读内容：\n{selected_text}"
            ),
        )
        try:
            prompt = (tmpl or "").format(
                selected_text=target_text,
                source_context=context_text,
                file_path=file_path or "未知",
            )
        except Exception:
            prompt = (
                "你是英语学习助手。请对用户提供的内容做清晰、可学习的解读，"
                "先讲含义，再讲语境/搭配。只输出纯文本，不要小标题。\n\n"
                f"文档路径：\n{file_path or '未知'}\n\n"
                f"待解读上下文：\n{context_text}\n\n"
                f"待解读内容：\n{target_text}"
            )
        signature = (
            file_path.lower(),
            int(start_pos),
            int(end_pos),
            (target_text or "").strip(),
        )
        inflight = getattr(self, "doc_auto_ai_inflight_signatures", None)
        if inflight is None:
            inflight = set()
            self.doc_auto_ai_inflight_signatures = inflight
        if signature in inflight:
            return
        inflight.add(signature)
        self.doc_auto_ai_dialog_open = True
        self._begin_doc_annotation_stream(signature, target_text, start_pos, end_pos)
        threading.Thread(
            target=self._doc_reader_explain_worker_stream,
            args=(url, key, model, prompt, target_text, start_pos, end_pos, signature, bool(silent_when_no_selection)),
            daemon=True,
        ).start()

    def _begin_doc_annotation_stream(self, signature, selected_text, start_pos, end_pos):
        streams = getattr(self, "doc_annotation_stream_buffers", None)
        if streams is None:
            streams = {}
            self.doc_annotation_stream_buffers = streams
        streams[signature] = ""
        anchor = {
            "start_pos": int(start_pos),
            "end_pos": int(end_pos),
            "selected_text": (selected_text or "").strip(),
        }
        self.open_doc_annotation_window(row=anchor)
        if hasattr(self, "doc_annotation_window_detail"):
            self.doc_annotation_window_detail.setPlainText("AI 正在生成注释...\n")

    def _doc_reader_explain_worker_stream(self, url, key, model, prompt, selected_text, start_pos, end_pos, signature, silent):
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": prompt_text(self.get_ai_prompts(), "note_ai_system", "You are a helpful English learning assistant for Chinese users.")},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "stream": True,
        }
        pieces = []
        try:
            data = json.dumps(payload).encode("utf-8")
            req = request.Request(
                url,
                data=data,
                headers={
                    "Accept": "text/event-stream",
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {key}",
                },
                method="POST",
            )
            with request.urlopen(req, timeout=90) as resp:
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
                            pieces.append(piece)
                            self.inner_tool_result_ready.emit(
                                {
                                    "ok": True,
                                    "tool": "doc_annotation",
                                    "stage": "chunk",
                                    "signature": signature,
                                    "selected_text": selected_text,
                                    "start_pos": int(start_pos),
                                    "end_pos": int(end_pos),
                                    "silent": bool(silent),
                                    "piece": piece,
                                }
                            )
                else:
                    resp_text = resp.read().decode("utf-8", errors="ignore")
                    text_piece = self.extract_text_from_response(resp_text) or ""
                    if text_piece:
                        pieces.append(text_piece)
                        self.inner_tool_result_ready.emit(
                            {
                                "ok": True,
                                "tool": "doc_annotation",
                                "stage": "chunk",
                                "signature": signature,
                                "selected_text": selected_text,
                                "start_pos": int(start_pos),
                                "end_pos": int(end_pos),
                                "silent": bool(silent),
                                "piece": text_piece,
                            }
                        )
            answer = "".join(pieces).strip()
            self.inner_tool_result_ready.emit(
                {
                    "ok": True,
                    "tool": "doc_annotation",
                    "stage": "done",
                    "selected_text": selected_text,
                    "start_pos": int(start_pos),
                    "end_pos": int(end_pos),
                    "signature": signature,
                    "silent": bool(silent),
                    "text": answer,
                }
            )
        except Exception as e:
            self.inner_tool_result_ready.emit(
                {
                    "ok": False,
                    "tool": "doc_annotation",
                    "stage": "done",
                    "selected_text": selected_text,
                    "start_pos": int(start_pos),
                    "end_pos": int(end_pos),
                    "signature": signature,
                    "silent": bool(silent),
                    "error": str(e),
                }
            )

    def _normalize_doc_annotation_text(self, text):
        cleaned = (text or "").strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:text|markdown)?\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        return cleaned.strip()

    def on_doc_annotation_result(self, result):
        stage = (result or {}).get("stage", "done")
        signature = (result or {}).get("signature")
        if stage == "chunk":
            piece = (result or {}).get("piece", "")
            if not piece:
                return
            streams = getattr(self, "doc_annotation_stream_buffers", None)
            if streams is None:
                streams = {}
                self.doc_annotation_stream_buffers = streams
            streams[signature] = (streams.get(signature, "") or "") + piece
            if hasattr(self, "doc_annotation_window_detail"):
                self.doc_annotation_window_detail.setPlainText(streams[signature])
            return
        signature = (result or {}).get("signature")
        inflight = getattr(self, "doc_auto_ai_inflight_signatures", None)
        if isinstance(inflight, set) and signature in inflight:
            inflight.discard(signature)
        self.doc_auto_ai_dialog_open = False
        if not result or not result.get("ok"):
            if not (result or {}).get("silent"):
                QMessageBox.warning(self, "AI 注释失败", (result or {}).get("error", "未知错误"))
            return
        streams = getattr(self, "doc_annotation_stream_buffers", None)
        streamed = ""
        if isinstance(streams, dict):
            streamed = streams.pop(signature, "")
        note = self._normalize_doc_annotation_text(streamed or (result or {}).get("text", ""))
        if not note:
            if not (result or {}).get("silent"):
                QMessageBox.information(self, "AI 注释", "模型未返回有效注释内容。")
            return
        row = self.save_doc_annotation(
            int((result or {}).get("start_pos", -1)),
            int((result or {}).get("end_pos", -1)),
            (result or {}).get("selected_text", ""),
            note,
        )
        if not row:
            return
        self.apply_doc_annotation_highlights()
        self.open_doc_annotation_window(row=row)

    def save_doc_annotation(self, start_pos, end_pos, selected_text, annotation):
        file_path = self._normalize_doc_note_path(getattr(self, "current_doc_reader_path", ""))
        if not file_path:
            return None
        token = (selected_text or "").strip()
        note = (annotation or "").strip()
        if not token or not note:
            return None
        s_pos = int(start_pos)
        e_pos = int(end_pos)
        if s_pos < 0 or e_pos <= s_pos:
            s_pos, e_pos = self._resolve_doc_selection_range(token)
        if s_pos < 0 or e_pos <= s_pos:
            s_pos, e_pos = 0, 0
        ts = datetime.now().isoformat(timespec="seconds")
        cur = self.user_conn.cursor()
        cur.execute(
            "INSERT INTO doc_annotations(file_path, start_pos, end_pos, selected_text, annotation, created_at, updated_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?)",
            (file_path, int(s_pos), int(e_pos), token, note, ts, ts),
        )
        ann_id = int(cur.lastrowid)
        self.user_conn.commit()
        return {
            "id": ann_id,
            "start_pos": int(s_pos),
            "end_pos": int(e_pos),
            "selected_text": token,
            "annotation": note,
            "created_at": ts,
            "updated_at": ts,
        }

    def _get_doc_annotations_for_fragment(self, row):
        file_path = self._normalize_doc_note_path(getattr(self, "current_doc_reader_path", ""))
        if not file_path or not row:
            return []
        start_pos = int(row.get("start_pos", -1))
        end_pos = int(row.get("end_pos", -1))
        token = (row.get("selected_text", "") or "").strip()
        if not token:
            return []
        cur = self.user_conn.cursor()
        if start_pos >= 0 and end_pos > start_pos:
            cur.execute(
                "SELECT id, start_pos, end_pos, selected_text, annotation, created_at, updated_at "
                "FROM doc_annotations WHERE file_path = ? AND start_pos = ? AND end_pos = ? AND selected_text = ? "
                "ORDER BY id DESC",
                (file_path, start_pos, end_pos, token),
            )
        else:
            cur.execute(
                "SELECT id, start_pos, end_pos, selected_text, annotation, created_at, updated_at "
                "FROM doc_annotations WHERE file_path = ? AND selected_text = ? ORDER BY id DESC",
                (file_path, token),
            )
        rows = []
        for r in cur.fetchall():
            rows.append(
                {
                    "id": int(r[0]),
                    "start_pos": int(r[1]),
                    "end_pos": int(r[2]),
                    "selected_text": r[3] or "",
                    "annotation": r[4] or "",
                    "created_at": r[5] or "",
                    "updated_at": r[6] or "",
                }
            )
        return rows

    def open_doc_annotation_window(self, row=None, global_pos=None):
        dlg = getattr(self, "doc_annotation_window", None)
        if dlg is None:
            dlg = QDialog(self)
            dlg.setWindowTitle("片段注释")
            dlg.resize(700, 430)
            root = QVBoxLayout()
            hint = QLabel("当前片段的所有注释：")
            hint.setWordWrap(True)
            root.addWidget(hint)
            token_label = QLabel("")
            token_label.setWordWrap(True)
            token_label.setStyleSheet("color:#61dafb;")
            root.addWidget(token_label)
            list_widget = QListWidget()
            root.addWidget(list_widget, 1)
            detail = QTextBrowser()
            detail.setOpenExternalLinks(False)
            detail.setPlaceholderText("选择一条注释查看完整内容")
            root.addWidget(detail, 1)
            btn_row = QHBoxLayout()
            delete_btn = QPushButton("删除选中注释")
            close_btn = QPushButton("关闭")
            btn_row.addWidget(delete_btn)
            btn_row.addStretch()
            btn_row.addWidget(close_btn)
            root.addLayout(btn_row)
            dlg.setLayout(root)
            self.doc_annotation_window = dlg
            self.doc_annotation_window_list = list_widget
            self.doc_annotation_window_detail = detail
            self.doc_annotation_window_token = token_label
            delete_btn.clicked.connect(self.on_doc_annotation_delete_clicked)
            close_btn.clicked.connect(dlg.close)
            list_widget.currentItemChanged.connect(self.on_doc_annotation_item_changed)
        if row is None:
            row = getattr(self, "doc_annotation_window_anchor", None)
            if row is None:
                file_path = self._normalize_doc_note_path(getattr(self, "current_doc_reader_path", ""))
                items = self.get_doc_annotations(file_path) if file_path else []
                row = items[0] if items else None
            if row is None:
                QMessageBox.information(self, "片段注释", "当前文档还没有可展示的注释。")
                return
        self.doc_annotation_window_anchor = dict(row)
        rows = self._get_doc_annotations_for_fragment(row)
        if hasattr(self, "doc_annotation_window_token"):
            token = (row.get("selected_text", "") or "").strip()
            self.doc_annotation_window_token.setText(token if token else "（未识别片段）")
        if hasattr(self, "doc_annotation_window_list"):
            box = self.doc_annotation_window_list
            box.blockSignals(True)
            box.clear()
            for item_row in rows:
                text = (item_row.get("annotation", "") or "").strip()
                preview = text if len(text) <= 80 else (text[:80] + "...")
                stamp = (item_row.get("created_at", "") or "").replace("T", " ")[:19]
                label = f"{stamp}  {preview}" if stamp else preview
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, item_row)
                box.addItem(item)
            box.blockSignals(False)
            if box.count() > 0:
                box.setCurrentRow(0)
        if hasattr(self, "doc_annotation_window_detail"):
            if not rows:
                self.doc_annotation_window_detail.setPlainText("该片段暂无注释。")
        if global_pos is not None:
            self.doc_annotation_window.move(global_pos)
        self.doc_annotation_window.show()
        self.doc_annotation_window.raise_()
        self.doc_annotation_window.activateWindow()

    def on_doc_annotation_item_changed(self, current, _previous):
        if not hasattr(self, "doc_annotation_window_detail"):
            return
        if current is None:
            self.doc_annotation_window_detail.clear()
            return
        row = current.data(Qt.ItemDataRole.UserRole) or {}
        note = (row.get("annotation", "") or "").strip()
        self.doc_annotation_window_detail.setPlainText(note)

    def on_doc_annotation_delete_clicked(self):
        if not hasattr(self, "doc_annotation_window_list"):
            return
        item = self.doc_annotation_window_list.currentItem()
        if item is None:
            QMessageBox.information(self, "删除注释", "请先选择要删除的注释。")
            return
        row = item.data(Qt.ItemDataRole.UserRole) or {}
        ann_id = int(row.get("id", 0))
        if ann_id <= 0:
            return
        cur = self.user_conn.cursor()
        cur.execute("DELETE FROM doc_annotations WHERE id = ?", (ann_id,))
        self.user_conn.commit()
        self.apply_doc_annotation_highlights()
        anchor = getattr(self, "doc_annotation_window_anchor", None)
        self.open_doc_annotation_window(row=anchor)

    def on_doc_save_markdown_clicked(self):
        file_path = self._normalize_doc_note_path(getattr(self, "current_doc_reader_path", ""))
        if not file_path:
            QMessageBox.information(self, "提示", "请先导入 Markdown 文件。")
            return
        try:
            text = self.doc_content_edit.toPlainText() if hasattr(self, "doc_content_edit") else ""
            with open(file_path, "w", encoding="utf-8", errors="strict") as f:
                f.write(text)
            self.current_doc_reader_text = text
            self.update_doc_markdown_preview()
            self.apply_doc_annotation_highlights()
            self.refresh_doc_markdown_file_list()
            QMessageBox.information(self, "保存成功", f"Markdown 已保存到：\n{file_path}")
        except Exception as e:
            QMessageBox.warning(self, "保存失败", f"无法保存 Markdown：{str(e)}")


    def safe_navigate_to_linked_word(self, target):
        try:
            self.navigate_to_word(target)
        except Exception as e:
            QMessageBox.warning(self, "跳转失败", f"关联词跳转失败：{str(e)}")

    def increment_query_count(self, query):
        cur = self.user_conn.cursor()
        ts = datetime.now().isoformat(timespec='seconds')
        cur.execute('INSERT INTO queries(query, count, last_at) VALUES(?, 1, ?) ON CONFLICT(query) DO UPDATE SET count = count + 1, last_at = excluded.last_at', (query, ts))
        self.user_conn.commit()

    def update_favorite_button_state(self, query):
        folder_id = self.get_current_folder_id()
        cur = self.user_conn.cursor()
        cur.execute('SELECT 1 FROM favorites WHERE query = ? AND folder_id = ?', (query, folder_id))
        exists = cur.fetchone() is not None
        self.favorite_button.setText('取消收藏' if exists else '收藏')
        if hasattr(self, 'favorite_option_btn') and self.favorite_option_btn is not None:
            item = self.folders_list.currentItem() if hasattr(self, 'folders_list') else None
            folder_name = item.text() if item else "默认"
            self.favorite_option_btn.setToolTip(f"当前收藏夹：{folder_name}")

    def is_in_review(self, query):
        cur = self.user_conn.cursor()
        cur.execute('SELECT 1 FROM reviewing WHERE query = ?', (query,))
        return cur.fetchone() is not None

    def update_review_button_state(self, query):
        if not hasattr(self, 'review_button'):
            return
        self.review_button.setText('取消在背' if self.is_in_review(query) else '标记在背')

    def toggle_review_current(self):
        if not self.current_query:
            return
        cur = self.user_conn.cursor()
        exists = self.is_in_review(self.current_query)
        if exists:
            cur.execute('DELETE FROM reviewing WHERE query = ?', (self.current_query,))
        else:
            ts = datetime.now().isoformat(timespec='seconds')
            cur.execute('INSERT INTO reviewing(query, proficiency, created_at, last_visited_at) VALUES(?, ?, ?, ?)', (self.current_query, '人上人', ts, ts))
        self.user_conn.commit()
        self.update_review_button_state(self.current_query)
        self.update_current_query_visuals()
        self.refresh_highlighted_items()
        current_word = self.lookup_dictionary_word_exact(self.current_query)
        if current_word:
            self.refresh_words_link_view(current_word)
        if hasattr(self, 'update_note_preview'):
            self.note_preview_cache_key = None
            self.update_note_preview()
        if hasattr(self, 'refresh_llm_translation_highlight'):
            self.refresh_llm_translation_highlight()
        self.refresh_internal_page()
        # 不要在“标记在背”时强制跳转内化态；用户可能只是想继续当前查询页面

    def update_current_query_visuals(self):
        in_review = self.is_in_review(self.current_query) if self.current_query else False
        if hasattr(self, 'current_word_label') and self.current_word_label is not None:
            show_text = self.current_word_label_base_text + ("  🔥在背" if in_review else "")
            show_color = '#ffb347' if in_review else '#61dafb'
            self.current_word_label.setText(show_text)
            self.current_word_label.setStyleSheet(f'color: {show_color}; margin-bottom: 10px;')
        if hasattr(self, 'current_source_text_label') and self.current_source_text_label is not None:
            self.current_source_text_label.setStyleSheet('margin-bottom: 20px;')
        self.apply_review_highlight_to_detail_labels(in_review)

    def apply_review_highlight_to_label(self, label, query, in_review):
        base_text = label.property("_base_plain_text")
        if base_text is None:
            base_text = label.text()
            label.setProperty("_base_plain_text", base_text)
        if not in_review:
            label.setText(base_text)
            return
        # 获取当前主题的高亮颜色
        highlight_bg = self.colors.get('highlight_bg', '#6b4f00') if hasattr(self, 'colors') else '#6b4f00'
        highlight_text = self.colors.get('highlight_text', '#ffe9a8') if hasattr(self, 'colors') else '#ffe9a8'
        highlighted_html, matched = build_highlighted_text_html(base_text, query, highlight_bg, highlight_text)
        label.setText(highlighted_html if matched else base_text)

    def apply_review_highlight_to_detail_labels(self, in_review):
        if not hasattr(self, 'detail_widget'):
            return
        query = self.current_query
        for label in self.detail_widget.findChildren(QLabel):
            if label is self.current_word_label:
                continue
            self.apply_review_highlight_to_label(label, query, in_review)

    def apply_review_style_to_item(self, item, query):
        if self.is_in_review(query):
            # 获取当前主题的高亮颜色
            highlight_bg = self.colors.get('highlight_bg', '#6b4f00') if hasattr(self, 'colors') else '#6b4f00'
            highlight_text = self.colors.get('highlight_text', '#ffe9a8') if hasattr(self, 'colors') else '#ffe9a8'
            item.setBackground(QColor(highlight_bg))
            item.setForeground(QColor(highlight_text))
            f = item.font()
            f.setBold(True)
            item.setFont(f)
        else:
            item.setBackground(QBrush())
            item.setForeground(QBrush())
            f = item.font()
            f.setBold(False)
            item.setFont(f)

    def refresh_highlighted_items(self):
        if hasattr(self, 'candidates_list'):
            for i in range(self.candidates_list.count()):
                item = self.candidates_list.item(i)
                q = item.data(Qt.ItemDataRole.UserRole) or item.text()
                self.apply_review_style_to_item(item, q)
        if hasattr(self, 'favorites_list'):
            for i in range(self.favorites_list.count()):
                item = self.favorites_list.item(i)
                q = item.data(Qt.ItemDataRole.UserRole) or item.text()
                self.apply_review_style_to_item(item, q)
        if hasattr(self, 'inner_favorites_list'):
            for i in range(self.inner_favorites_list.count()):
                item = self.inner_favorites_list.item(i)
                q = item.data(Qt.ItemDataRole.UserRole) or item.text()
                self.apply_review_style_to_item(item, q)
        if hasattr(self, 'reviewing_words_list'):
            for i in range(self.reviewing_words_list.count()):
                item = self.reviewing_words_list.item(i)
                q = item.data(Qt.ItemDataRole.UserRole) or item.text()
                self.apply_review_style_to_item(item, q)

    def toggle_favorite_current(self):
        if not self.current_query:
            return
        folder_id = self.get_current_folder_id()
        cur = self.user_conn.cursor()
        cur.execute('SELECT 1 FROM favorites WHERE query = ? AND folder_id = ?', (self.current_query, folder_id))
        exists = cur.fetchone() is not None
        if exists:
            cur.execute('DELETE FROM favorites WHERE query = ? AND folder_id = ?', (self.current_query, folder_id))
        else:
            ts = datetime.now().isoformat(timespec='seconds')
            cur.execute('INSERT INTO favorites(query, folder_id, created_at) VALUES(?, ?, ?)', (self.current_query, folder_id, ts))
        self.user_conn.commit()
        self.update_favorite_button_state(self.current_query)
        self.load_favorites_list()
        self.refresh_internal_page()

    def load_favorites_list(self):
        if not hasattr(self, 'favorites_list') or not hasattr(self, 'user_conn'):
            return
        self.favorites_list.clear()
        folder_id = self.get_current_folder_id()
        cur = self.user_conn.cursor()
        cur.execute('SELECT query FROM favorites WHERE folder_id = ? ORDER BY created_at DESC', (folder_id,))
        rows = cur.fetchall()
        for r in rows:
            q = r[0]
            item = QListWidgetItem(q)
            item.setData(Qt.ItemDataRole.UserRole, q)
            self.apply_review_style_to_item(item, q)
            self.favorites_list.addItem(item)
        self.refresh_internal_page()

    def on_favorite_activated(self, item):
        q = item.data(Qt.ItemDataRole.UserRole) or item.text()
        self.switch_to_extension_page()
        self.search_input.setText(q)
        self.on_enter_pressed()

    def get_note(self, query):
        cur = self.user_conn.cursor()
        cur.execute('SELECT content FROM notes WHERE query = ?', (query,))
        row = cur.fetchone()
        return row[0] if row else ""

    def save_current_note(self):
        if not self.current_query:
            return
        content = self.note_edit.toPlainText()
        cur = self.user_conn.cursor()
        ts = datetime.now().isoformat(timespec='seconds')
        cur.execute('INSERT INTO notes(query, content, updated_at) VALUES(?, ?, ?) ON CONFLICT(query) DO UPDATE SET content = excluded.content, updated_at = excluded.updated_at', (self.current_query, content, ts))
        self.user_conn.commit()

    def get_current_folder_id(self):
        if hasattr(self, 'folders_list'):
            item = self.folders_list.currentItem()
            if item:
                folder_id = item.data(Qt.ItemDataRole.UserRole)
                if folder_id:
                    self.current_folder_id = int(folder_id)
        if hasattr(self, 'current_folder_id') and self.current_folder_id:
            return int(self.current_folder_id)
        return 1

    def load_folders(self):
        if not hasattr(self, 'folders_list'):
            return
        self.folders_list.clear()
        cur = self.user_conn.cursor()
        cur.execute('SELECT id, name FROM folders ORDER BY id')
        rows = cur.fetchall()
        selected_row = 0
        for idx, (folder_id, folder_name) in enumerate(rows):
            item = QListWidgetItem(folder_name)
            item.setData(Qt.ItemDataRole.UserRole, int(folder_id))
            self.folders_list.addItem(item)
            if int(folder_id) == self.get_current_folder_id():
                selected_row = idx
        if self.folders_list.count() > 0:
            self.folders_list.setCurrentRow(selected_row)
            cur_item = self.folders_list.currentItem()
            if cur_item:
                self.current_folder_id = int(cur_item.data(Qt.ItemDataRole.UserRole))
        if hasattr(self, 'init_export_ui'):
            self.init_export_ui()
        self.refresh_internal_page()

    def on_folder_changed(self, item):
        if not item:
            return
        self.current_folder_id = int(item.data(Qt.ItemDataRole.UserRole))
        self.load_favorites_list()
        if self.current_query and hasattr(self, 'favorite_button'):
            self.update_favorite_button_state(self.current_query)
        if self.current_query and hasattr(self, 'review_button'):
            self.update_review_button_state(self.current_query)
        self.refresh_internal_page()
        if hasattr(self, 'init_export_ui'):
            self.init_export_ui()
    def init_export_ui(self):
        if not hasattr(self, 'export_source_combo') or self.export_source_combo is None:
            return
        combo = self.export_source_combo
        combo.blockSignals(True)
        prev_idx = combo.currentIndex()
        combo.clear()
        options = self.build_wordcraft_scope_options()
        for label, scope, f_id in options:
            combo.addItem(label, (scope, f_id))
        if prev_idx >= 0 and prev_idx < combo.count():
            combo.setCurrentIndex(prev_idx)
        combo.blockSignals(False)

    def on_export_words_clicked(self):
        if not hasattr(self, 'export_source_combo') or self.export_source_combo is None:
            return
        data = self.export_source_combo.currentData()
        if not data:
            return
        scope, folder_id = data
        source_label = self.export_source_combo.currentText()
        
        candidates = self.get_scope_candidates(scope, folder_id)
        words = [row[0] for row in candidates]
        
        if not words:
            QMessageBox.information(self, "导出提示", f"来源“{source_label}”中没有单词可供导出。")
            return

        fmt = self.export_format_combo.currentText() if hasattr(self, 'export_format_combo') else ".txt"
        include_trans = self.export_include_trans_cb.isChecked() if hasattr(self, 'export_include_trans_cb') else False
        include_phon = self.export_include_phonetic_cb.isChecked() if hasattr(self, 'export_include_phonetic_cb') else False

        if ".csv" in fmt: ext = ".csv"
        elif ".md" in fmt: ext = ".md"
        elif ".json" in fmt: ext = ".json"
        else: ext = ".txt"

        filter_map = {
            ".csv": "CSV Files (*.csv)",
            ".md": "Markdown Files (*.md)",
            ".json": "JSON Files (*.json)",
            ".txt": "Text Files (*.txt)"
        }
        filter_str = filter_map.get(ext, "All Files (*)")
        file_path, _ = QFileDialog.getSaveFileName(self, "导出单词本", f"{source_label}_export{ext}", filter_str)
        if not file_path:
            return
            
        try:
            rows = []
            json_data = []
            cur = self.cursor
            for w in words:
                trans = ""
                phon = ""
                if include_trans or include_phon:
                    cur.execute("SELECT translation, phonetic FROM stardict WHERE word = ? COLLATE NOCASE LIMIT 1", (w,))
                    row = cur.fetchone()
                    if row:
                        trans = row[0] or ""
                        phon = row[1] or ""
                
                out_w = w
                out_phon = f"[{phon}]" if phon and include_phon else ""
                
                if include_trans and trans:
                    trans = trans.replace("\r", " ").replace("\n", " ").strip()
                else:
                    trans = ""

                if ext == ".csv":
                    r = [out_w]
                    if include_phon: r.append(out_phon)
                    if include_trans: r.append(trans)
                    rows.append(r)
                elif ext == ".md":
                    # Markdown 表格行构造
                    r = [f"**{out_w}**"]
                    if include_phon: r.append(out_phon if out_phon else "-")
                    if include_trans: r.append(trans if trans else "-")
                    rows.append("| " + " | ".join(r) + " |")
                elif ext == ".json":
                    item = {"word": out_w}
                    if include_phon: item["phonetic"] = phon
                    if include_trans: item["translation"] = trans
                    json_data.append(item)
                else:
                    parts = [out_w]
                    if out_phon: parts.append(out_phon)
                    if trans: parts.append("- " + trans)
                    rows.append(" ".join(parts))

            with open(file_path, 'w', encoding='utf-8', newline='') as f:
                if ext == ".csv":
                    import csv
                    writer = csv.writer(f)
                    header = ["Word"]
                    if include_phon: header.append("Phonetic")
                    if include_trans: header.append("Translation")
                    writer.writerow(header)
                    writer.writerows(rows)
                elif ext == ".md":
                    f.write(f"# 单词导出: {source_label}\n\n")
                    header = ["Word"]
                    sep = ["---"]
                    if include_phon: 
                        header.append("Phonetic")
                        sep.append("---")
                    if include_trans: 
                        header.append("Translation")
                        sep.append("---")
                    f.write("| " + " | ".join(header) + " |\n")
                    f.write("| " + " | ".join(sep) + " |\n")
                    f.write("\n".join(rows))
                elif ext == ".json":
                    import json as _json
                    _json.dump(json_data, f, ensure_ascii=False, indent=2)
                else:
                    f.write("\n".join(rows))
            QMessageBox.information(self, "导出成功", f"已成功从“{source_label}”导出 {len(words)} 个单词到：\n{file_path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", f"无法写入文件：{str(e)}")
