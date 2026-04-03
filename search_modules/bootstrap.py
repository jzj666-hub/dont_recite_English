import os
import sqlite3
from datetime import datetime

from search_modules.infrastructure import LLMCacheStore


class BootstrapMixin:
    def init_runtime_state(self):
        self.llm_translate_click_count = 0
        self.llm_target_text = ""
        self.llm_target_is_word = False
        self.llm_restore_kind = ""
        self.llm_restore_query = ""
        self.llm_last_response_text = ""
        self.translation_primary_widgets = []
        self.llm_translation_widgets = []
        self.query_page_stack = []
        self.current_page_kind = ""
        self.ai_link_suggest_btn = None
        self.favorite_option_btn = None
        self.note_preview_cache_key = None
        self.ai_chat_windows = []
        self.ai_chat_shortcut = None
        self.inner_active_tool = ""
        self.inner_current_session_id = None
        self.wordcraft_config = {}
        self.study_timer = None
        self.study_today_label = None
        self.study_last_tick_dt = datetime.now()

    def init_database(self):
        self.conn = sqlite3.connect('stardict.db')
        self.cursor = self.conn.cursor()

    def init_user_data(self):
        self.user_conn = sqlite3.connect('user_data.db')
        cur = self.user_conn.cursor()
        cur.execute('CREATE TABLE IF NOT EXISTS queries (query TEXT PRIMARY KEY, count INTEGER DEFAULT 0, last_at TEXT)')
        cur.execute('CREATE TABLE IF NOT EXISTS notes (query TEXT PRIMARY KEY, content TEXT, updated_at TEXT)')
        cur.execute("CREATE TABLE IF NOT EXISTS reviewing (query TEXT PRIMARY KEY, proficiency TEXT DEFAULT '人上人', created_at TEXT, last_visited_at TEXT)")
        cur.execute('CREATE TABLE IF NOT EXISTS word_links (id INTEGER PRIMARY KEY AUTOINCREMENT, word_a TEXT NOT NULL, word_b TEXT NOT NULL, created_at TEXT, UNIQUE(word_a, word_b))')
        cur.execute('CREATE TABLE IF NOT EXISTS inner_sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, tool TEXT NOT NULL, content TEXT, config_json TEXT, rating INTEGER, created_at TEXT, updated_at TEXT)')
        self.llm_cache_store = LLMCacheStore(self.user_conn)
        self.llm_cache_store.ensure_schema()
        self.migrate_reviewing_schema()
        self.user_conn.commit()
        cur.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')
        cur.execute('CREATE TABLE IF NOT EXISTS folders (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)')
        cur.execute('INSERT OR IGNORE INTO folders(id, name) VALUES(1, ?)', ('默认',))
        self.migrate_favorites_schema()
        self.user_conn.commit()
        self.load_settings()
        self.current_folder_id = 1

    def migrate_reviewing_schema(self):
        cur = self.user_conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='reviewing'")
        if not cur.fetchone():
            return
        cur.execute('PRAGMA table_info(reviewing)')
        cols = [c[1] for c in cur.fetchall()]
        if 'proficiency' not in cols:
            cur.execute("ALTER TABLE reviewing ADD COLUMN proficiency TEXT DEFAULT '人上人'")
        if 'last_visited_at' not in cols:
            cur.execute('ALTER TABLE reviewing ADD COLUMN last_visited_at TEXT')
        cur.execute("UPDATE reviewing SET proficiency = '人上人'")
        cur.execute('UPDATE reviewing SET last_visited_at = COALESCE(last_visited_at, created_at)')

    def migrate_favorites_schema(self):
        cur = self.user_conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='favorites'")
        row = cur.fetchone()
        if not row:
            cur.execute('CREATE TABLE favorites (id INTEGER PRIMARY KEY AUTOINCREMENT, query TEXT NOT NULL, folder_id INTEGER NOT NULL DEFAULT 1, created_at TEXT, UNIQUE(query, folder_id))')
            return
        cur.execute('PRAGMA table_info(favorites)')
        cols = [c[1] for c in cur.fetchall()]
        if 'folder_id' not in cols:
            cur.execute('CREATE TABLE favorites_new (id INTEGER PRIMARY KEY AUTOINCREMENT, query TEXT NOT NULL, folder_id INTEGER NOT NULL DEFAULT 1, created_at TEXT, UNIQUE(query, folder_id))')
            if 'query' in cols and 'created_at' in cols:
                cur.execute('INSERT OR IGNORE INTO favorites_new(query, folder_id, created_at) SELECT query, 1, created_at FROM favorites')
            elif 'query' in cols:
                cur.execute('INSERT OR IGNORE INTO favorites_new(query, folder_id, created_at) SELECT query, 1, NULL FROM favorites')
            cur.execute('DROP TABLE favorites')
            cur.execute('ALTER TABLE favorites_new RENAME TO favorites')

    def init_translator(self):
        self.translator = None
        from_code = "en"
        to_code = "zh"
        self.translator = self.get_local_translation(from_code, to_code)
        self.translator_available = self.translator is not None

    def get_local_translation(self, from_code, to_code):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        offline_assets_dir = os.path.join(base_dir, "offline_assets")
        argos_packages_dir = os.path.join(offline_assets_dir, "argos_packages")
        stanza_resources_dir = os.path.join(offline_assets_dir, "stanza_resources")
        if os.path.isdir(argos_packages_dir):
            os.environ["ARGOS_PACKAGES_DIR"] = argos_packages_dir
        if os.path.isdir(stanza_resources_dir):
            os.environ["STANZA_RESOURCES_DIR"] = stanza_resources_dir
        try:
            import argostranslate.translate
            installed_languages = argostranslate.translate.get_installed_languages()
        except Exception:
            return None
        from_lang = next((lang for lang in installed_languages if lang.code == from_code), None)
        to_lang = next((lang for lang in installed_languages if lang.code == to_code), None)
        if from_lang is None or to_lang is None:
            return None
        try:
            return from_lang.get_translation(to_lang)
        except Exception:
            return None

    def load_settings(self):
        self.settings = {}
        cur = self.user_conn.cursor()
        cur.execute('SELECT key, value FROM settings')
        for k, v in cur.fetchall():
            self.settings[k] = v
        if 'theme' not in self.settings:
            self.set_setting('theme', 'dark')
            self.settings['theme'] = 'dark'
        if 'api_url' not in self.settings:
            self.set_setting('api_url', '')
            self.settings['api_url'] = ''
        if 'api_key' not in self.settings:
            self.set_setting('api_key', '')
            self.settings['api_key'] = ''
        if 'model' not in self.settings:
            self.set_setting('model', '')
            self.settings['model'] = ''
        if 'model_high' not in self.settings:
            high = self.settings.get('model', '')
            self.set_setting('model_high', high)
            self.settings['model_high'] = high
        if 'model_mid' not in self.settings:
            self.set_setting('model_mid', '')
            self.settings['model_mid'] = ''
        if 'reviewing_sort_basis' not in self.settings:
            self.set_setting('reviewing_sort_basis', 'recommended')
            self.settings['reviewing_sort_basis'] = 'recommended'
        if 'font_english' not in self.settings:
            self.set_setting('font_english', 'Segoe UI')
            self.settings['font_english'] = 'Segoe UI'
        if 'font_chinese' not in self.settings:
            self.set_setting('font_chinese', 'Microsoft YaHei UI')
            self.settings['font_chinese'] = 'Microsoft YaHei UI'
        today = datetime.now().strftime('%Y-%m-%d')
        if 'study_minutes_date' not in self.settings:
            self.set_setting('study_minutes_date', today)
            self.settings['study_minutes_date'] = today
        if 'study_minutes_today' not in self.settings:
            self.set_setting('study_minutes_today', '0')
            self.settings['study_minutes_today'] = '0'
        if self.settings.get('study_minutes_date') != today:
            self.set_setting('study_minutes_date', today)
            self.set_setting('study_minutes_today', '0')
            self.settings['study_minutes_date'] = today
            self.settings['study_minutes_today'] = '0'

    def set_setting(self, key, value):
        cur = self.user_conn.cursor()
        cur.execute('INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value', (key, value))
        self.user_conn.commit()
