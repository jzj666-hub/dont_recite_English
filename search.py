import logging
import os
import sys

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QMainWindow, QVBoxLayout

# ================= 路径自适应魔法开始 =================
if getattr(sys, 'frozen', False):
    # 如果是打包后的 exe 运行，获取 exe 所在的真实目录
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # 如果是在开发环境直接运行 py 脚本，获取脚本所在目录
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# ================= 路径自适应魔法结束 =================

OFFLINE_ASSETS_DIR = os.path.join(BASE_DIR, "offline_assets")
PROJECT_ARGOS_PACKAGES_DIR = os.path.join(OFFLINE_ASSETS_DIR, "argos_packages")
PROJECT_STANZA_RESOURCES_DIR = os.path.join(OFFLINE_ASSETS_DIR, "stanza_resources")

if os.path.isdir(PROJECT_ARGOS_PACKAGES_DIR):
    os.environ["ARGOS_PACKAGES_DIR"] = PROJECT_ARGOS_PACKAGES_DIR
if os.path.isdir(PROJECT_STANZA_RESOURCES_DIR):
    os.environ["STANZA_RESOURCES_DIR"] = PROJECT_STANZA_RESOURCES_DIR


class StartupCuteDialog(QDialog):
    def __init__(self):
        super().__init__(None)
        self._mascot_frames = ["(=^･ω･^=)", "(=^･o･^=)", "(=^･ω･^=)", "(=^･ｪ･^=)"]
        self._frame_index = 0
        self._progress_value = 0

        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setFixedSize(520, 210)
        self.setStyleSheet(
            """
            QDialog {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #fdf2ff, stop:1 #ffeef7);
                border: 1px solid #f5c7e1;
                border-radius: 18px;
            }
            QLabel {
                color: #5c335c;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 16)
        root.setSpacing(10)

        header_row = QHBoxLayout()
        header_row.setSpacing(12)

        self.mascot_label = QLabel(self._mascot_frames[0])
        self.mascot_label.setStyleSheet("font-size: 30px; color: #7f4f95;")
        header_row.addWidget(self.mascot_label)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("I Love English")
        title.setStyleSheet("font-size: 22px; font-weight: 700; color: #7b2d8e;")
        subtitle = QLabel("词典精灵正在整理学习小屋...")
        subtitle.setStyleSheet("font-size: 12px; color: #9b5ea2;")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header_row.addLayout(title_box, 1)
        root.addLayout(header_row)

        self.status_label = QLabel("准备启动...")
        self.status_label.setStyleSheet("font-size: 14px; font-weight: 600; color: #69386e;")
        root.addWidget(self.status_label)

        self.track_label = QLabel("· · · · · · · · · ·")
        self.track_label.setStyleSheet("font-size: 18px; color: #b66599;")
        root.addWidget(self.track_label)

        self.percent_label = QLabel("0%")
        self.percent_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.percent_label.setStyleSheet("font-size: 12px; color: #8f5b8f;")
        root.addWidget(self.percent_label)

        self.hint_label = QLabel("请稍候，马上就好～")
        self.hint_label.setStyleSheet("font-size: 12px; color: #9b5ea2;")
        root.addWidget(self.hint_label)

        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self._tick_mascot)
        self.anim_timer.start(180)

    def _tick_mascot(self):
        self._frame_index = (self._frame_index + 1) % len(self._mascot_frames)
        self.mascot_label.setText(self._mascot_frames[self._frame_index])

    def set_progress(self, value, message):
        self._progress_value = max(0, min(100, int(value)))
        self.status_label.setText(message or "正在启动...")
        self.percent_label.setText(f"{self._progress_value}%")
        slots = 10
        filled = int(round(self._progress_value / 100 * slots))
        if self._progress_value > 0:
            filled = max(1, filled)
        track = ["♥" if i < filled else "·" for i in range(slots)]
        self.track_label.setText(" ".join(track))
        self._tick_mascot()


def build_dictionary_app_class(startup_progress=None):
    progress = startup_progress or (lambda *_: None)
    progress(6, "正在邀请功能模块入场...")
    from search_modules.ai_assistant import AIAssistantMixin
    progress(10, "正在装配基础能力...")
    from search_modules.bootstrap import BootstrapMixin
    from search_modules.infrastructure import InfrastructureMixin, patch_argos_stanza_offline_mode
    progress(15, "正在连线页面与交互...")
    from search_modules.llm_translation import LLMTranslationMixin
    from search_modules.navigation import NavigationMixin
    from search_modules.ui import UIMixin
    from search_modules.user_features import UserFeaturesMixin
    logging.getLogger("stanza").setLevel(logging.ERROR)
    patch_argos_stanza_offline_mode()
    progress(20, "基础组件准备完成")

    class DictionaryApp(
        QMainWindow,
        InfrastructureMixin,
        BootstrapMixin,
        UIMixin,
        NavigationMixin,
        LLMTranslationMixin,
        UserFeaturesMixin,
        AIAssistantMixin,
    ):
        ai_chunk_ready = pyqtSignal(str)
        ai_done = pyqtSignal()
        llm_result_ready = pyqtSignal(dict)
        ai_links_ready = pyqtSignal(dict)
        smart_favorite_ready = pyqtSignal(dict)
        inner_tool_result_ready = pyqtSignal(dict)

        def __init__(self, startup_progress=None):
            super().__init__()
            progress = startup_progress or (lambda *_: None)
            progress(30, "正在连接信号...")
            self.ai_chunk_ready.connect(self._append_ai_chunk_to_note, Qt.ConnectionType.QueuedConnection)
            self.ai_done.connect(self._finish_ai_generation, Qt.ConnectionType.QueuedConnection)
            self.llm_result_ready.connect(self.on_llm_translate_result, Qt.ConnectionType.QueuedConnection)
            self.ai_links_ready.connect(self.on_ai_links_result, Qt.ConnectionType.QueuedConnection)
            self.smart_favorite_ready.connect(self.on_ai_smart_favorite_result, Qt.ConnectionType.QueuedConnection)
            self.inner_tool_result_ready.connect(self.on_inner_tool_result, Qt.ConnectionType.QueuedConnection)
            progress(45, "正在初始化运行状态...")
            self.init_runtime_state()
            progress(60, "正在加载词库...")
            self.init_database()
            progress(74, "正在加载用户数据...")
            self.init_user_data()
            progress(88, "正在构建界面...")
            self.init_ui()
            progress(96, "正在加载离线翻译...")
            self.init_translator()
            progress(100, "启动完成")

    return DictionaryApp


if __name__ == '__main__':
    app = QApplication(sys.argv)
    startup = StartupCuteDialog()
    startup.show()
    app.processEvents()

    def on_startup_progress(value, message):
        startup.set_progress(value, message)
        app.processEvents()

    on_startup_progress(2, "准备启动...")
    DictionaryApp = build_dictionary_app_class(startup_progress=on_startup_progress)
    on_startup_progress(24, "正在唤醒词典核心...")
    window = DictionaryApp(startup_progress=on_startup_progress)
    on_startup_progress(100, "启动完成")
    startup.close()
    window.show()
    sys.exit(app.exec())
