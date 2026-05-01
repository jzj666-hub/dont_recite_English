import os
import sqlite3
from datetime import datetime

from search_modules.infrastructure import LLMCacheStore


class BootstrapMixin:
    def init_runtime_state(self):
        self.llm_translate_click_count = 0
        self.llm_translate_request_seq = 0
        self.llm_target_text = ""
        self.llm_target_original_meaning = ""
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
        self.study_timer_card = None
        self.study_timer_title_label = None
        self.study_continuous_label = None
        self.study_rest_tip_label = None
        self.study_continuous_minutes = 0
        self.study_last_rest_reminder_block = 0
        self.study_last_tick_dt = datetime.now()

    def init_database(self):
        self.conn = sqlite3.connect('stardict.db')
        self.cursor = self.conn.cursor()

    def init_user_data(self):
        self.user_conn = sqlite3.connect('user_data.db')
        cur = self.user_conn.cursor()
        cur.execute('CREATE TABLE IF NOT EXISTS queries (query TEXT PRIMARY KEY, count INTEGER DEFAULT 0, last_at TEXT)')
        cur.execute('CREATE TABLE IF NOT EXISTS notes (query TEXT PRIMARY KEY, content TEXT, updated_at TEXT)')
        cur.execute(
            "CREATE TABLE IF NOT EXISTS reviewing ("
            "query TEXT PRIMARY KEY, "
            "proficiency TEXT DEFAULT '人上人', "
            "created_at TEXT, "
            "last_visited_at TEXT, "
            "last_active_search_at TEXT)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS reviewing_auto_remove_history ("
            "query_key TEXT PRIMARY KEY, "
            "auto_removed_count INTEGER DEFAULT 0, "
            "last_auto_removed_at TEXT, "
            "updated_at TEXT)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS word_links ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "word_a TEXT NOT NULL, "
            "word_b TEXT NOT NULL, "
            "link_type TEXT NOT NULL DEFAULT '近义词', "
            "created_at TEXT, "
            "UNIQUE(word_a, word_b))"
        )
        cur.execute('CREATE TABLE IF NOT EXISTS inner_sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, tool TEXT NOT NULL, content TEXT, config_json TEXT, rating INTEGER, created_at TEXT, updated_at TEXT)')
        cur.execute('CREATE TABLE IF NOT EXISTS doc_notes (file_path TEXT PRIMARY KEY, title TEXT, content TEXT, source_text TEXT, updated_at TEXT)')
        cur.execute('CREATE TABLE IF NOT EXISTS doc_annotations (id INTEGER PRIMARY KEY AUTOINCREMENT, file_path TEXT NOT NULL, start_pos INTEGER NOT NULL, end_pos INTEGER NOT NULL, selected_text TEXT NOT NULL, annotation TEXT NOT NULL, created_at TEXT, updated_at TEXT)')
        cur.execute('CREATE TABLE IF NOT EXISTS wordcraft_annotations (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER NOT NULL, start_pos INTEGER NOT NULL, end_pos INTEGER NOT NULL, selected_text TEXT NOT NULL, annotation TEXT NOT NULL, created_at TEXT, updated_at TEXT)')
        self.llm_cache_store = LLMCacheStore(self.user_conn)
        self.llm_cache_store.ensure_schema()
        self.migrate_reviewing_schema()
        self.migrate_wordcraft_annotations_schema()
        self.migrate_word_links_schema()
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
        if 'last_active_search_at' not in cols:
            cur.execute('ALTER TABLE reviewing ADD COLUMN last_active_search_at TEXT')
        cur.execute("UPDATE reviewing SET proficiency = '人上人'")
        cur.execute('UPDATE reviewing SET last_visited_at = COALESCE(last_visited_at, created_at)')
        cur.execute('UPDATE reviewing SET last_active_search_at = COALESCE(last_active_search_at, last_visited_at, created_at)')

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

    def migrate_wordcraft_annotations_schema(self):
        cur = self.user_conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='wordcraft_annotations'")
        if not cur.fetchone():
            return
        cur.execute('PRAGMA table_info(wordcraft_annotations)')
        cols = [c[1] for c in cur.fetchall()]
        required = {'session_id', 'start_pos', 'end_pos', 'selected_text', 'annotation', 'created_at', 'updated_at'}
        if required.issubset(set(cols)):
            return

        if 'selected_text' in cols and 'segment_key' in cols:
            selected_expr = 'COALESCE(selected_text, segment_key, "")'
        elif 'selected_text' in cols:
            selected_expr = 'COALESCE(selected_text, "")'
        elif 'segment_key' in cols:
            selected_expr = 'COALESCE(segment_key, "")'
        else:
            selected_expr = '""'

        if 'annotation' in cols and 'explain_text' in cols:
            annotation_expr = 'COALESCE(annotation, explain_text, "")'
        elif 'annotation' in cols:
            annotation_expr = 'COALESCE(annotation, "")'
        elif 'explain_text' in cols:
            annotation_expr = 'COALESCE(explain_text, "")'
        else:
            annotation_expr = '""'

        start_expr = 'COALESCE(start_pos, -1)' if 'start_pos' in cols else '-1'
        end_expr = 'COALESCE(end_pos, -1)' if 'end_pos' in cols else '-1'
        if 'created_at' in cols and 'updated_at' in cols:
            created_expr = 'COALESCE(created_at, updated_at, "")'
            updated_expr = 'COALESCE(updated_at, created_at, "")'
        elif 'created_at' in cols:
            created_expr = 'COALESCE(created_at, "")'
            updated_expr = 'COALESCE(created_at, "")'
        elif 'updated_at' in cols:
            created_expr = 'COALESCE(updated_at, "")'
            updated_expr = 'COALESCE(updated_at, "")'
        else:
            created_expr = '""'
            updated_expr = '""'

        cur.execute('DROP TABLE IF EXISTS wordcraft_annotations_new')
        cur.execute(
            'CREATE TABLE wordcraft_annotations_new ('
            'id INTEGER PRIMARY KEY AUTOINCREMENT, '
            'session_id INTEGER NOT NULL, '
            'start_pos INTEGER NOT NULL, '
            'end_pos INTEGER NOT NULL, '
            'selected_text TEXT NOT NULL, '
            'annotation TEXT NOT NULL, '
            'created_at TEXT, '
            'updated_at TEXT)'
        )
        cur.execute(
            'INSERT INTO wordcraft_annotations_new(session_id, start_pos, end_pos, selected_text, annotation, created_at, updated_at) '
            f'SELECT COALESCE(session_id, 0), {start_expr}, {end_expr}, {selected_expr}, {annotation_expr}, {created_expr}, {updated_expr} '
            'FROM wordcraft_annotations'
        )
        cur.execute('DROP TABLE wordcraft_annotations')
        cur.execute('ALTER TABLE wordcraft_annotations_new RENAME TO wordcraft_annotations')

    def migrate_word_links_schema(self):
        cur = self.user_conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='word_links'")
        if not cur.fetchone():
            return
        cur.execute('PRAGMA table_info(word_links)')
        cols = [c[1] for c in cur.fetchall()]
        if 'link_type' not in cols:
            cur.execute("ALTER TABLE word_links ADD COLUMN link_type TEXT NOT NULL DEFAULT '近义词'")
        cur.execute(
            "UPDATE word_links SET link_type = '近义词' "
            "WHERE link_type IS NULL OR TRIM(link_type) = '' "
            "OR link_type NOT IN ('近义词', '反义词', '形近词')"
        )

    def init_translator(self):
        self.translator = None
        self.zh_en_translator = None
        self.translator = self.get_local_translation("en", "zh")
        self.zh_en_translator = self.get_local_translation("zh", "en")
        self.translator_available = self.translator is not None or self.zh_en_translator is not None

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
        if 'ai_example_exam_level' not in self.settings:
            self.set_setting('ai_example_exam_level', '不限')
            self.settings['ai_example_exam_level'] = '不限'
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
        if 'tts_voice' not in self.settings:
            self.set_setting('tts_voice', 'en-US-GuyNeural')
            self.settings['tts_voice'] = 'en-US-GuyNeural'
        if 'tts_rate' not in self.settings:
            self.set_setting('tts_rate', '+0%')
            self.settings['tts_rate'] = '+0%'
        if 'force_topmost' not in self.settings:
            self.set_setting('force_topmost', '1')
            self.settings['force_topmost'] = '1'
        if 'reviewing_auto_remove_days' not in self.settings:
            self.set_setting('reviewing_auto_remove_days', '14')
            self.settings['reviewing_auto_remove_days'] = '14'

    def set_setting(self, key, value):
        cur = self.user_conn.cursor()
        cur.execute('INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value', (key, value))
        self.user_conn.commit()
