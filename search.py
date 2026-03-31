import logging
import os
import sys

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QApplication, QMainWindow

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
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

    def __init__(self):
        super().__init__()
        self.ai_chunk_ready.connect(self._append_ai_chunk_to_note)
        self.ai_done.connect(self._finish_ai_generation)
        self.llm_result_ready.connect(self.on_llm_translate_result)
        self.ai_links_ready.connect(self.on_ai_links_result)
        self.smart_favorite_ready.connect(self.on_ai_smart_favorite_result)
        self.inner_tool_result_ready.connect(self.on_inner_tool_result)
        self.init_runtime_state()
        self.init_database()
        self.init_user_data()
        self.init_ui()
        self.init_translator()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = DictionaryApp()
    window.show()
    sys.exit(app.exec())
