import threading
from urllib.parse import quote

from PyQt6.QtCore import QUrl, QObject
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtWidgets import QApplication, QMessageBox

class TTSClient(QObject):
    """
    TTS 调用封装模块，直接把本地 TTS 服务 URL 交给 QMediaPlayer 播放，
    让音频按网络流式方式边下边播。
    """
    _instance = None
    _lock = threading.Lock()
    def __new__(cls, *args, **kwargs):
        # 线程安全单例
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(TTSClient, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, parent=None):
        if self._initialized:
            return
        super().__init__(parent)

        # 初始化 QMediaPlayer 和它的输出后端
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)

        # 默认音量 1.0 (最大)
        self.audio_output.setVolume(1.0)

        # FastAPI 服务默认的基础 URL
        self.base_url = "http://127.0.0.1:8000/tts"
        self._play_seq = 0
        self._active_stream_seq = 0
        self.player.mediaStatusChanged.connect(self._on_media_status_changed)
        self.player.errorOccurred.connect(self._on_player_error)

        # 标记初始化完成
        self._initialized = True

    def play(self, text: str, voice: str = "en-US-GuyNeural", rate: str = "+0%", volume: str = "+0%", pitch: str = "+0Hz"):
        """
        合成并播放指定文本的语音。
        """
        if not text:
            return

        self._play_seq += 1
        seq = self._play_seq
        self._active_stream_seq = seq
        # 直接切换 source，减少 stop() 触发的底层解复用器销毁日志。
        self.player.setSource(QUrl(self._build_tts_url(text, voice, rate, volume, pitch)))
        self.player.play()

    def stop(self):
        """
        停止当前播放
        """
        self._play_seq += 1
        self._active_stream_seq = self._play_seq
        self.player.stop()

    def set_volume(self, value):
        """
        设置音量 (0.0 to 1.0)
        """
        self.audio_output.setVolume(value)

    def _build_tts_url(self, text, voice, rate, volume, pitch):
        params = {
            "text": text,
            "voice": voice,
            "rate": rate,
            "volume": volume,
            "pitch": pitch,
        }
        query_str = "&".join([f"{k}={quote(str(v))}" for k, v in params.items()])
        return f"{self.base_url}?{query_str}"

    def _on_media_status_changed(self, status):
        if self._active_stream_seq != self._play_seq:
            return
        if status == QMediaPlayer.MediaStatus.InvalidMedia:
            active = QApplication.activeWindow()
            QMessageBox.warning(active, "TTS 播放失败", "音频流无效，请确认本地 TTS 服务是否正常。")

    def _on_player_error(self, _error, error_string):
        if self._active_stream_seq != self._play_seq:
            return
        text = (error_string or "").strip() or "无法连接本地 TTS 服务（127.0.0.1:8000）。请先通过 start.bat 启动。"
        active = QApplication.activeWindow()
        QMessageBox.warning(active, "TTS 播放失败", text)

# 方便调用的快捷函数获取单例实例
def get_tts_client():
    return TTSClient()
