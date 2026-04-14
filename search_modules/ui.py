from datetime import datetime
import json

from PyQt6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, QTimer, Qt, QUrl
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QKeySequence, QPalette, QShortcut, QTextCursor, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QKeySequenceEdit,
    QScrollArea,
    QSlider,
    QStackedLayout,
    QTextBrowser,
    QTextEdit,
    QTabWidget,
    QGraphicsOpacityEffect,
    QVBoxLayout,
    QWidget,
    QGroupBox,
)

class ImportDropWidget(QWidget):
    def __init__(self, parent=None, callback=None, ai_callback=None):
        super().__init__(parent)
        self.callback = callback
        self.ai_callback = ai_callback
        self.setAcceptDrops(True)
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if not urls:
            return
        file_path = urls[0].toLocalFile()
        if file_path.lower().endswith('.txt') and self.callback:
            self.callback(file_path)
        elif self.ai_callback:
            self.ai_callback(file_path)
        elif self.callback:
            self.callback(file_path)


class _GlobalUIKeyFilter(QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner

    def eventFilter(self, obj, event):
        owner = self.owner
        if owner is None or event is None:
            return False
        if event.type() == QEvent.Type.KeyPress:
            return bool(owner.handle_global_ui_key_press(event))
        return False

from search_modules.infrastructure import build_highlighted_text_html
from search_modules.ai_prompts import default_ai_prompts, loads_prompts


class UIMixin:
    def get_ai_prompts(self):
        raw = self.settings.get("ai_prompts_json", "") if hasattr(self, "settings") else ""
        merged = dict(default_ai_prompts())
        user_obj = loads_prompts(raw)
        for k, v in (user_obj or {}).items():
            if isinstance(k, str) and isinstance(v, str) and k.strip():
                merged[k.strip()] = v
        return merged

    def update_ui_fonts(self):
        """
        字体设置变更后立即刷新界面：
        - 应用 QApplication 字体
        - 对当前已存在控件做一次 font 重新应用
        - 对“详情区”做一次轻量重建（复用当前查询）
        """
        self.apply_font_preferences()

        # 递归刷新现有控件字体：更新字体系列，不在这里做累加缩放，防止“设置完字体变两倍大”
        try:
            base = self.make_ui_font(10, False)
            fams = base.families()
            self.setFont(base)
            
            for w in self.findChildren(QWidget):
                f = w.font()
                if fams:
                    f.setFamilies(fams)
                # 不再执行乘以 1.4 的操作，由 base 字体统一管理
                w.setFont(f)

            # 最右侧会话框保持原来的 1.8 倍（相对于基础字号 10 的 18pt），不再相对于当前字号做乘法
            if hasattr(self, "inner_dialog_editor") and self.inner_dialog_editor is not None:
                try:
                    f2 = self.inner_dialog_editor.font()
                    # 直接设定为 18 号字（基础字号 10 * 1.8），或者是保留之前已经扩大的字号但不重复累加
                    f2.setPointSizeF(18.0)
                    self.inner_dialog_editor.setFont(f2)
                except Exception:
                    pass
        except Exception:
            pass

        # 详情区内容需要重建，才能让那些创建时写死的字体被替换为当前偏好
        try:
            if hasattr(self, "current_page_kind") and hasattr(self, "current_query") and self.current_query:
                kind = self.current_page_kind
                q = self.current_query
                if kind == "word" and hasattr(self, "show_word_detail"):
                    self.animate_detail_change(lambda: (self.clear_detail(), self.show_word_detail(q, skip_clear=True)))
                elif kind == "sentence" and hasattr(self, "translate_text"):
                    self.animate_detail_change(lambda: (self.clear_detail(), self.translate_text(q, skip_clear=True)))
        except Exception:
            pass

    def animate_detail_change(self, build_func):
        """
        让详情区在切换内容时先淡出，再构建新内容并淡入。
        build_func: 一个无参函数，用于构建详情区新内容（内部通常会 clear_detail 并重新 addWidget）。
        """
        if not hasattr(self, "detail_widget") or self.detail_widget is None:
            build_func()
            return

        # 停掉可能存在的旧动画，避免连点导致状态错乱
        prev = getattr(self, "_detail_fade_anim", None)
        if prev is not None:
            try:
                prev.stop()
            except Exception:
                pass
        self._detail_fade_anim = None

        # 以 QScrollArea 的 viewport 作为淡入淡出目标，可覆盖滚动区域整体（避免某些子控件不吃 effect）
        w = None
        if hasattr(self, "detail_area") and self.detail_area is not None:
            try:
                w = self.detail_area.viewport()
            except Exception:
                w = None
        if w is None:
            w = self.detail_widget
        old_effect = w.graphicsEffect()
        effect = old_effect if isinstance(old_effect, QGraphicsOpacityEffect) else QGraphicsOpacityEffect(w)
        w.setGraphicsEffect(effect)
        effect.setOpacity(1.0)

        fade_out = QPropertyAnimation(effect, b"opacity", self)
        # 更快淡出：点击后内容迅速“消失”，避免最后一刻突然清空的突兀感
        fade_out.setDuration(90)
        fade_out.setStartValue(float(effect.opacity()))
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.Type.OutCubic)

        def after_out():
            try:
                build_func()
            except Exception:
                # 即使构建失败，也不要让界面永远透明
                pass
            # 构建后可能 detail_widget 仍是同一个，重新取一次
            w2 = getattr(self, "detail_widget", None)
            if w2 is None:
                return
            # 淡入同样作用于 viewport（若存在）
            w_in = None
            if hasattr(self, "detail_area") and self.detail_area is not None:
                try:
                    w_in = self.detail_area.viewport()
                except Exception:
                    w_in = None
            if w_in is None:
                w_in = w2

            eff2 = w_in.graphicsEffect()
            if not isinstance(eff2, QGraphicsOpacityEffect):
                eff2 = QGraphicsOpacityEffect(w_in)
                w_in.setGraphicsEffect(eff2)
            eff2.setOpacity(0.0)
            fade_in = QPropertyAnimation(eff2, b"opacity", self)
            fade_in.setDuration(180)
            fade_in.setStartValue(0.0)
            fade_in.setEndValue(1.0)
            fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)

            def clear_effect():
                # 清理 effect：优先清理 viewport，其次 detail_widget
                if hasattr(self, "detail_area") and self.detail_area is not None:
                    try:
                        vp = self.detail_area.viewport()
                        if vp is not None and isinstance(vp.graphicsEffect(), QGraphicsOpacityEffect):
                            vp.setGraphicsEffect(None)
                    except Exception:
                        pass
                ww = getattr(self, "detail_widget", None)
                if ww is not None and isinstance(ww.graphicsEffect(), QGraphicsOpacityEffect):
                    ww.setGraphicsEffect(None)
                self._detail_fade_anim = None

            fade_in.finished.connect(clear_effect)
            self._detail_fade_anim = fade_in
            fade_in.start()

        fade_out.finished.connect(after_out)
        self._detail_fade_anim = fade_out
        fade_out.start()

    def build_font_choices(self):
        """
        返回字体选项列表：[(label, family, note), ...]
        label 用于下拉显示；family 用于实际保存；note 用于 tooltip/说明。
        """
        available = set(QFontDatabase.families())

        def pick(family, note):
            if family in available:
                label = f"{family}（{note}）" if note else family
                return (label, family, note)
            return None

        # 先放常用/推荐，再补全系统字体
        preferred = [
            ("Segoe UI", "默认英文字体，清晰耐看"),
            ("Calibri", "圆润现代，屏幕阅读友好"),
            ("Arial", "通用无衬线，兼容性强"),
            ("Consolas", "等宽字体，适合音标/代码/对齐"),
            ("Times New Roman", "衬线字体，偏传统排版风格"),
            ("Microsoft YaHei UI", "常见中文 UI 字体"),
            ("微软雅黑", "常见中文字体（部分系统显示为“Microsoft YaHei”）"),
            ("SimSun", "宋体，传统印刷风格"),
            ("SimHei", "黑体，标题感更强"),
            ("Noto Sans CJK SC", "谷歌 Noto 中文无衬线（若已安装）"),
            ("Source Han Sans SC", "思源黑体（若已安装）"),
        ]

        out = []
        seen = set()
        for fam, note in preferred:
            item = pick(fam, note)
            if item and item[1] not in seen:
                out.append(item)
                seen.add(item[1])

        # 追加剩余字体（不带注释）
        for fam in sorted(available, key=lambda s: s.lower()):
            if fam in seen:
                continue
            out.append((fam, fam, ""))
        return out

    def get_font_preferences(self):
        english = (self.settings.get('font_english', 'Segoe UI') or 'Segoe UI').strip()
        chinese = (self.settings.get('font_chinese', 'Microsoft YaHei UI') or 'Microsoft YaHei UI').strip()
        return english, chinese

    def make_ui_font(self, size=10, bold=False):
        english, chinese = self.get_font_preferences()
        font = QFont()
        font.setFamilies([english, chinese])
        # 全局非标题字号放大：小字号（<16）统一按 1.4 倍缩放；标题字号保持不变
        scale = 1.4
        target_size = float(size)
        if target_size < 16:
            target_size = target_size * scale
        font.setPointSizeF(target_size)
        font.setBold(bool(bold))
        return font

    def apply_font_preferences(self):
        app = QApplication.instance()
        if app is None:
            return
        base = self.make_ui_font(10, False)
        app.setFont(base)

    def init_study_timer(self):
        if not hasattr(self, 'study_today_label'):
            return
        self.study_last_tick_dt = datetime.now()
        self.study_timer = QTimer(self)
        self.study_timer.timeout.connect(self.on_study_timer_tick)
        self.study_timer.start(60000)
        self.on_study_timer_tick()

    def get_study_minutes_today(self):
        try:
            return max(0, int(self.settings.get('study_minutes_today', '0') or 0))
        except Exception:
            return 0

    def on_study_timer_tick(self):
        now = datetime.now()
        delta_min = int((now - self.study_last_tick_dt).total_seconds() // 60)
        if delta_min > 0:
            total = self.get_study_minutes_today() + delta_min
            self.set_setting('study_minutes_today', str(total))
            self.settings['study_minutes_today'] = str(total)
            self.study_last_tick_dt = now
        self.update_study_today_label()

    def update_study_today_label(self):
        if not hasattr(self, 'study_today_label') or self.study_today_label is None:
            return
        mins = self.get_study_minutes_today()
        self.study_today_label.setText(f"🐣 今天已经学了 {mins} 分钟啦～")

    def is_force_topmost_enabled(self):
        return str(self.settings.get('force_topmost', '1')).strip().lower() in ('1', 'true', 'yes', 'on')

    def apply_topmost_preference(self):
        enabled = self.is_force_topmost_enabled()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        self.show()

    def init_ui(self):
        self.setWindowTitle('英语查词翻译软件')
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.is_force_topmost_enabled())
        self.setGeometry(100, 100, 900, 700)
        self.apply_theme()
        self.apply_font_preferences()
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
        self.main_tabs.addTab(ext_page, "溯游")
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
        title_label = QLabel('🌊 溯游 Tracing')
        title_label.setFont(self.make_ui_font(24, True))
        title_label.setStyleSheet('color: #61dafb;')
        title_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        header_layout.addWidget(title_label)

        # 溯游寓意标注
        tracing_meta = QLabel('【溯游态】 逆流而上，穷源竟委；“道阻且长”，真意乃现。')
        tracing_meta.setFont(self.make_ui_font(10, False))
        tracing_meta.setStyleSheet('color: #abb2bf; margin-bottom: 5px;')
        tracing_meta.setWordWrap(True)
        self.study_today_label = QLabel("")
        self.study_today_label.setFont(self.make_ui_font(11, False))
        self.study_today_label.setStyleSheet('color: #ffb86b; margin-left: 12px;')
        self.study_today_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        header_layout.addWidget(self.study_today_label)
        header_layout.addStretch()
        self.settings_btn = QPushButton('设置')
        self.settings_btn.setFixedHeight(32)
        self.settings_btn.clicked.connect(self.open_settings_dialog)
        header_layout.addWidget(self.settings_btn)
        left_layout.addWidget(header_widget)
        left_layout.addWidget(tracing_meta)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('输入单词或句子...')
        self.search_input.setFont(self.make_ui_font(14, False))
        self.search_input.textChanged.connect(self.on_search_text_changed)
        self.search_input.returnPressed.connect(self.on_enter_pressed)
        left_layout.addWidget(self.search_input)
        self.search_input.keyPressEvent = self.on_search_key_press
        self.candidates_list = QListWidget()
        self.candidates_list.setFont(self.make_ui_font(12, False))
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

        self.detail_tab_widget = QTabWidget()
        self.detail_tab_widget.setDocumentMode(True)

        self.detail_info_tab = QScrollArea()
        self.detail_info_tab.setWidgetResizable(True)
        self.detail_info_widget = QWidget()
        self.detail_info_layout = QVBoxLayout()
        self.detail_info_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.detail_info_widget.setLayout(self.detail_info_layout)
        self.detail_info_tab.setWidget(self.detail_info_widget)

        self.detail_note_tab = QWidget()
        self.detail_note_layout = QVBoxLayout()
        self.detail_note_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.detail_note_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_note_tab.setLayout(self.detail_note_layout)

        self.detail_ai_tab = QScrollArea()
        self.detail_ai_tab.setWidgetResizable(True)
        self.detail_ai_widget = QWidget()
        self.detail_ai_layout = QVBoxLayout()
        self.detail_ai_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.detail_ai_layout.setContentsMargins(12, 12, 12, 12)
        self.detail_ai_widget.setLayout(self.detail_ai_layout)
        self.detail_ai_tab.setWidget(self.detail_ai_widget)

        self.detail_tab_widget.addTab(self.detail_info_tab, "基础信息")
        self.detail_tab_widget.addTab(self.detail_note_tab, "批注")
        self.detail_tab_widget.addTab(self.detail_ai_tab, "AI 服务")

        left_layout.addWidget(self.detail_tab_widget)
        fav_title = QLabel('⭐ 收藏夹')
        fav_title.setFont(self.make_ui_font(16, True))
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
        self.favorites_list.setFont(self.make_ui_font(12, False))
        self.favorites_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.favorites_list.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.favorites_list.itemActivated.connect(self.on_favorite_activated)
        self.favorites_list.itemClicked.connect(self.on_favorite_activated)
        right_layout.addWidget(self.favorites_list)
        self.inner_page = QWidget()
        self.main_tabs.addTab(self.inner_page, "入海")
        
        # 第三态：引泾 (Channeling) - 放到最后
        import_page = ImportDropWidget(callback=self.on_import_txt_clicked, ai_callback=self.on_import_ai_clicked)
        self.main_tabs.addTab(import_page, "引泾")
        import_layout = QVBoxLayout()
        import_layout.setSpacing(30)
        import_layout.setContentsMargins(40, 40, 40, 40)
        import_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        import_page.setLayout(import_layout)

        import_title_label = QLabel('🌾 引泾 Channeling')
        import_title_label.setFont(self.make_ui_font(28, True))
        import_title_label.setStyleSheet('color: #e5c07b;')
        import_layout.addWidget(import_title_label)

        import_meta = QLabel('【引泾】 引渠灌溉，纳四方新词；“疏而导之”，汇入蓄水之池。以此态开启你的语词森林。')
        import_meta.setFont(self.make_ui_font(12, False))
        import_meta.setStyleSheet('color: #abb2bf; margin-bottom: 20px;')
        import_meta.setWordWrap(True)
        import_layout.addWidget(import_meta)

        self.import_btn = QPushButton("📁 标准导入：选择或拖拽单词本 (.txt)")
        self.import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.import_btn.setFixedHeight(120)
        self.import_btn.setStyleSheet("""
            QPushButton {
                background-color: #282c34;
                border: 2px dashed #e5c07b;
                border-radius: 15px;
                color: #e5c07b;
                font-size: 18px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #353b45;
                border: 2px solid #e5c07b;
                color: #ffffff;
            }
        """)
        self.import_btn.clicked.connect(lambda: self.on_import_txt_clicked())
        import_layout.addWidget(self.import_btn)

        self.import_ai_btn = QPushButton("🤖 AI 智能解析：导入任意格式文件")
        self.import_ai_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.import_ai_btn.setFixedHeight(120)
        self.import_ai_btn.setStyleSheet("""
            QPushButton {
                background-color: #282c34;
                border: 2px dashed #61dafb;
                border-radius: 15px;
                color: #61dafb;
                font-size: 18px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #353b45;
                border: 2px solid #61dafb;
                color: #ffffff;
            }
        """)
        self.import_ai_btn.clicked.connect(lambda: self.on_import_ai_clicked())
        import_layout.addWidget(self.import_ai_btn)

        # 导入状态/日志
        self.import_status_label = QLabel('')
        self.import_status_label.setFont(self.make_ui_font(11, False))
        self.import_status_label.setStyleSheet('color: #98c379;')
        self.import_status_label.setWordWrap(True)
        import_layout.addWidget(self.import_status_label)

        import_tip = QLabel('标准导入：适用于每行一个单词的 .txt 文件。\nAI 智能解析：适用于 CSV、Excel 导出、非标准格式等任意文件，AI 会自动识别文件结构并提取单词。\n支持直接拖拽文件到此页面（.txt 走标准流程，其他格式走 AI 解析）。')
        import_tip.setFont(self.make_ui_font(10, False))
        import_tip.setStyleSheet('color: #5c6370; font-style: italic;')
        import_tip.setWordWrap(True)
        import_layout.addWidget(import_tip)

        # 导出部分
        export_group = QGroupBox("📦 词条导出")
        export_group.setFont(self.make_ui_font(14, True))
        export_group.setStyleSheet("QGroupBox{ color: #98c379; border: 1px solid #3d3d3d; border-radius: 8px; margin-top: 20px; padding: 20px; }")
        export_layout = QVBoxLayout()
        export_group.setLayout(export_layout)
        
        export_row = QHBoxLayout()
        export_row.setSpacing(10)
        self.export_source_combo = QComboBox()
        self.export_source_combo.setFixedHeight(40)
        self.export_source_combo.setMinimumWidth(180)
        export_row.addWidget(self.export_source_combo, 1)

        self.export_include_trans_cb = QCheckBox("加翻译")
        self.export_include_phonetic_cb = QCheckBox("加音标")
        export_row.addWidget(self.export_include_trans_cb)
        export_row.addWidget(self.export_include_phonetic_cb)

        self.export_format_combo = QComboBox()
        self.export_format_combo.setFixedHeight(40)
        self.export_format_combo.addItems([".txt", ".csv", ".md", ".json"])
        export_row.addWidget(self.export_format_combo)
        
        self.export_btn_ui = QPushButton("导出")
        self.export_btn_ui.setFixedHeight(40)
        self.export_btn_ui.setCursor(Qt.CursorShape.PointingHandCursor)
        self.export_btn_ui.setStyleSheet("""
            QPushButton {
                background-color: #98c379;
                color: #1e1e1e;
                border-radius: 6px;
                font-weight: bold;
                padding: 0 20px;
            }
            QPushButton:hover {
                background-color: #b1d69d;
            }
        """)
        self.export_btn_ui.clicked.connect(self.on_export_words_clicked)
        export_row.addWidget(self.export_btn_ui)
        export_layout.addLayout(export_row)
        
        export_desc = QLabel("支持从一个特定的收藏夹或者“在背状态”的单词列表中导出所有查询词。")
        export_desc.setFont(self.make_ui_font(10, False))
        export_desc.setStyleSheet("color: #abb2bf;")
        export_layout.addWidget(export_desc)
        import_layout.addWidget(export_group)

        # 第四态：析文（Markdown 导入 + 划线注解）
        self.doc_page = QWidget()
        self.main_tabs.addTab(self.doc_page, "析文")
        doc_layout = QVBoxLayout()
        doc_layout.setSpacing(12)
        doc_layout.setContentsMargins(18, 18, 18, 18)
        self.doc_page.setLayout(doc_layout)

        doc_title = QLabel("🪶 析文 Exegesis")
        doc_title.setFont(self.make_ui_font(24, True))
        doc_title.setStyleSheet("color: #e5c07b;")
        doc_layout.addWidget(doc_title)

        doc_meta = QLabel("【析文】 披卷入微，循句采义；墨线所至，疑处可问，注解可存。")
        doc_meta.setWordWrap(True)
        doc_meta.setStyleSheet("color: #abb2bf; margin-bottom: 8px;")
        doc_layout.addWidget(doc_meta)

        doc_desc = QLabel("仅支持 Markdown（.md）。框选后会自动生成并保存 AI 注释，片段会被划线标记，鼠标在片段上停留约 0.5 秒会打开注释窗口。")
        doc_desc.setWordWrap(True)
        doc_desc.setStyleSheet("color: #5c6370;")
        doc_layout.addWidget(doc_desc)

        doc_btn_row = QWidget()
        doc_btn_layout = QHBoxLayout()
        doc_btn_layout.setContentsMargins(0, 0, 0, 0)
        doc_btn_row.setLayout(doc_btn_layout)
        self.doc_new_btn = QPushButton("📝 新建 Markdown（.md）")
        self.doc_new_btn.clicked.connect(self.on_doc_create_markdown_clicked)
        doc_btn_layout.addWidget(self.doc_new_btn)
        self.doc_import_btn = QPushButton("📁 导入 Markdown（.md）")
        self.doc_import_btn.clicked.connect(self.on_import_document_clicked)
        doc_btn_layout.addWidget(self.doc_import_btn)
        self.doc_save_btn = QPushButton("💾 保存 Markdown")
        self.doc_save_btn.clicked.connect(self.on_doc_save_markdown_clicked)
        doc_btn_layout.addWidget(self.doc_save_btn)
        self.doc_delete_btn = QPushButton("🗑 删除 Markdown")
        self.doc_delete_btn.clicked.connect(self.on_doc_delete_markdown_clicked)
        doc_btn_layout.addWidget(self.doc_delete_btn)
        self.doc_annotations_btn = QPushButton("🗂 注释管理")
        self.doc_annotations_btn.clicked.connect(self.on_doc_annotation_manage_clicked)
        doc_btn_layout.addWidget(self.doc_annotations_btn)
        doc_layout.addWidget(doc_btn_row)

        self.doc_current_path_label = QLabel("当前文档：未导入")
        self.doc_current_path_label.setWordWrap(True)
        self.doc_current_path_label.setStyleSheet("color: #5c6370;")
        doc_layout.addWidget(self.doc_current_path_label)

        self.doc_content_host = QWidget()
        self.doc_content_stack = QStackedLayout()
        self.doc_content_stack.setContentsMargins(0, 0, 0, 0)
        self.doc_content_host.setLayout(self.doc_content_stack)

        self.doc_md_preview = QTextBrowser()
        self.doc_md_preview.setOpenExternalLinks(False)
        self.doc_md_preview.setPlaceholderText("Markdown 浏览模式")
        self.doc_md_preview.setMouseTracking(True)
        self.doc_md_preview.viewport().setMouseTracking(True)
        self.doc_md_preview._orig_mouse_press = self.doc_md_preview.mousePressEvent
        self.doc_md_preview._orig_mouse_double_click = self.doc_md_preview.mouseDoubleClickEvent
        self.doc_md_preview._orig_mouse_move = self.doc_md_preview.mouseMoveEvent
        self.doc_md_preview._orig_leave_event = self.doc_md_preview.leaveEvent
        self.doc_md_preview.mousePressEvent = self.on_doc_preview_mouse_press
        self.doc_md_preview.mouseDoubleClickEvent = self.on_doc_preview_double_click
        self.doc_md_preview.mouseMoveEvent = self.on_doc_preview_mouse_move
        self.doc_md_preview.leaveEvent = self.on_doc_preview_leave
        self.doc_md_preview.selectionChanged.connect(self.on_doc_preview_selection_changed)
        self.doc_content_stack.addWidget(self.doc_md_preview)

        self.doc_content_edit = QTextEdit()
        self.doc_content_edit.setReadOnly(False)
        self.doc_content_edit.setPlaceholderText("Markdown 编辑区：仅支持 .md 文档。")
        self.doc_content_edit.setMouseTracking(True)
        self.doc_content_edit.viewport().setMouseTracking(True)
        self.doc_content_edit._orig_mouse_move = self.doc_content_edit.mouseMoveEvent
        self.doc_content_edit._orig_leave_event = self.doc_content_edit.leaveEvent
        self.doc_content_edit.mouseMoveEvent = self.on_doc_edit_mouse_move
        self.doc_content_edit.leaveEvent = self.on_doc_edit_leave
        self.doc_content_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.doc_content_edit.customContextMenuRequested.connect(self.on_doc_content_context_menu)
        self.doc_content_edit.textChanged.connect(self.on_doc_content_text_changed)
        self.doc_content_edit.selectionChanged.connect(self.on_doc_selection_changed)
        self.doc_content_edit.focusOutEvent = self.on_doc_edit_focus_out
        self.doc_content_stack.addWidget(self.doc_content_edit)
        self.doc_content_stack.setCurrentWidget(self.doc_md_preview)
        if hasattr(self, "_install_doc_edit_outside_click_filter"):
            self._install_doc_edit_outside_click_filter()
        doc_main_row = QWidget()
        doc_main_layout = QHBoxLayout()
        doc_main_layout.setContentsMargins(0, 0, 0, 0)
        doc_main_layout.setSpacing(12)
        doc_main_row.setLayout(doc_main_layout)
        doc_main_layout.addWidget(self.doc_content_host, 5)

        doc_side_panel = QWidget()
        doc_side_layout = QVBoxLayout()
        doc_side_layout.setContentsMargins(0, 0, 0, 0)
        doc_side_layout.setSpacing(8)
        doc_side_panel.setLayout(doc_side_layout)
        doc_files_title = QLabel("项目 Markdown")
        doc_files_title.setFont(self.make_ui_font(11, True))
        doc_side_layout.addWidget(doc_files_title)
        self.doc_files_list = QListWidget()
        self.doc_files_list.setMinimumWidth(220)
        self.doc_files_list.itemActivated.connect(self.on_doc_file_item_activated)
        self.doc_files_list.itemClicked.connect(self.on_doc_file_item_activated)
        doc_side_layout.addWidget(self.doc_files_list, 1)
        doc_main_layout.addWidget(doc_side_panel, 2)
        doc_layout.addWidget(doc_main_row, 1)
        if hasattr(self, "refresh_doc_markdown_file_list"):
            self.refresh_doc_markdown_file_list()

        if hasattr(self, 'init_export_ui'):
            self.init_export_ui()
        inner_layout = QVBoxLayout()
        inner_layout.setSpacing(12)
        inner_layout.setContentsMargins(12, 12, 12, 12)
        self.inner_page.setLayout(inner_layout)

        # 入海标题与寓意标注
        merging_title_label = QLabel('⛵ 入海 Merging')
        merging_title_label.setFont(self.make_ui_font(24, True))
        merging_title_label.setStyleSheet('color: #98c379;')
        inner_layout.addWidget(merging_title_label)
        
        merging_meta = QLabel('【入海】 纳万川入怀，织锦绣于胸。此前之词，今后之我。')
        merging_meta.setFont(self.make_ui_font(11, False))
        merging_meta.setStyleSheet('color: #abb2bf; margin-bottom: 10px;')
        merging_meta.setWordWrap(True)
        inner_layout.addWidget(merging_meta)
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
        inner_content_layout.addWidget(inner_left_panel, 3)
        inner_fav_title = QLabel("⭐ 收藏夹（当前文件夹）")
        inner_fav_title.setFont(self.make_ui_font(14, True))
        inner_left_layout.addWidget(inner_fav_title)
        self.inner_favorites_list = QListWidget()
        self.inner_favorites_list.itemActivated.connect(self.on_favorite_activated)
        self.inner_favorites_list.itemClicked.connect(self.on_favorite_activated)

        # 收藏夹排序依据
        fav_sort_row = QWidget()
        fav_sort_layout = QHBoxLayout()
        fav_sort_layout.setContentsMargins(0, 0, 0, 0)
        fav_sort_row.setLayout(fav_sort_layout)
        fav_sort_label = QLabel("排序依据：")
        fav_sort_label.setFont(self.make_ui_font(10, False))
        fav_sort_label.setFixedWidth(80)
        fav_sort_layout.addWidget(fav_sort_label)
        self.fav_sort_combo = QComboBox()
        for label, val in self.get_basis_options():
            self.fav_sort_combo.addItem(label, val)
        self.fav_sort_combo.currentIndexChanged.connect(self.refresh_internal_page)
        fav_sort_layout.addWidget(self.fav_sort_combo, 1)

        inner_left_layout.addWidget(fav_sort_row)
        inner_left_layout.addWidget(self.inner_favorites_list, 1)
        review_title = QLabel("🔥 在背状态单词")
        review_title.setFont(self.make_ui_font(14, True))
        inner_left_layout.addWidget(review_title)
        review_sort_row = QWidget()
        review_sort_layout = QHBoxLayout()
        review_sort_layout.setContentsMargins(0, 0, 0, 0)
        review_sort_row.setLayout(review_sort_layout)
        review_sort_label = QLabel("排序依据：")
        review_sort_label.setFont(self.make_ui_font(10, False))
        review_sort_label.setFixedWidth(80)
        review_sort_layout.addWidget(review_sort_label)
        self.reviewing_sort_combo = QComboBox()
        review_sort_layout.addWidget(self.reviewing_sort_combo, 1)
        inner_left_layout.addWidget(review_sort_row)
        self.reviewing_words_list = QListWidget()
        self.reviewing_words_list.itemActivated.connect(self.on_favorite_activated)
        self.reviewing_words_list.itemClicked.connect(self.on_favorite_activated)
        inner_left_layout.addWidget(self.reviewing_words_list, 1)
        inner_right_panel = QWidget()
        inner_right_layout = QVBoxLayout()
        inner_right_layout.setContentsMargins(0, 0, 0, 0)
        inner_right_layout.setSpacing(10)
        inner_right_panel.setLayout(inner_right_layout)
        inner_content_layout.addWidget(inner_right_panel, 7)
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
        self.inner_session_list.setMinimumWidth(120)
        self.inner_session_list.setMaximumWidth(400)
        self.inner_dialog_area_layout.addWidget(self.inner_session_list, 2)
        # 右侧会话区：支持在"普通会话文本"和"随机考词面板"之间切换
        self.inner_dialog_host = QWidget()
        self.inner_dialog_stack = QStackedLayout()
        self.inner_dialog_stack.setContentsMargins(0, 0, 0, 0)
        self.inner_dialog_host.setLayout(self.inner_dialog_stack)
        self.inner_dialog_editor = QTextEdit()
        self.inner_dialog_editor.setPlaceholderText("用于 AI 对话或其他特殊用途（待定）")
        # 放大最右侧"会话框"文本（不是会话历史列表）到 1.8 倍 (基础 10 * 1.8 = 18pt)
        try:
            f = self.inner_dialog_editor.font()
            f.setPointSizeF(18.0)
            self.inner_dialog_editor.setFont(f)
        except Exception:
            pass
        self.inner_quiz_panel = QWidget()
        self.inner_dialog_stack.addWidget(self.inner_dialog_editor)
        self.inner_dialog_stack.addWidget(self.inner_quiz_panel)
        self.inner_dialog_stack.setCurrentWidget(self.inner_dialog_editor)
        self.inner_dialog_area_layout.addWidget(self.inner_dialog_host, 5)
        inner_right_layout.addWidget(self.inner_dialog_area, 1)
        self.inner_confirm_btn = QPushButton("确认已选中不懂片段")
        self.inner_confirm_btn.setVisible(False)
        inner_right_layout.addWidget(self.inner_confirm_btn)
        if hasattr(self, 'init_inner_workspace'):
            self.init_inner_workspace()
        if hasattr(self, 'init_reviewing_sort_ui'):
            self.init_reviewing_sort_ui()
        self.load_folders()
        self.load_favorites_list()
        self.refresh_internal_page()
        self.apply_styles()
        if hasattr(self, 'setup_ai_chat_shortcuts'):
            self.setup_ai_chat_shortcuts()
        self.setup_global_ui_shortcuts()
        self.init_study_timer()

    def get_shortcut_pool(self):
        pool = []
        for mod in ("Alt", "Ctrl+Alt"):
            for key in ("1", "2", "3", "4", "5", "6", "7", "8", "9", "0"):
                pool.append(f"{mod}+{key}")
            for key in "QWERTYUIOPASDFGHJKLZXCVBNM":
                pool.append(f"{mod}+{key}")
        return pool

    def get_default_button_shortcuts(self):
        preferred = {
            "settings_btn": "Alt+S",
            "add_folder_btn": "Alt+N",
            "delete_folder_btn": "Alt+D",
            "import_btn": "Alt+I",
            "import_ai_btn": "Alt+A",
            "export_btn_ui": "Alt+O",
            "doc_new_btn": "Alt+M",
            "doc_import_btn": "Alt+P",
            "doc_save_btn": "Alt+V",
            "doc_delete_btn": "Alt+X",
            "doc_annotations_btn": "Alt+G",
            "inner_tool_action_1": "Alt+1",
            "inner_tool_action_2": "Alt+2",
            "inner_confirm_btn": "Alt+C",
        }
        defaults = {}
        used = set()
        for attr in self._shortcut_button_order:
            seq = preferred.get(attr, "")
            if seq:
                low = seq.lower()
                if low not in used:
                    defaults[attr] = seq
                    used.add(low)
        pool = self.get_shortcut_pool()
        for attr in self._shortcut_button_order:
            if attr in defaults:
                continue
            chosen = ""
            for seq in pool:
                low = seq.lower()
                if low not in used:
                    chosen = seq
                    used.add(low)
                    break
            defaults[attr] = chosen
        return defaults

    def collect_shortcut_buttons(self):
        buttons = {}
        order = []
        auto_idx = 1
        for btn in self.findChildren(QPushButton):
            name = (btn.objectName() or "").strip()
            if not name:
                while True:
                    candidate = f"auto_btn_{auto_idx}"
                    auto_idx += 1
                    if candidate not in buttons:
                        name = candidate
                        break
                btn.setObjectName(name)
            if name in buttons:
                continue
            buttons[name] = btn
            order.append(name)
        return buttons, order

    def setup_global_ui_shortcuts(self):
        if getattr(self, "_global_ui_shortcuts_ready", False):
            return
        self._shortcut_buttons, self._shortcut_button_order = self.collect_shortcut_buttons()
        self._button_shortcut_hints_visible = False
        self._button_shortcut_hint_labels = []
        self._button_shortcuts = self.load_button_shortcuts()
        self.apply_button_shortcuts()

        self.shortcut_toggle_hints = QShortcut(QKeySequence("Shift+E"), self)
        self.shortcut_toggle_hints.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_toggle_hints.activated.connect(self.toggle_button_shortcut_hints)

        self.shortcut_edit_hints = QShortcut(QKeySequence("Shift+R"), self)
        self.shortcut_edit_hints.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_edit_hints.activated.connect(self.open_button_shortcut_editor)

        app = QApplication.instance()
        if app is not None:
            self._global_ui_key_filter = _GlobalUIKeyFilter(self)
            app.installEventFilter(self._global_ui_key_filter)
        self._global_ui_shortcuts_ready = True

    def load_button_shortcuts(self):
        defaults = self.get_default_button_shortcuts()
        merged = dict(defaults)
        raw = self.settings.get("button_shortcuts_json", "") if hasattr(self, "settings") else ""
        user_obj = {}
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    user_obj = parsed
            except Exception:
                user_obj = {}
        for key, val in user_obj.items():
            if key in merged and isinstance(val, str):
                seq = QKeySequence(val.strip())
                text = seq.toString(QKeySequence.SequenceFormat.PortableText).strip()
                merged[key] = text
        serialized = json.dumps(merged, ensure_ascii=False)
        if hasattr(self, "settings"):
            if self.settings.get("button_shortcuts_json", "") != serialized:
                self.set_setting("button_shortcuts_json", serialized)
                self.settings["button_shortcuts_json"] = serialized
        return merged

    def apply_button_shortcuts(self):
        for attr, btn in self._shortcut_buttons.items():
            key_text = (self._button_shortcuts.get(attr, "") or "").strip()
            if key_text:
                btn.setShortcut(QKeySequence(key_text))
            else:
                btn.setShortcut(QKeySequence())

    def toggle_button_shortcut_hints(self):
        if getattr(self, "_button_shortcut_hints_visible", False):
            self.hide_button_shortcut_hints()
        else:
            self.show_button_shortcut_hints()

    def show_button_shortcut_hints(self):
        self.hide_button_shortcut_hints()
        hints = []
        for attr in self._shortcut_button_order:
            btn = self._shortcut_buttons.get(attr)
            if btn is None or not btn.isVisible():
                continue
            key_text = (self._button_shortcuts.get(attr, "") or "").strip()
            if not key_text:
                continue
            label = QLabel(key_text, btn)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            label.setStyleSheet(
                "QLabel{background-color:#f1c40f;color:#111111;border:1px solid #b38f00;border-radius:4px;padding:1px 6px;font-size:10px;font-weight:700;}"
            )
            label.adjustSize()
            x = max(0, (btn.width() - label.width()) // 2)
            y = 2
            label.move(x, y)
            label.show()
            label.raise_()
            hints.append(label)
        self._button_shortcut_hint_labels = hints
        self._button_shortcut_hints_visible = True

    def hide_button_shortcut_hints(self):
        for label in getattr(self, "_button_shortcut_hint_labels", []):
            try:
                label.hide()
                label.deleteLater()
            except Exception:
                pass
        self._button_shortcut_hint_labels = []
        self._button_shortcut_hints_visible = False

    def open_button_shortcut_editor(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("快捷键设置")
        dlg.resize(580, 560)
        layout = QVBoxLayout()
        dlg.setLayout(layout)
        tip = QLabel("设置每个按钮的快捷键（Shift+E 显示，Shift+R 可再次修改）。")
        tip.setWordWrap(True)
        layout.addWidget(tip)
        form = QFormLayout()
        editors = {}
        for attr in self._shortcut_button_order:
            btn = self._shortcut_buttons.get(attr)
            if btn is None:
                continue
            editor = QKeySequenceEdit(dlg)
            editor.setKeySequence(QKeySequence((self._button_shortcuts.get(attr, "") or "").strip()))
            label_text = (btn.text() or attr).replace("\n", " ").strip()
            form.addRow(label_text, editor)
            editors[attr] = editor
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(buttons)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        updated = dict(self._button_shortcuts)
        used = {}
        for attr in self._shortcut_button_order:
            editor = editors.get(attr)
            if editor is None:
                continue
            key_text = editor.keySequence().toString(QKeySequence.SequenceFormat.PortableText).strip()
            if key_text:
                low = key_text.lower()
                if low in used and used[low] != attr:
                    QMessageBox.warning(self, "快捷键冲突", f"“{key_text}”重复，请改成不冲突的快捷键。")
                    return
                used[low] = attr
            updated[attr] = key_text

        self._button_shortcuts = updated
        serialized = json.dumps(updated, ensure_ascii=False)
        self.set_setting("button_shortcuts_json", serialized)
        self.settings["button_shortcuts_json"] = serialized
        self.apply_button_shortcuts()
        if self._button_shortcut_hints_visible:
            self.show_button_shortcut_hints()

    def handle_global_ui_key_press(self, event):
        if event is None:
            return False
        return self.route_typing_to_search_input(event)

    def route_typing_to_search_input(self, event):
        if not hasattr(self, "main_tabs") or not hasattr(self, "search_input"):
            return False
        if self.main_tabs.currentIndex() != 0:
            return False
        mods = event.modifiers()
        if mods & (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.MetaModifier
            | Qt.KeyboardModifier.ShiftModifier
        ):
            return False
        focus = QApplication.focusWidget()
        if focus is not None:
            if (
                focus.inherits("QLineEdit")
                or focus.inherits("QTextEdit")
                or focus.inherits("QPlainTextEdit")
                or focus.inherits("QTextBrowser")
                or focus.inherits("QComboBox")
                or focus.inherits("QAbstractSpinBox")
            ):
                return False
        text = event.text() or ""
        if len(text) != 1 or (not text.isascii()) or (not text.isalpha()):
            return False
        self.search_input.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search_input.insert(text)
        return True

    def on_main_tab_changed(self, index):
        if hasattr(self, 'main_tabs'):
            prev_anim = getattr(self, '_tab_fade_anim', None)
            if prev_anim is not None:
                prev_anim.stop()
            prev_page = getattr(self, '_tab_fade_page', None)
            prev_effect = getattr(self, '_tab_fade_effect', None)
            if prev_page is not None and prev_effect is not None and prev_page.graphicsEffect() is prev_effect:
                prev_page.setGraphicsEffect(None)
            page = self.main_tabs.widget(index)
            if page is not None:
                effect = QGraphicsOpacityEffect(page)
                page.setGraphicsEffect(effect)
                effect.setOpacity(0.0)
                anim = QPropertyAnimation(effect, b"opacity", self)
                anim.setDuration(260)
                anim.setStartValue(0.0)
                anim.setEndValue(1.0)
                anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                self._tab_fade_page = page
                self._tab_fade_effect = effect
                self._tab_fade_anim = anim

                def clear_effect():
                    if page.graphicsEffect() is effect:
                        page.setGraphicsEffect(None)
                    self._tab_fade_page = None
                    self._tab_fade_effect = None
                    self._tab_fade_anim = None

                anim.finished.connect(clear_effect)
                anim.start()
        if index == 1:
            self.refresh_internal_page()
        if getattr(self, "_button_shortcut_hints_visible", False):
            self.show_button_shortcut_hints()

    def set_dark_theme(self):
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.Base, QColor(45, 45, 45))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(35, 35, 35))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(45, 45, 45))
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
                'accent_hover': '#0d47a1',
                'highlight_bg': '#e1bee7',  # 浅色主题紫色高亮背景
                'highlight_text': '#4a148c',  # 浅色主题紫色高亮文字
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
            'accent_hover': '#21a1c4',
            'highlight_bg': '#6b4f00',  # 深色主题金色高亮背景
            'highlight_text': '#ffe9a8',  # 深色主题金色高亮文字
        }

    def apply_styles(self):
        if not hasattr(self, 'settings'):
            self.settings = {'theme': 'dark'}
        if not hasattr(self, 'colors'):
            self.colors = self.compute_theme_colors(self.settings.get('theme', 'dark'))
        c = self.colors
        
        # 通用输入框样式 - 应用到所有输入相关组件
        input_style = f"""
            QLineEdit, QTextEdit, QTextBrowser, QPlainTextEdit, QComboBox, QAbstractSpinBox {{
                background-color: {c['widget_bg']};
                border: 2px solid {c['border']};
                border-radius: 8px;
                color: {c['text']};
                padding: 8px 12px;
                selection-background-color: {c['accent']};
                selection-color: {c['accent_text']};
            }}
            QLineEdit:focus, QTextEdit:focus, QTextBrowser:focus, QPlainTextEdit:focus, QComboBox:focus, QAbstractSpinBox:focus {{
                border: 2px solid {c['accent']};
            }}
            QLineEdit:hover, QTextEdit:hover, QTextBrowser:hover, QPlainTextEdit:hover, QComboBox:hover, QAbstractSpinBox:hover {{
                border: 2px solid {c['accent']};
            }}
            QLineEdit:disabled, QTextEdit:disabled, QTextBrowser:disabled, QPlainTextEdit:disabled, QComboBox:disabled, QAbstractSpinBox:disabled {{
                background-color: {c['bg_alt']};
                color: {c['text_muted']};
            }}
        """
        
        # 应用通用样式到所有输入组件
        if hasattr(self, 'search_input'):
            self.search_input.setStyleSheet(input_style)
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
            self.note_edit.setStyleSheet(input_style)
            self.note_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        if hasattr(self, 'note_preview'):
            self.note_preview.setStyleSheet(input_style)
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
        if hasattr(self, 'reviewing_sort_combo'):
            self.reviewing_sort_combo.setStyleSheet(input_style)
        if hasattr(self, 'fav_sort_combo'):
            self.fav_sort_combo.setStyleSheet(input_style)
        if hasattr(self, 'inner_session_list'):
            self.inner_session_list.setStyleSheet(
                f"QListWidget{{background-color:{c['widget_bg']};border:1px solid {c['border']};border-radius:8px;color:{c['text']};padding:5px;}}QListWidget::item{{padding:8px;border-bottom:1px solid {c['bg_alt']};}}QListWidget::item:selected{{background-color:{c['accent']};color:{c['accent_text']};}}"
            )
        if hasattr(self, 'inner_dialog_editor'):
            self.inner_dialog_editor.setStyleSheet(input_style)
        if hasattr(self, 'doc_md_preview'):
            self.doc_md_preview.setStyleSheet(input_style)
            self.doc_md_preview.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        if hasattr(self, 'doc_content_edit'):
            self.doc_content_edit.setStyleSheet(input_style)
            self.doc_content_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        if hasattr(self, 'ai_free_input'):
            self.ai_free_input.setStyleSheet(input_style)
        if hasattr(self, 'inner_tool_title'):
            self.inner_tool_title.setStyleSheet(f"color:{c['accent']};font-weight:600;")

        # 右键菜单在深色主题下保持可读
        menu_style = (
            f"QMenu{{background-color:{c['widget_bg']};color:{c['text']};border:1px solid {c['border']};}}"
            f"QMenu::item{{padding:6px 22px;}}"
            f"QMenu::item:selected{{background-color:{c['accent']};color:{c['accent_text']};}}"
            f"QMenu::separator{{height:1px;background:{c['border']};margin:4px 8px;}}"
            f"QToolTip{{background-color:{c['widget_bg']};color:{c['text']};border:1px solid {c['border']};padding:6px;}}"
        )
        # 统一挂到窗口级样式，覆盖动态创建的输入框（例如随机考词中的答题输入框）
        self.setStyleSheet(input_style + "\n" + menu_style)

        self.apply_font_preferences()
        self.update_study_today_label()

    def open_settings_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("设置")
        dlg.setMinimumSize(700, 600)
        dlg.resize(800, 700)
        
        # 应用当前主题到对话框
        if hasattr(self, 'colors'):
            c = self.colors
            dlg.setStyleSheet(f"""
                QDialog {{ 
                    background-color: {c['bg']}; 
                    color: {c['text']}; 
                }}
                QScrollArea {{
                    border: none;
                    background-color: transparent;
                }}
                QScrollBar:vertical {{
                    background-color: {c['widget_bg']};
                    width: 12px;
                    border-radius: 6px;
                    margin: 0px;
                }}
                QScrollBar::handle:vertical {{
                    background-color: {c['accent']};
                    border-radius: 6px;
                    min-height: 30px;
                }}
                QScrollBar::handle:vertical:hover {{
                    background-color: {c['accent_hover']};
                }}
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                    border: none;
                    background: none;
                }}
                QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                    background: none;
                }}
            """)
        
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        # 创建内容容器
        content_widget = QWidget()
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
        
        # TTS 英文设置
        tts_en_voices = [
            ("美式英语 - Guy (男)", "en-US-GuyNeural"),
            ("美式英语 - Aria (女)", "en-US-AriaNeural"),
            ("英式英语 - Thomas (男)", "en-GB-ThomasNeural"),
            ("英式英语 - Sonia (女)", "en-GB-SoniaNeural"),
        ]
        tts_cn_voices = [
            ("中文普通话 - 晓晓 (女)", "zh-CN-XiaoxiaoNeural"),
            ("中文普通话 - 云希 (男)", "zh-CN-YunxiNeural"),
            ("中文普通话 - 晓依 (女)", "zh-CN-XiaoyiNeural"),
        ]

        def create_rate_control(pref_key):
            container = QWidget()
            layout = QHBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            container.setLayout(layout)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(-100, 100)
            try:
                rate_str = self.settings.get(pref_key, '+0%')
                val = int(rate_str.replace('%', ''))
                slider.setValue(val)
            except:
                slider.setValue(0)
            label = QLabel(f"{'+' if slider.value() > 0 else ''}{slider.value()}%")
            label.setFixedWidth(50)
            slider.valueChanged.connect(lambda v: label.setText(f"{'+' if v > 0 else ''}{v}%"))
            layout.addWidget(slider, 1)
            layout.addWidget(label)
            return slider, container

        tts_voice_combo = QComboBox()
        for label, val in tts_en_voices:
            tts_voice_combo.addItem(label, val)
        curr_en = self.settings.get('tts_voice', 'en-US-GuyNeural')
        for i in range(tts_voice_combo.count()):
            if tts_voice_combo.itemData(i) == curr_en:
                tts_voice_combo.setCurrentIndex(i)
                break
        tts_rate_slider, tts_rate_container = create_rate_control('tts_rate')

        tts_voice_cn_combo = QComboBox()
        for label, val in tts_cn_voices:
            tts_voice_cn_combo.addItem(label, val)
        curr_cn = self.settings.get('tts_voice_cn', 'zh-CN-XiaoxiaoNeural')
        for i in range(tts_voice_cn_combo.count()):
            if tts_voice_cn_combo.itemData(i) == curr_cn:
                tts_voice_cn_combo.setCurrentIndex(i)
                break
        tts_rate_cn_slider, tts_rate_cn_container = create_rate_control('tts_rate_cn')
        font_english_edit = QComboBox()
        font_chinese_edit = QComboBox()
        force_topmost_chk = QCheckBox("启用")
        force_topmost_chk.setChecked(self.is_force_topmost_enabled())
        font_english_edit.setEditable(True)
        font_chinese_edit.setEditable(True)
        eng, zh = self.get_font_preferences()

        # 字体选项：带“特色说明”，并允许手动输入自定义字体
        font_choices = self.build_font_choices() if hasattr(self, "build_font_choices") else []
        for label, family, note in font_choices:
            font_english_edit.addItem(label, family)
            font_chinese_edit.addItem(label, family)
            if note:
                idx_e = font_english_edit.count() - 1
                idx_c = font_chinese_edit.count() - 1
                font_english_edit.setItemData(idx_e, note, Qt.ItemDataRole.ToolTipRole)
                font_chinese_edit.setItemData(idx_c, note, Qt.ItemDataRole.ToolTipRole)

        def set_combo_to_family(combo, family):
            target = (family or "").strip()
            if not target:
                return
            for i in range(combo.count()):
                if (combo.itemData(i) or "").strip().lower() == target.lower():
                    combo.setCurrentIndex(i)
                    return
            combo.setEditText(target)

        set_combo_to_family(font_english_edit, eng)
        set_combo_to_family(font_chinese_edit, zh)
        
        # AI 提示词设置 - 分类标签页
        ai_prompts_tabs = QTabWidget()
        ai_prompts_tabs.setDocumentMode(True)
        
        # 获取当前提示词设置
        try:
            current_prompts = loads_prompts(self.settings.get("ai_prompts_json", "")) if hasattr(self, "settings") else {}
            if not current_prompts:
                current_prompts = default_ai_prompts()
        except Exception:
            current_prompts = default_ai_prompts()
        
        # 分类定义
        categories = {
            "通用设置": ["chat_system", "json_system", "translator_system", "note_ai_system"],
            "词条页AI服务": ["detail_ai_header", "detail_ai_tail"],
            "右键语境提问": ["selection_answer_rules"],
            "AI收藏夹推荐": ["smart_favorite_prompt"],
            "AI关联词推荐": ["suggest_links_prompt"],
            "LLM补充翻译": ["llm_translate_prompt"],
            "随机考词": ["quiz_hint_prompt", "quiz_grade_prompt"],
            "文档解读": ["doc_reader_explain_prompt"],
        }
        
        # 创建每个分类的标签页
        all_prompt_edits = {}
        for category_name, prompt_keys in categories.items():
            tab_widget = QWidget()
            tab_layout = QVBoxLayout()
            tab_layout.setSpacing(10)
            tab_widget.setLayout(tab_layout)
            
            # 添加分类说明
            category_desc = QLabel(self._get_category_description(category_name))
            category_desc.setWordWrap(True)
            category_desc.setStyleSheet("color: #888; font-size: 12px; margin-bottom: 10px;")
            tab_layout.addWidget(category_desc)
            
            # 添加每个提示词的编辑框
            for key in prompt_keys:
                prompt_data = current_prompts.get(key, {})
                if isinstance(prompt_data, str):
                    prompt_text = prompt_data
                    agent_info = "未知"
                    purpose_info = "未知"
                else:
                    prompt_text = prompt_data.get("text", "")
                    agent_info = prompt_data.get("agent", "未知")
                    purpose_info = prompt_data.get("purpose", "未知")
                
                # 提示词标题和说明
                prompt_header = QLabel(f"<b>{key}</b>")
                prompt_header.setStyleSheet("color: #61dafb; font-size: 14px; margin-top: 10px;")
                tab_layout.addWidget(prompt_header)
                
                prompt_desc = QLabel(f"用途：{purpose_info} | 使用位置：{agent_info}")
                prompt_desc.setStyleSheet("color: #aaa; font-size: 11px; margin-bottom: 5px;")
                tab_layout.addWidget(prompt_desc)
                
                # 提示词编辑框
                prompt_edit = QTextEdit()
                prompt_edit.setMinimumHeight(80)
                prompt_edit.setMaximumHeight(150)
                prompt_edit.setPlainText(prompt_text)
                prompt_edit.setPlaceholderText(f"请输入 {key} 的提示词内容")
                all_prompt_edits[key] = prompt_edit
                tab_layout.addWidget(prompt_edit)
            
            tab_layout.addStretch()
            ai_prompts_tabs.addTab(tab_widget, category_name)
        
        # 高级选项：原始JSON编辑
        advanced_tab = QWidget()
        advanced_layout = QVBoxLayout()
        advanced_tab.setLayout(advanced_layout)
        
        advanced_desc = QLabel("<b>高级选项：直接编辑JSON</b><br/>仅建议熟悉JSON格式的用户使用此功能。")
        advanced_desc.setWordWrap(True)
        advanced_layout.addWidget(advanced_desc)
        
        ai_prompts_json_edit = QTextEdit()
        ai_prompts_json_edit.setMinimumHeight(200)
        ai_prompts_json_edit.setPlainText(json.dumps(current_prompts, ensure_ascii=False, indent=2))
        ai_prompts_json_edit.setPlaceholderText("AI 提示词 JSON（高级选项）")
        advanced_layout.addWidget(ai_prompts_json_edit)
        
        prompts_btn_row = QWidget()
        prompts_btn_layout = QHBoxLayout()
        prompts_btn_layout.setContentsMargins(0, 0, 0, 0)
        prompts_btn_row.setLayout(prompts_btn_layout)
        
        prompts_restore_btn = QPushButton("恢复默认 AI 提示词")
        prompts_apply_json_btn = QPushButton("应用JSON到分类编辑")
        prompts_btn_layout.addWidget(prompts_restore_btn)
        prompts_btn_layout.addWidget(prompts_apply_json_btn)
        prompts_btn_layout.addStretch()
        advanced_layout.addWidget(prompts_btn_row)
        
        ai_prompts_tabs.addTab(advanced_tab, "高级编辑")
        
        def restore_prompts():
            default_prompts = default_ai_prompts()
            ai_prompts_json_edit.setPlainText(json.dumps(default_prompts, ensure_ascii=False, indent=2))
            # 同时更新分类编辑框
            for key, edit in all_prompt_edits.items():
                prompt_data = default_prompts.get(key, {})
                if isinstance(prompt_data, str):
                    edit.setPlainText(prompt_data)
                else:
                    edit.setPlainText(prompt_data.get("text", ""))
        
        def apply_json_to_edits():
            try:
                json_text = ai_prompts_json_edit.toPlainText().strip()
                if json_text:
                    parsed = json.loads(json_text)
                    for key, edit in all_prompt_edits.items():
                        prompt_data = parsed.get(key, {})
                        if isinstance(prompt_data, str):
                            edit.setPlainText(prompt_data)
                        else:
                            edit.setPlainText(prompt_data.get("text", ""))
            except Exception as e:
                QMessageBox.warning(dlg, "JSON解析错误", f"无法解析JSON：{str(e)}")
        
        prompts_restore_btn.clicked.connect(restore_prompts)
        prompts_apply_json_btn.clicked.connect(apply_json_to_edits)
        
        # 应用统一的输入框样式
        if hasattr(self, 'colors'):
            c = self.colors
            input_style = f"""
                QLineEdit, QTextEdit, QTextBrowser, QComboBox {{
                    background-color: {c['widget_bg']};
                    border: 2px solid {c['border']};
                    border-radius: 8px;
                    color: {c['text']};
                    padding: 8px 12px;
                    selection-background-color: {c['accent']};
                    selection-color: {c['accent_text']};
                }}
                QLineEdit:focus, QTextEdit:focus, QTextBrowser:focus, QComboBox:focus {{
                    border: 2px solid {c['accent']};
                }}
                QLineEdit:hover, QTextEdit:hover, QTextBrowser:hover, QComboBox:hover {{
                    border: 2px solid {c['accent']};
                }}
            """
            theme_combo.setStyleSheet(input_style)
            api_url_edit.setStyleSheet(input_style)
            api_key_edit.setStyleSheet(input_style)
            model_mid_edit.setStyleSheet(input_style)
            model_high_edit.setStyleSheet(input_style)
            tts_voice_combo.setStyleSheet(input_style)
            tts_voice_cn_combo.setStyleSheet(input_style)
            self.export_source_combo.setStyleSheet(input_style)
            font_english_edit.setStyleSheet(input_style)
            font_chinese_edit.setStyleSheet(input_style)
            ai_prompts_json_edit.setStyleSheet(input_style)
            
            # 为滑动条应用美化样式
            slider_style = f"""
                QSlider::groove:horizontal {{
                    border: 1px solid {c['border']};
                    height: 8px;
                    background: {c['bg_alt']};
                    margin: 2px 0;
                    border-radius: 4px;
                }}
                QSlider::handle:horizontal {{
                    background: {c['accent']};
                    border: 1px solid {c['accent']};
                    width: 18px;
                    height: 18px;
                    margin: -5px 0;
                    border-radius: 9px;
                }}
                QSlider::handle:horizontal:hover {{
                    background: {c['accent_hover']};
                }}
            """
            tts_rate_slider.setStyleSheet(slider_style)
            tts_rate_cn_slider.setStyleSheet(slider_style)
            
            # 为所有分类编辑框应用样式
            for edit in all_prompt_edits.values():
                edit.setStyleSheet(input_style)
        
        # 设置表单布局
        form.addRow("主题", theme_combo)
        form.addRow("API URL", api_url_edit)
        form.addRow("API Key", api_key_edit)
        form.addRow("中级模型名", model_mid_edit)
        form.addRow("高级模型名", model_high_edit)
        form.addRow("TTS 语音 (英文)", tts_voice_combo)
        form.addRow("TTS 语速 (英文)", tts_rate_container)
        form.addRow("TTS 语音 (中文)", tts_voice_cn_combo)
        form.addRow("TTS 语速 (中文)", tts_rate_cn_container)
        form.addRow("英文字体", font_english_edit)
        form.addRow("中文字体", font_chinese_edit)
        form.addRow("强制置顶本页面", force_topmost_chk)
        form.addRow("AI 提示词", ai_prompts_tabs)
        
        # 设置内容容器的布局
        content_layout = QVBoxLayout()
        content_layout.addLayout(form)
        content_layout.addStretch()
        content_widget.setLayout(content_layout)
        
        # 将内容容器放入滚动区域
        scroll_area.setWidget(content_widget)
        
        # 创建按钮区域
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        
        # 主布局：滚动区域 + 按钮
        main_layout = QVBoxLayout()
        main_layout.addWidget(scroll_area, 1)  # 滚动区域占据主要空间
        main_layout.addWidget(buttons)
        dlg.setLayout(main_layout)
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
            self.set_setting('tts_voice', tts_voice_combo.currentData())
            rate_val = tts_rate_slider.value()
            self.set_setting('tts_rate', f"{'+' if rate_val >= 0 else ''}{rate_val}%")

            self.set_setting('tts_voice_cn', tts_voice_cn_combo.currentData())
            rate_cn_val = tts_rate_cn_slider.value()
            self.set_setting('tts_rate_cn', f"{'+' if rate_cn_val >= 0 else ''}{rate_cn_val}%")
            
            eng_val = (font_english_edit.currentData() or font_english_edit.currentText() or "").strip()
            zh_val = (font_chinese_edit.currentData() or font_chinese_edit.currentText() or "").strip()
            self.set_setting('font_english', eng_val or 'Segoe UI')
            self.set_setting('font_chinese', zh_val or 'Microsoft YaHei UI')
            self.set_setting('force_topmost', '1' if force_topmost_chk.isChecked() else '0')
            
            # 处理AI提示词设置（从分类编辑框构建JSON）
            merged_prompts = {}
            default_prompts = default_ai_prompts()
            
            # 从分类编辑框收集所有提示词
            for key, edit in all_prompt_edits.items():
                prompt_text = edit.toPlainText().strip()
                if prompt_text:
                    # 保持原有的结构（如果有agent和purpose信息）
                    default_data = default_prompts.get(key, {})
                    if isinstance(default_data, dict) and 'agent' in default_data:
                        merged_prompts[key] = {
                            "agent": default_data.get("agent", ""),
                            "purpose": default_data.get("purpose", ""),
                            "text": prompt_text
                        }
                    else:
                        merged_prompts[key] = prompt_text
            
            # 保存到设置
            if merged_prompts:
                self.set_setting("ai_prompts_json", json.dumps(merged_prompts, ensure_ascii=False, indent=2))
            else:
                # 如果没有修改，保持原设置
                pass
            self.load_settings()
            self.apply_topmost_preference()
            self.apply_theme()
            self.apply_styles()
            # 立刻刷新当前界面字体（含那些创建时写死字体的控件，需要重绘/重建内容区）
            if hasattr(self, "update_ui_fonts") and callable(getattr(self, "update_ui_fonts")):
                self.update_ui_fonts()

    def build_note_section(self):
        note_title = QLabel("批注")
        note_title.setFont(self.make_ui_font(12, True))
        note_title.setStyleSheet('color: #61dafb; margin-top: 15px; margin-bottom: 5px;')
        self.detail_note_layout.addWidget(note_title)
        save_note_btn = QPushButton("保存批注")
        save_note_btn.clicked.connect(self.save_current_note)
        self.detail_note_layout.addWidget(save_note_btn)
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
        self.detail_note_layout.addWidget(self.note_host)
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

    def _get_category_description(self, category_name):
        """获取分类的详细说明"""
        descriptions = {
            "通用设置": "这些是基础的系统提示词，影响AI在所有功能中的基本行为。包括聊天角色定义、JSON输出要求、翻译风格等。",
            "词条页AI服务": "控制词条详情页中AI服务的提示词，包括AI批注生成、词条解释等功能的开头和结尾约束。",
            "右键语境提问": "当您在文本中右键选择文字并提问时使用的提示词，控制AI对选中文本的回答风格和内容要求。",
            "AI收藏夹推荐": "当使用AI智能推荐收藏夹功能时使用的提示词，控制AI如何根据当前词条选择合适的收藏夹。",
            "AI关联词推荐": "AI推荐相关单词功能使用的提示词，控制AI如何选择和推荐与当前单词相关的词汇。",
            "LLM补充翻译": "LLM翻译功能使用的提示词，控制AI如何生成详细的单词释义、例句和常见用法。",
            "随机考词": "随机考词功能中使用的提示词，包括单词提示（轻/中/强提示）和最终评档的规则设置。",
            "文档解读": "析文标签页中，针对框选 Markdown 片段进行 AI 划线注解（流式弹框输出）时使用的提示词。",
        }
        return descriptions.get(category_name, "该分类的详细说明。")

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
                # 获取当前主题的高亮颜色
                highlight_bg = self.colors.get('highlight_bg', '#6b4f00')
                highlight_text = self.colors.get('highlight_text', '#ffe9a8')
                highlighted_html, matched = build_highlighted_text_html(text, self.current_query, highlight_bg, highlight_text)
                if matched:
                    self.note_preview.setHtml(f"<div style='white-space: pre-wrap;'>{highlighted_html}</div>")
                    return
            self.note_preview.setMarkdown(text)

    def create_folder(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("新建收藏文件夹")
        root = QVBoxLayout()
        form = QFormLayout()
        name_edit = QLineEdit()
        form.addRow("文件夹名称", name_edit)
        root.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        root.addWidget(buttons)
        dlg.setLayout(root)
        if hasattr(self, 'colors'):
            c = self.colors
            dlg.setStyleSheet(f"QDialog {{ background-color: {c['bg']}; color: {c['text']}; }}")
            input_style = (
                f"QLineEdit{{background-color:{c['widget_bg']};border:2px solid {c['border']};"
                f"border-radius:8px;color:{c['text']};padding:8px 12px;}}"
                f"QLineEdit:focus{{border:2px solid {c['accent']};}}"
            )
            name_edit.setStyleSheet(input_style)
        if not dlg.exec():
            return
        folder_name = name_edit.text().strip()
        if not folder_name:
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
        def clear_layout(layout):
            if layout is None: return
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
                elif item.layout():
                    clear_layout(item.layout())

        clear_layout(self.detail_layout)
        clear_layout(self.detail_info_layout)
        clear_layout(self.detail_note_layout)
        clear_layout(self.detail_ai_layout)
        self.translation_primary_widgets = []
        self.llm_translation_widgets = []
        self.note_preview_cache_key = None

    def closeEvent(self, event):
        self.conn.close()
        if hasattr(self, 'user_conn'):
            self.user_conn.close()
        event.accept()
