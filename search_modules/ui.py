from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPalette, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedLayout,
    QTextBrowser,
    QTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from search_modules.infrastructure import build_highlighted_text_html


class UIMixin:
    def init_ui(self):
        self.setWindowTitle('英语查词翻译软件')
        self.setGeometry(100, 100, 900, 700)
        self.apply_theme()
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(10)
        main_widget.setLayout(main_layout)
        self.main_tabs = QTabWidget()
        self.main_tabs.setDocumentMode(True)
        self.main_tabs.setMovable(False)
        self.main_tabs.currentChanged.connect(self.on_main_tab_changed)
        main_layout.addWidget(self.main_tabs)
        ext_page = QWidget()
        self.main_tabs.addTab(ext_page, "扩展态")
        root_layout = QHBoxLayout()
        root_layout.setSpacing(20)
        root_layout.setContentsMargins(12, 12, 12, 12)
        ext_page.setLayout(root_layout)
        left_container = QWidget()
        left_layout = QVBoxLayout()
        left_layout.setSpacing(20)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_container.setLayout(left_layout)
        root_layout.addWidget(left_container, 3)
        right_container = QWidget()
        right_layout = QVBoxLayout()
        right_layout.setSpacing(12)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_container.setLayout(right_layout)
        root_layout.addWidget(right_container, 1)
        header_widget = QWidget()
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_widget.setLayout(header_layout)
        title_label = QLabel('🔍 英语查词翻译')
        title_label.setFont(QFont('Segoe UI', 24, QFont.Weight.Bold))
        title_label.setStyleSheet('color: #61dafb;')
        title_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        self.settings_btn = QPushButton('设置')
        self.settings_btn.setFixedHeight(32)
        self.settings_btn.clicked.connect(self.open_settings_dialog)
        header_layout.addWidget(self.settings_btn)
        left_layout.addWidget(header_widget)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('输入单词或句子...')
        self.search_input.setFont(QFont('Segoe UI', 14))
        self.search_input.textChanged.connect(self.on_search_text_changed)
        self.search_input.returnPressed.connect(self.on_enter_pressed)
        left_layout.addWidget(self.search_input)
        self.search_input.keyPressEvent = self.on_search_key_press
        self.candidates_list = QListWidget()
        self.candidates_list.setFont(QFont('Consolas', 12))
        self.candidates_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.candidates_list.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.candidates_list.keyPressEvent = self.on_candidates_key_press
        self.candidates_list.setMaximumHeight(200)
        self.candidates_list.itemClicked.connect(self.on_candidate_clicked)
        self.candidates_list.itemActivated.connect(self.on_candidate_activated)
        self.candidates_list.verticalScrollBar().valueChanged.connect(self.on_scroll_changed)
        left_layout.addWidget(self.candidates_list)
        self.current_search_text = ""
        self.all_candidates = []
        self.loaded_count = 0
        self.current_query = ""
        self.detail_area = QScrollArea()
        self.detail_area.setWidgetResizable(True)
        self.detail_widget = QWidget()
        self.detail_layout = QVBoxLayout()
        self.detail_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.detail_widget.setLayout(self.detail_layout)
        self.detail_area.setWidget(self.detail_widget)
        left_layout.addWidget(self.detail_area)
        fav_title = QLabel('⭐ 收藏夹')
        fav_title.setFont(QFont('Segoe UI', 16, QFont.Weight.Bold))
        fav_title.setStyleSheet('color: #ffc107;')
        fav_title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        right_layout.addWidget(fav_title)
        folder_toolbar = QWidget()
        folder_toolbar_layout = QHBoxLayout()
        folder_toolbar_layout.setContentsMargins(0, 0, 0, 0)
        folder_toolbar.setLayout(folder_toolbar_layout)
        self.add_folder_btn = QPushButton('新建文件夹')
        self.add_folder_btn.clicked.connect(self.create_folder)
        folder_toolbar_layout.addWidget(self.add_folder_btn)
        self.delete_folder_btn = QPushButton('删除文件夹')
        self.delete_folder_btn.clicked.connect(self.delete_current_folder)
        folder_toolbar_layout.addWidget(self.delete_folder_btn)
        folder_toolbar_layout.addStretch()
        right_layout.addWidget(folder_toolbar)
        self.folders_list = QListWidget()
        self.folders_list.setMaximumHeight(140)
        self.folders_list.itemClicked.connect(self.on_folder_changed)
        right_layout.addWidget(self.folders_list)
        self.favorites_list = QListWidget()
        self.favorites_list.setFont(QFont('Consolas', 12))
        self.favorites_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.favorites_list.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.favorites_list.itemActivated.connect(self.on_favorite_activated)
        self.favorites_list.itemClicked.connect(self.on_favorite_activated)
        right_layout.addWidget(self.favorites_list)
        self.inner_page = QWidget()
        self.main_tabs.addTab(self.inner_page, "内化态")
        inner_layout = QVBoxLayout()
        inner_layout.setSpacing(12)
        inner_layout.setContentsMargins(12, 12, 12, 12)
        self.inner_page.setLayout(inner_layout)
        inner_content = QWidget()
        inner_content_layout = QHBoxLayout()
        inner_content_layout.setContentsMargins(0, 0, 0, 0)
        inner_content_layout.setSpacing(12)
        inner_content.setLayout(inner_content_layout)
        inner_layout.addWidget(inner_content, 1)
        inner_left_panel = QWidget()
        inner_left_layout = QVBoxLayout()
        inner_left_layout.setContentsMargins(0, 0, 0, 0)
        inner_left_layout.setSpacing(12)
        inner_left_panel.setLayout(inner_left_layout)
        inner_content_layout.addWidget(inner_left_panel, 1)
        inner_fav_title = QLabel("⭐ 收藏夹（当前文件夹）")
        inner_fav_title.setFont(QFont('Segoe UI', 14, QFont.Weight.Bold))
        inner_left_layout.addWidget(inner_fav_title)
        self.inner_favorites_list = QListWidget()
        self.inner_favorites_list.itemActivated.connect(self.on_favorite_activated)
        self.inner_favorites_list.itemClicked.connect(self.on_favorite_activated)
        inner_left_layout.addWidget(self.inner_favorites_list, 1)
        review_title = QLabel("🔥 在背状态单词")
        review_title.setFont(QFont('Segoe UI', 14, QFont.Weight.Bold))
        inner_left_layout.addWidget(review_title)
        self.reviewing_words_list = QListWidget()
        self.reviewing_words_list.itemActivated.connect(self.on_favorite_activated)
        self.reviewing_words_list.itemClicked.connect(self.on_favorite_activated)
        inner_left_layout.addWidget(self.reviewing_words_list, 1)
        inner_right_panel = QWidget()
        inner_right_layout = QVBoxLayout()
        inner_right_layout.setContentsMargins(0, 0, 0, 0)
        inner_right_layout.setSpacing(10)
        inner_right_panel.setLayout(inner_right_layout)
        inner_content_layout.addWidget(inner_right_panel, 1)
        self.inner_tool_bar = QWidget()
        self.inner_tool_bar_layout = QHBoxLayout()
        self.inner_tool_bar_layout.setContentsMargins(0, 0, 0, 0)
        self.inner_tool_bar.setLayout(self.inner_tool_bar_layout)
        self.inner_tool_title = QLabel("工具栏")
        self.inner_tool_bar_layout.addWidget(self.inner_tool_title)
        self.inner_tool_bar_layout.addStretch()
        self.inner_tool_action_1 = QPushButton("新会话")
        self.inner_tool_action_2 = QPushButton("删除会话")
        self.inner_tool_bar_layout.addWidget(self.inner_tool_action_1)
        self.inner_tool_bar_layout.addWidget(self.inner_tool_action_2)
        inner_right_layout.addWidget(self.inner_tool_bar)
        self.inner_dialog_area = QWidget()
        self.inner_dialog_area_layout = QHBoxLayout()
        self.inner_dialog_area_layout.setContentsMargins(0, 0, 0, 0)
        self.inner_dialog_area_layout.setSpacing(10)
        self.inner_dialog_area.setLayout(self.inner_dialog_area_layout)
        self.inner_session_list = QListWidget()
        self.inner_session_list.setMinimumWidth(160)
        self.inner_dialog_area_layout.addWidget(self.inner_session_list, 1)
        self.inner_dialog_editor = QTextEdit()
        self.inner_dialog_editor.setPlaceholderText("用于 AI 对话或其他特殊用途（待定）")
        self.inner_dialog_area_layout.addWidget(self.inner_dialog_editor, 1)
        inner_right_layout.addWidget(self.inner_dialog_area, 1)
        self.inner_confirm_btn = QPushButton("确认已选中不懂片段")
        self.inner_confirm_btn.setVisible(False)
        inner_right_layout.addWidget(self.inner_confirm_btn)
        if hasattr(self, 'init_inner_workspace'):
            self.init_inner_workspace()
        self.load_folders()
        self.load_favorites_list()
        self.refresh_internal_page()
        self.apply_styles()
        if hasattr(self, 'setup_ai_chat_shortcuts'):
            self.setup_ai_chat_shortcuts()

    def on_main_tab_changed(self, index):
        if index == 1:
            self.refresh_internal_page()

    def set_dark_theme(self):
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.Base, QColor(45, 45, 45))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(35, 35, 35))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.Text, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.Button, QColor(45, 45, 45))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
        palette.setColor(QPalette.ColorRole.Link, QColor(97, 218, 251))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(97, 218, 251))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0))
        QApplication.setPalette(palette)

    def set_light_theme(self):
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(0, 0, 0))
        palette.setColor(QPalette.ColorRole.Base, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(247, 247, 247))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor(0, 0, 0))
        palette.setColor(QPalette.ColorRole.Text, QColor(0, 0, 0))
        palette.setColor(QPalette.ColorRole.Button, QColor(247, 247, 247))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(0, 0, 0))
        palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
        palette.setColor(QPalette.ColorRole.Link, QColor(26, 115, 232))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(26, 115, 232))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
        QApplication.setPalette(palette)

    def apply_theme(self):
        theme = self.settings.get('theme', 'dark')
        if theme == 'light':
            self.set_light_theme()
        else:
            self.set_dark_theme()
        self.colors = self.compute_theme_colors(theme)

    def compute_theme_colors(self, theme):
        if theme == 'light':
            return {
                'bg': '#ffffff',
                'bg_alt': '#f5f5f5',
                'border': '#cccccc',
                'text': '#000000',
                'text_muted': '#333333',
                'accent': '#1a73e8',
                'accent_text': '#ffffff',
                'widget_bg': '#ffffff',
            }
        return {
            'bg': '#1e1e1e',
            'bg_alt': '#2d2d2d',
            'border': '#3d3d3d',
            'text': '#ffffff',
            'text_muted': '#abb2bf',
            'accent': '#61dafb',
            'accent_text': '#000000',
            'widget_bg': '#1e1e1e',
        }

    def apply_styles(self):
        if not hasattr(self, 'settings'):
            self.settings = {'theme': 'dark'}
        if not hasattr(self, 'colors'):
            self.colors = self.compute_theme_colors(self.settings.get('theme', 'dark'))
        c = self.colors
        if hasattr(self, 'search_input'):
            self.search_input.setStyleSheet(
                f"QLineEdit{{background-color:{c['widget_bg']};border:2px solid {c['border']};border-radius:8px;padding:15px;color:{c['text']};font-size:14px;}}QLineEdit:focus{{border:2px solid {c['accent']};}}"
            )
        if hasattr(self, 'candidates_list'):
            self.candidates_list.setStyleSheet(
                f"QListWidget{{background-color:{c['widget_bg']};border:1px solid {c['border']};border-radius:8px;color:{c['text']};padding:5px;}}QListWidget::item{{padding:8px;border-bottom:1px solid {c['bg_alt']};}}QListWidget::item:hover{{background-color:{c['bg_alt']};}}QListWidget::item:selected{{background-color:{c['accent']};color:{c['accent_text']};}}"
            )
        if hasattr(self, 'detail_area'):
            self.detail_area.setStyleSheet("QScrollArea{border:none;background-color:transparent;}")
        if hasattr(self, 'favorites_list'):
            self.favorites_list.setStyleSheet(
                f"QListWidget{{background-color:{c['widget_bg']};border:1px solid {c['border']};border-radius:8px;color:{c['text']};padding:5px;}}QListWidget::item{{padding:8px;border-bottom:1px solid {c['bg_alt']};}}QListWidget::item:hover{{background-color:{c['bg_alt']};}}QListWidget::item:selected{{background-color:{c['accent']};color:{c['accent_text']};}}"
            )
        if hasattr(self, 'folders_list'):
            self.folders_list.setStyleSheet(
                f"QListWidget{{background-color:{c['widget_bg']};border:1px solid {c['border']};border-radius:8px;color:{c['text']};padding:5px;}}QListWidget::item{{padding:6px;}}QListWidget::item:selected{{background-color:{c['accent']};color:{c['accent_text']};}}"
            )
        if hasattr(self, 'note_edit'):
            self.note_edit.setStyleSheet(
                f"QTextEdit{{background-color:{c['widget_bg']};border:1px solid {c['border']};border-radius:6px;color:{c['text']};padding:8px;}}QScrollBar:vertical{{background:{c['bg_alt']};width:12px;margin:0px;}}QScrollBar::handle:vertical{{background:{c['accent']};min-height:20px;border-radius:6px;}}"
            )
            self.note_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        if hasattr(self, 'note_preview'):
            self.note_preview.setStyleSheet(
                f"QTextBrowser{{background-color:{c['widget_bg']};border:1px solid {c['border']};border-radius:6px;color:{c['text']};padding:8px;}}QScrollBar:vertical{{background:{c['bg_alt']};width:12px;margin:0px;}}QScrollBar::handle:vertical{{background:{c['accent']};min-height:20px;border-radius:6px;}}"
            )
            self.note_preview.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        if hasattr(self, 'ai_options_list'):
            self.ai_options_list.setStyleSheet(
                f"QListWidget{{background-color:{c['widget_bg']};border:1px solid {c['border']};border-radius:6px;color:{c['text']};}}"
            )
        if hasattr(self, 'main_tabs'):
            self.main_tabs.setStyleSheet(
                f"QTabWidget::pane{{border:1px solid {c['border']};border-radius:8px;background:{c['bg']};}}QTabBar::tab{{background:{c['bg_alt']};color:{c['text']};padding:8px 16px;border:1px solid {c['border']};border-bottom:none;border-top-left-radius:6px;border-top-right-radius:6px;margin-right:4px;}}QTabBar::tab:selected{{background:{c['widget_bg']};color:{c['accent']};}}"
            )
        if hasattr(self, 'inner_favorites_list'):
            self.inner_favorites_list.setStyleSheet(
                f"QListWidget{{background-color:{c['widget_bg']};border:1px solid {c['border']};border-radius:8px;color:{c['text']};padding:5px;}}QListWidget::item{{padding:8px;border-bottom:1px solid {c['bg_alt']};}}QListWidget::item:selected{{background-color:{c['accent']};color:{c['accent_text']};}}"
            )
        if hasattr(self, 'reviewing_words_list'):
            self.reviewing_words_list.setStyleSheet(
                f"QListWidget{{background-color:{c['widget_bg']};border:1px solid {c['border']};border-radius:8px;color:{c['text']};padding:5px;}}QListWidget::item{{padding:8px;border-bottom:1px solid {c['bg_alt']};}}QListWidget::item:selected{{background-color:{c['accent']};color:{c['accent_text']};}}"
            )
        if hasattr(self, 'inner_session_list'):
            self.inner_session_list.setStyleSheet(
                f"QListWidget{{background-color:{c['widget_bg']};border:1px solid {c['border']};border-radius:8px;color:{c['text']};padding:5px;}}QListWidget::item{{padding:8px;border-bottom:1px solid {c['bg_alt']};}}QListWidget::item:selected{{background-color:{c['accent']};color:{c['accent_text']};}}"
            )
        if hasattr(self, 'inner_dialog_editor'):
            self.inner_dialog_editor.setStyleSheet(
                f"QTextEdit{{background-color:{c['widget_bg']};border:1px solid {c['border']};border-radius:8px;color:{c['text']};padding:8px;}}"
            )
        if hasattr(self, 'inner_tool_title'):
            self.inner_tool_title.setStyleSheet(f"color:{c['accent']};font-weight:600;")

    def open_settings_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("设置")
        form = QFormLayout()
        theme_combo = QComboBox()
        theme_combo.addItems(["深色", "浅色"])
        theme_combo.setCurrentIndex(0 if self.settings.get('theme', 'dark') == 'dark' else 1)
        api_url_edit = QLineEdit()
        api_url_edit.setText(self.settings.get('api_url', ''))
        api_key_edit = QLineEdit()
        api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        api_key_edit.setText(self.settings.get('api_key', ''))
        model_mid_edit = QLineEdit()
        model_mid_edit.setText(self.get_mid_model_name())
        model_high_edit = QLineEdit()
        model_high_edit.setText(self.get_high_model_name())
        form.addRow("主题", theme_combo)
        form.addRow("API URL", api_url_edit)
        form.addRow("API Key", api_key_edit)
        form.addRow("中级模型名", model_mid_edit)
        form.addRow("高级模型名", model_high_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        container = QVBoxLayout()
        container.addLayout(form)
        container.addWidget(buttons)
        dlg.setLayout(container)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        if dlg.exec():
            theme = 'dark' if theme_combo.currentIndex() == 0 else 'light'
            self.set_setting('theme', theme)
            self.set_setting('api_url', api_url_edit.text().strip())
            self.set_setting('api_key', api_key_edit.text().strip())
            self.set_setting('model_mid', model_mid_edit.text().strip())
            high_model = model_high_edit.text().strip()
            self.set_setting('model_high', high_model)
            self.set_setting('model', high_model)
            self.load_settings()
            self.apply_theme()
            self.apply_styles()

    def build_note_section(self):
        note_title = QLabel("批注")
        note_title.setFont(QFont('Segoe UI', 12, QFont.Weight.Bold))
        note_title.setStyleSheet('color: #61dafb; margin-top: 15px; margin-bottom: 5px;')
        self.detail_layout.addWidget(note_title)
        self.note_host = QWidget()
        self.note_host.setMinimumHeight(220)
        self.note_stack = QStackedLayout()
        self.note_stack.setContentsMargins(0, 0, 0, 0)
        self.note_host.setLayout(self.note_stack)
        self.note_edit = QTextEdit()
        self.note_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.note_edit.setPlainText(self.get_note(self.current_query))
        self.note_edit.textChanged.connect(self.update_note_preview)
        self.note_preview = QTextBrowser()
        self.note_preview.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.note_preview.setOpenExternalLinks(False)
        self.note_preview.mousePressEvent = self.on_note_preview_mouse_press
        self.note_preview.mouseDoubleClickEvent = self.on_note_preview_double_click
        if hasattr(self, 'install_ai_selection_context_menu'):
            self.install_ai_selection_context_menu(self.note_edit, "批注栏")
            self.install_ai_selection_context_menu(self.note_preview, "批注栏预览")
        self.note_stack.addWidget(self.note_preview)
        self.note_stack.addWidget(self.note_edit)
        self.detail_layout.addWidget(self.note_host)
        self.note_edit.focusOutEvent = self.on_note_edit_focus_out
        self.note_preview_cache_key = None
        self.update_note_preview()
        self.switch_note_to_preview()

    def on_note_preview_mouse_press(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.switch_note_to_edit()
        QTextBrowser.mousePressEvent(self.note_preview, event)

    def on_note_preview_double_click(self, event):
        self.switch_note_to_edit()
        QTextBrowser.mouseDoubleClickEvent(self.note_preview, event)

    def on_note_edit_focus_out(self, event):
        QTextEdit.focusOutEvent(self.note_edit, event)
        self.switch_note_to_preview()

    def switch_note_to_preview(self):
        if hasattr(self, 'note_stack'):
            self.update_note_preview()
            self.note_stack.setCurrentWidget(self.note_preview)
            self.note_preview.verticalScrollBar().setValue(self.note_edit.verticalScrollBar().value())

    def switch_note_to_edit(self):
        if hasattr(self, 'note_stack'):
            self.note_stack.setCurrentWidget(self.note_edit)
            self.note_edit.setFocus()
            self.note_edit.moveCursor(QTextCursor.MoveOperation.End)

    def update_note_preview(self):
        if hasattr(self, 'note_edit') and hasattr(self, 'note_preview'):
            text = self.note_edit.toPlainText()
            in_review = self.is_in_review(self.current_query) if self.current_query else False
            cache_key = (self.current_query, in_review, text)
            if self.note_preview_cache_key == cache_key:
                return
            self.note_preview_cache_key = cache_key
            if in_review and self.current_query:
                highlighted_html, matched = build_highlighted_text_html(text, self.current_query)
                if matched:
                    self.note_preview.setHtml(f"<div style='white-space: pre-wrap;'>{highlighted_html}</div>")
                    return
            self.note_preview.setMarkdown(text)

    def create_folder(self):
        name, ok = QInputDialog.getText(self, '新建收藏文件夹', '文件夹名称')
        folder_name = name.strip()
        if not ok or not folder_name:
            return
        cur = self.user_conn.cursor()
        try:
            cur.execute('INSERT INTO folders(name) VALUES(?)', (folder_name,))
            self.user_conn.commit()
        except Exception:
            return
        cur.execute('SELECT id FROM folders WHERE name = ?', (folder_name,))
        row = cur.fetchone()
        if row:
            self.current_folder_id = int(row[0])
        self.load_folders()
        self.load_favorites_list()

    def delete_current_folder(self):
        folder_id = self.get_current_folder_id()
        if folder_id == 1:
            return
        item = self.folders_list.currentItem()
        if not item:
            return
        folder_name = item.text()
        reply = QMessageBox.question(self, '删除文件夹', f'确认删除文件夹“{folder_name}”？其中收藏会自动移动到“默认”文件夹。')
        if reply != QMessageBox.StandardButton.Yes:
            return
        cur = self.user_conn.cursor()
        cur.execute('UPDATE favorites SET folder_id = 1 WHERE folder_id = ?', (folder_id,))
        cur.execute('DELETE FROM folders WHERE id = ?', (folder_id,))
        self.user_conn.commit()
        self.current_folder_id = 1
        self.load_folders()
        self.load_favorites_list()
        if self.current_query and hasattr(self, 'favorite_button'):
            self.update_favorite_button_state(self.current_query)
        if self.current_query and hasattr(self, 'review_button'):
            self.update_review_button_state(self.current_query)

    def clear_detail(self):
        for i in reversed(range(self.detail_layout.count())):
            widget = self.detail_layout.itemAt(i).widget()
            if widget is not None:
                widget.setParent(None)
        self.translation_primary_widgets = []
        self.llm_translation_widgets = []
        self.note_preview_cache_key = None

    def closeEvent(self, event):
        self.conn.close()
        if hasattr(self, 'user_conn'):
            self.user_conn.close()
        event.accept()
