import threading
from urllib.parse import quote
from PyQt6.QtCore import QUrl, QObject, pyqtSignal
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

class TTSClient(QObject):
    """
    一个简单的 API 调用封装模块，采用单例模式，支持流式播放（直接交给 QMediaPlayer 自动流式缓冲）。
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
        
        # 标记初始化完成
        self._initialized = True

    def play(self, text: str, voice: str = "en-US-GuyNeural", rate: str = "+0%", volume: str = "+0%", pitch: str = "+0Hz"):
        """
        合成并播放指定文本的语音。
        由于 QMediaPlayer 支持直接从 URL 播放，音频会自动进行边下边播的流式播放。
        """
        if not text:
            return
            
        # 构造带有参数的 URL，并对所有参数进行 URL 编码
        params = {
            "text": text,
            "voice": voice,
            "rate": rate,
            "volume": volume,
            "pitch": pitch
        }
        query_str = "&".join([f"{k}={quote(v)}" for k, v in params.items()])
        url_str = f"{self.base_url}?{query_str}"
        
        # 设置媒体源并启动播放
        self.player.setSource(QUrl(url_str))
        self.player.play()

    def stop(self):
        """
        停止当前播放
        """
        self.player.stop()

    def set_volume(self, value):
        """
        设置音量 (0.0 to 1.0)
        """
        self.audio_output.setVolume(value)

# 方便调用的快捷函数获取单例实例
def get_tts_client():
    return TTSClient()
