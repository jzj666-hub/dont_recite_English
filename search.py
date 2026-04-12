import logging
import os
import sys

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMainWindow, QProgressDialog

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
from search_modules.ai_assistant import AIAssistantMixin
from search_modules.bootstrap import BootstrapMixin
from search_modules.infrastructure import InfrastructureMixin, patch_argos_stanza_offline_mode
from search_modules.llm_translation import LLMTranslationMixin
from search_modules.navigation import NavigationMixin
from search_modules.ui import UIMixin
from search_modules.user_features import UserFeaturesMixin

logging.getLogger("stanza").setLevel(logging.ERROR)
patch_argos_stanza_offline_mode()


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
        progress(10, "正在连接信号...")
        self.ai_chunk_ready.connect(self._append_ai_chunk_to_note, Qt.ConnectionType.QueuedConnection)
        self.ai_done.connect(self._finish_ai_generation, Qt.ConnectionType.QueuedConnection)
        self.llm_result_ready.connect(self.on_llm_translate_result, Qt.ConnectionType.QueuedConnection)
        self.ai_links_ready.connect(self.on_ai_links_result, Qt.ConnectionType.QueuedConnection)
        self.smart_favorite_ready.connect(self.on_ai_smart_favorite_result, Qt.ConnectionType.QueuedConnection)
        self.inner_tool_result_ready.connect(self.on_inner_tool_result, Qt.ConnectionType.QueuedConnection)
        progress(30, "正在初始化运行状态...")
        self.init_runtime_state()
        progress(45, "正在加载词库...")
        self.init_database()
        progress(60, "正在加载用户数据...")
        self.init_user_data()
        progress(80, "正在构建界面...")
        self.init_ui()
        progress(92, "正在加载离线翻译...")
        self.init_translator()
        progress(100, "启动完成")


if __name__ == '__main__':
    app = QApplication(sys.argv)
    startup = QProgressDialog("正在启动...", "", 0, 100)
    startup.setWindowFlags(
        Qt.WindowType.Dialog
        | Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.WindowStaysOnTopHint
    )
    startup.setWindowTitle("启动中")
    startup.setWindowModality(Qt.WindowModality.ApplicationModal)
    startup.setCancelButton(None)
    startup.setMinimumDuration(0)
    startup.setAutoClose(False)
    startup.setAutoReset(False)
    startup.resize(520, 132)
    startup.setStyleSheet(
        """
        QProgressDialog {
            background-color: #1f2430;
            color: #e6edf3;
            border: 1px solid #3b4252;
            border-radius: 12px;
            padding: 16px;
            font-size: 14px;
        }
        QProgressBar {
            background-color: #2b3240;
            border: 1px solid #3b4252;
            border-radius: 8px;
            text-align: center;
            color: #d8dee9;
            min-height: 18px;
        }
        QProgressBar::chunk {
            border-radius: 7px;
            background-color: #5e81ac;
            margin: 1px;
        }
        """
    )
    startup.show()
    app.processEvents()

    def on_startup_progress(value, message):
        startup.setLabelText(message)
        startup.setValue(max(0, min(100, int(value))))
        app.processEvents()

    on_startup_progress(5, "准备启动...")
    window = DictionaryApp(startup_progress=on_startup_progress)
    startup.setValue(100)
    startup.close()
    window.show()
    sys.exit(app.exec())
