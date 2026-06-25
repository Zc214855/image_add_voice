# 儿童故事视频生成器

将同名故事文本、旁白和插图自动合成为适合抖音发布的 `1080x1920` 竖屏视频。

## 素材约定

```text
res/
  txt/故事名.txt
  voice/故事名.mp3
  image/故事名/scene_01.png
                 scene_02.png
                 ...
```

音频支持 FFmpeg 可读取的格式，插图支持 PNG/JPG/WebP。图片按文件名自然排序。

## 安装

```powershell
python -m pip install -r story_video_tool/requirements.txt
```

系统必须可直接执行 `ffmpeg` 和 `ffprobe`。

## 桌面界面

双击：

```text
story_video_tool/start_gui.bat
```

或在项目根目录执行：

```powershell
python story_video_tool/gui.py
```

界面支持：

- 自行选择任意位置的故事文本和旁白音频
- 批量选择插图或导入整个插图文件夹
- 调整插图播放顺序并查看缩略图
- 自定义输出文件位置
- 选择 Whisper 模型和视频编码器
- 生成快速预览或正式版视频
- 查看生成阶段和字幕匹配率

## 生成视频

在项目根目录执行：

```powershell
python story_video_tool/main.py "妈妈买绿豆"
```

默认输出：

```text
output/妈妈买绿豆.mp4
```

首次处理新故事时会下载 Whisper 模型并转写旁白。转写缓存位于
`story_video_tool/.cache/故事名/`，再次生成不会重复转写。

常用参数：

```powershell
python story_video_tool/main.py "妈妈买绿豆" --model small --encoder auto
python story_video_tool/main.py "妈妈买绿豆" --draft
python story_video_tool/main.py "妈妈买绿豆" --force-transcribe
```

- `--model`: Whisper 模型，默认 `small`
- `--encoder`: `auto`、`nvenc` 或 `x264`
- `--draft`: 生成 `540x960` 快速预览
- `--force-transcribe`: 忽略转写缓存

## 对齐机制

1. Whisper 生成中文逐词时间戳。
2. 工具将识别结果拆为字符时间点。
3. 统一繁简体后，使用序列匹配把时间点映射回原始故事文本。
4. 未直接匹配的标点或字符由相邻时间点插值。
5. ASS 字幕使用原文显示，并按字符时间逐字高亮。

因此识别文本中的偶发错字不会直接进入成片。

## 是否需要接入 AI

当前已经使用本地 AI，但不需要云端 API：

- `faster-whisper` 在本机识别旁白并生成逐词时间戳。
- 字幕显示内容来自导入的原始故事文本，不直接采用 AI 识别文字。
- FFmpeg 负责图片运动、转场、字幕烧录、音频处理和视频编码。
- 所有故事文本、音频和插图均在本机处理，不上传到第三方服务。

只有需要自动生成插图、自动配音、智能分镜或云端高精度转写时，
才需要额外接入对应的 AI 服务。
