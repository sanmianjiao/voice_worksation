# 声刻 · 本地 AI 配音工作台

用参考录音中的音色朗读新文案，输出可导入剪映、Premiere、DaVinci Resolve 的配音文件。本项目是**配音引擎与本地操作界面**，不包含数字人形象、视频生成或口型驱动。

## 从 GitHub 下载后的首次运行

GitHub 仓库只包含源码、测试和说明文档，**不包含模型权重、Python 虚拟环境、参考录音、个人音色、生成结果和日志**。本文后面提到的本机样例与现成环境，不会随 Git 克隆提供。

准备 Windows、Python 3.10、FFmpeg（含 ffprobe，加入 PATH）后：

```powershell
git clone https://github.com/sanmianjiao/voice_worksation.git
cd voice_worksation
powershell -ExecutionPolicy Bypass -File .\setup.ps1
# 可选：下载参考语音的中文自动转写模型
.\.venv\Scripts\python.exe scripts\download_models.py --asr
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

首次打开界面后，请导入你本人或已获授权的音频，截取参考片段，再输入文案生成配音。没有内置录音也可以正常启动。

## 本机独立目录说明

本项目已独立整理到 `E:\project\codex_project\voice_studio\`。本文中的「项目目录」指这个文件夹，不再指其父目录。其他任务请在父目录下建立各自的同级文件夹，不要共用这里的运行环境、模型和资料。

## 从这里开始

已生成的参考原声、完整克隆/快速模式样例、字幕和工程包集中在 `deliverables`。先看该目录的 `验收记录.md`，再试听对照。

1. 双击项目目录的 `启动配音工作台.bat`。
2. 启动后会自动打开浏览器 `http://127.0.0.1:7860`；也可手动打开。如果服务已运行，启动器会直接打开已有工作台。
3. 左侧选择已保存的参考音色，试听参考片段；右侧输入自己的文案。
4. 勾选音色授权与 AI 合成标识提醒，点击「生成 AI 配音」。
5. 生成后试听，下载 WAV、MP3、SRT 或 ZIP。也可以在「最近生成」打开此前结果。

原始素材 `E:\project\ffmpeg\output.mp3` **只读使用，未修改**。现在文件夹内已包含其字节一致的副本 `data/sources/output.mp3`，工作台默认读取此副本，不再依赖外部素材目录。参考片段保存在 `data/references`，音色资料保存在 `data/profiles`，配音与字幕保存在 `data/outputs`。音色特征在生成时提取，并在同一任务各句之间复用；没有训练专属权重，也没有永久保存模型内部的特征缓存。

## 两种音色克隆方式

| 模式 | 输入 | 使用建议 |
|---|---|---|
| 快速试音 | 3–25 秒参考语音 | 无需参考原文，用于初步试音；只使用说话人特征 |
| 完整克隆 | 参考语音 + 与录音逐字匹配的原文 | 先「自动识别」，试听并校对，再保存；可以利用更多参考信息 |

建议选择 8–15 秒、仅目标说话人、无音乐/混响/串音的完整句子。不要把 23 分钟录音全部作为参考。工具会检查片段长度、静音与部分失真情况，**不会自动鉴定身份、区分男女说话人、分离人声，或保证相似度**。效果须自行试听评估；改善参考素材往往比拉长参考音频更重要。

参考音频的内容仅作为素材，不会被当作系统操作指令。没有云端音频 API；运行时处理在本机完成。初次安装/下载模型需要联网。

## 输出与视频剪辑

- `voice.wav`：48kHz、24-bit PCM、单声道。原模型采样率经过重采样，不表示新增高频细节。
- `voice.mp3`：192kbps，带 AI-generated comment 元数据。
- `subtitles.srt`：按照每个实际合成片段的时长生成，包含调速后的时间和句间停顿。**片段级时间轴，不是逐字强制对齐**，片段内部可能有静音，剪辑时可再微调。
- `segment_001.wav` 等：独立片段，便于在时间线上替换单句。
- `script.txt`：原始文案。
- `manifest.json`：模型、参考片段、生成设置、随机种子、AI 合成说明、时间轴。
- `project.zip`：上述文件的完整工程包。

长文按标点拆成不超过 100 字的片段，分句推理以控制显存。语速通过 FFmpeg `atempo` 后处理（0.7–1.4 倍），不是模型情绪控制。当前 Base 模型界面不提供未经验证的“情绪强度”或“音色相似度百分比”。

## Python 程序结构

```text
studio/
  config.py       路径与运行设置
  audio.py        FFmpeg 处理、波形、文案拆分、SRT 时间轴
  engine.py       Qwen3-TTS 加载、显存释放、Whisper 转写
  server.py       本地 API、音色资料、单任务推理队列、导出
scripts/
  download_models.py  下载公开 TTS / ASR 权重
  download_torch.py   官方 PyTorch 大文件分段下载备用工具（SHA256 校验）
  smoke_test.py       使用真实 GPU 模型的端到端测试
  repair_environment.py  同机移动文件夹后修复已有环境，不重新下载依赖
  sleep_pc.py         仅显式运行时才使 Windows 睡眠
web/
  index.html / style.css / app.js   无构建依赖的中文界面
tests/
  test_studio.py   音频、输入校验、接口与安全边界测试
setup.ps1         创建隔离 Python 环境并安装依赖
start.ps1         绑定 127.0.0.1 的启动入口
run.py            检测已有服务并自动打开浏览器
```

## 首次安装 / 迁移电脑

需要 Windows、Python 3.10、FFmpeg（含 ffprobe）在 PATH 中。NVIDIA GPU 推荐；CPU 可以运行但会显著更慢。运行环境装在项目 `.venv`，模型下载在项目 `models`，不会覆盖系统 Python。

这次整理已包含本机的完整环境、模型和数据；**本机直接双击启动即可，无需重新安装**。它不是免安装的独立 EXE：系统 Python 3.10、FFmpeg 和显卡驱动仍使用本机已安装的程序。换电脑时请按下面步骤准备对应环境。

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
# 可选：安装中文参考录音自动转写模型
.\.venv\Scripts\python.exe scripts\download_models.py --asr
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

若 Hugging Face 下载不通，TTS 权重可从模型作者列出的 ModelScope 源下载：

```powershell
.\.venv\Scripts\python.exe scripts\download_models.py --provider modelscope
```

若官方 PyTorch 单请求下载长时间无进展，可用备用下载器，再安装校验后的 wheel：

```powershell
.\.venv\Scripts\python.exe scripts\download_torch.py
.\.venv\Scripts\python.exe -m pip install ".downloads\torch-2.8.0+cu128-cp310-cp310-win_amd64.whl"
.\.venv\Scripts\python.exe -m pip install torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

安装版固定 `qwen-tts==0.1.1`、`torch==2.8.0` / `torchaudio==2.8.0` CUDA 12.8。底层使用 SDPA，不要求在 Windows 编译 FlashAttention。模型冷加载或首次语音特征提取可能较慢。

`requirements.lock.txt` 保存本机通过验证的完整依赖版本，`setup.ps1` 优先按此安装。`requirements.txt` 是较短的直接依赖清单。Gradio 虽然不是本工作台的界面框架，但属于 Qwen 包的依赖，固定在与其 Transformers / Hugging Face Hub 兼容的 5.50.0 版本。

如果 PyPI 下载很慢，可仅对本次安装指定清华镜像，不修改全局 pip 配置：

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -PackageIndex https://pypi.tuna.tsinghua.edu.cn/simple
```

高级可选环境变量（在启动前设置）：`VOICE_SAMPLE_PATH` 覆盖示例素材路径；`VOICE_MODEL_PATH` 指向兼容的 Qwen3-TTS Base 本地模型；`VOICE_DEVICE=cpu` 强制 CPU；`VOICE_DATA_DIR` 指定数据目录。

### 以后在同一台电脑移动整个文件夹

先停止正在运行的配音服务，再整体移动 `voice_studio` 文件夹，不要只移动源码。到新位置打开 PowerShell，用系统 Python 3.10 修复 `.venv` 的激活脚本与命令入口：

```powershell
py -3.10 scripts\repair_environment.py --previous-root "移动前的配音工作台完整路径"
```

此工具保留已安装的库、模型和所有音频，不下载依赖、不清空环境。修复记录写入 `logs/environment_relocation.json`。本次迁移已经执行过，无需重复。历史 `manifest.json` 中的绝对模型路径记录的是当时生成环境，作为原始记录保留；当前模型与数据路径按新的项目目录计算。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
# 真实模型测试；生成明确标识为 AI 合成的测试句，不是本人原话
.\.venv\Scripts\python.exe scripts\smoke_test.py
```

普通测试使用隔离临时目录，不更改已有音色和配音。真实模型测试会在 `data` 中保留测试片段和生成结果。界面任务串行执行，最多接受 4 个运行/等待任务；取消会在当前处理步骤结束后生效，不会强杀模型。重启后被打断的任务标记失败，可手动重试。没有自动重启、后台定时任务或持续监控。

## 常见问题

- **显存不足**：先关闭游戏等占用显存的程序，然后点击「释放模型显存」再重试；该按钮不会关闭其他程序。
- **声音不像 / 有杂音**：先换一个清晰的单人片段；完整模式需要准确参考原文。此版没有背景音乐分离。
- **听到漏字 / 多字 / 重复**：缩短文案句子，检查参考原文，换参考片段；对生成结果人工验收。本项目不能承诺语音与文字百分之百一致。
- **自动转写不准确**：转写结果只是草稿，必须试听校对，不会直接覆盖已保存的原文。
- **端口被占用**：检查已有工作台是否已启动，或用 `start.ps1 -Port 7861`。
- **电脑睡眠后**：唤醒后通常可以继续访问尚未关闭的服务；如果进程已停止，重新双击启动入口。
- **打开页面提示会话失效**：刷新页面重新获取本地会话 token。
- **控制台提示未安装 SoX / FlashAttention**：当前已验证的克隆链路使用 FFmpeg 和 PyTorch SDPA，不依赖这两个可选组件。日志里的提示来自上游包；不影响已验证的本地推理。

## 素材与使用边界

仅用于本人或已获授权的音色。用户提供音频不等于授权已经核实；项目记录 `user_provided_not_verified`，不会伪造本人同意。输出是 AI 合成语音，不是说话者真实发表的言论。发布时应按适用平台要求做好合成内容说明，不能用于冒充本人、虚假背书或欺骗。

服务只绑定本机回环地址，有 Host 校验和写操作会话 token。不应直接暴露到公网，也不是有账号鉴权的多人服务。音频、原文、任务记录都以普通文件保存在本机，请自行管理隐私和备份。MP3 元数据/工程说明不是不可移除的水印，WAV 不保证携带合成标记。

## 模型与实现依据

- Qwen3-TTS 官方仓库：`https://github.com/QwenLM/Qwen3-TTS`
- 模型卡：`https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base`
- faster-whisper：`https://github.com/SYSTRAN/faster-whisper`
- Whisper small 权重：`https://huggingface.co/Systran/faster-whisper-small`

模型及第三方依赖遵守其各自许可证；公开权重许可不替代个人音色或源素材的使用许可。
