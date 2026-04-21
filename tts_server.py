import asyncio
import edge_tts
import uvicorn
from fastapi import FastAPI, Response, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Edge-TTS Backend", description="A simple TTS server using Microsoft Edge TTS")

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/tts")
async def tts(
    text: str = Query(..., description="要转换成语音的文字"),
    voice: str = Query("en-US-GuyNeural", description="说话人声音"),
    rate: str = Query("+0%", description="语速"),
    volume: str = Query("+0%", description="音量"),
    pitch: str = Query("+0Hz", description="音调")
):
    """
    接收文字并返回 MP3 音频流
    """
    try:
        # FastAPI 会自动解码 URL 参数，这导致原本表示正号的 '+' 符号被解析成了空格（' '）。
        # 我们在这里将其重新替换回 '+'，以满足 edge_tts 严格的正则匹配要求（^[+-]\d+%$）。
        rate = rate.replace(" ", "+")
        volume = volume.replace(" ", "+")
        pitch = pitch.replace(" ", "+")

        # 如果是默认值，就不传对应的参数，让 edge-tts 使用其内部默认逻辑，提高稳定性
        params = {"text": text, "voice": voice}
        if rate not in ("+0%", "0%"): params["rate"] = rate
        if volume not in ("+0%", "0%"): params["volume"] = volume
        if pitch not in ("+0Hz", "0Hz"): params["pitch"] = pitch
            
        communicate = edge_tts.Communicate(**params)
        
        # 使用流式返回（StreamingResponse），防止长文本导致的超时 (FFmpeg Error -138)
        async def audio_generator():
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    yield chunk["data"]
                    
        return StreamingResponse(audio_generator(), media_type="audio/mpeg")
    except Exception as exc:
        return Response(
            status_code=503,
            content=f"TTS synthesis failed: {str(exc)}",
            media_type="text/plain; charset=utf-8",
        )

@app.get("/voices")
async def get_voices():
    """
    获取所有可用的声音列表
    """
    voices = await edge_tts.VoicesManager.create()
    return voices.voices

if __name__ == "__main__":
    # 默认启动在 8000 端口
    uvicorn.run(app, host="127.0.0.1", port=8000)
