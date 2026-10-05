import gc
import os
import threading

from .config import ASR_PATH, MODEL_PATH


class VoiceEngine:
    def __init__(self):
        self.model = None
        self.lock = threading.Lock()
        self.device = "未加载"

    def load(self):
        if self.model is not None:
            return self.model
        if not (MODEL_PATH / "model.safetensors").is_file():
            raise RuntimeError("模型尚未下载，请先运行 setup.ps1 或 scripts/download_models.py。")
        import torch
        from qwen_tts import Qwen3TTSModel

        torch.set_num_threads(min(8, os.cpu_count() or 4))
        device = os.environ.get("VOICE_DEVICE", "cuda:0" if torch.cuda.is_available() else "cpu")
        if device.startswith("cuda"):
            free, _ = torch.cuda.mem_get_info()
            if free < 2.8 * 1024 ** 3:
                raise RuntimeError("可用显存不足 2.8GB。请关闭占用显存的游戏等程序后重试。")
        self.device = device
        self.model = Qwen3TTSModel.from_pretrained(
            str(MODEL_PATH), device_map=device,
            dtype=torch.bfloat16 if device.startswith("cuda") else torch.float32,
            attn_implementation="sdpa",
        )
        return self.model

    def unload(self):
        with self.lock:
            self.model = None
            self.device = "未加载"
            gc.collect()
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    def transcribe(self, path):
        from faster_whisper import WhisperModel

        if not (ASR_PATH / "model.bin").is_file():
            raise RuntimeError("转写模型尚未下载，请运行 scripts/download_models.py --asr。也可手动填写参考原文。")
        # CPU int8 keeps GPU memory available for synthesis.
        model = WhisperModel(str(ASR_PATH), device="cpu", compute_type="int8",
                             cpu_threads=min(8, os.cpu_count() or 4))
        segments, info = model.transcribe(str(path), language="zh", beam_size=5,
                                          vad_filter=True, condition_on_previous_text=False)
        text = "".join(s.text for s in segments).strip()
        del model
        gc.collect()
        if not text:
            raise ValueError("没有识别到语音，请换一个片段或手动填写。")
        return {"text": text, "language": info.language,
                "notice": "自动转写可能有误，请试听并逐字校对。"}


engine = VoiceEngine()
