"""素材发现、媒体探测、转写与 FFmpeg 渲染。"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .alignment import Caption


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
AUDIO_EXTENSIONS = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")


@dataclass
class StoryAssets:
    title: str
    text_path: Path
    audio_path: Path
    images: list[Path]


def natural_key(path: Path) -> list[object]:
    """让 scene_2 排在 scene_10 之前。"""
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", path.name)
    ]


def discover_assets(project_root: Path, title: str) -> StoryAssets:
    """按约定目录自动发现同名文本、音频与插图。"""
    text_path = project_root / "res" / "txt" / f"{title}.txt"
    image_dir = project_root / "res" / "image" / title
    audio_path = next(
        (
            project_root / "res" / "voice" / f"{title}{extension}"
            for extension in AUDIO_EXTENSIONS
            if (project_root / "res" / "voice" / f"{title}{extension}").is_file()
        ),
        None,
    )
    missing: list[str] = []
    if not text_path.is_file():
        missing.append(str(text_path))
    if audio_path is None:
        missing.append(str(project_root / "res" / "voice" / f"{title}.*"))
    if not image_dir.is_dir():
        missing.append(str(image_dir))
    if missing:
        raise FileNotFoundError("缺少故事素材:\n" + "\n".join(missing))

    images = sorted(
        (
            path
            for path in image_dir.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ),
        key=natural_key,
    )
    if not images:
        raise FileNotFoundError(f"插图目录为空: {image_dir}")
    return StoryAssets(title, text_path, audio_path, images)


def run(command: list[str], cwd: Path | None = None) -> None:
    """显示并执行外部命令，失败时直接保留完整错误信息。"""
    printable = subprocess.list2cmdline(command)
    print(f"[执行] {printable}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def media_duration(path: Path) -> float:
    """通过 ffprobe 获取音频时长。"""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return float(result.stdout.strip())


def transcribe(
    audio_path: Path,
    output_path: Path,
    model_name: str,
) -> list[dict]:
    """使用中文 Whisper 逐词时间戳转写旁白，并保存原始结果供审查。"""
    from faster_whisper import WhisperModel

    print(f"[转写] 加载 Whisper 模型: {model_name}", flush=True)
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, info = model.transcribe(
        str(audio_path),
        language="zh",
        beam_size=5,
        best_of=5,
        vad_filter=True,
        word_timestamps=True,
        condition_on_previous_text=True,
    )
    words: list[dict] = []
    segment_payload: list[dict] = []
    for segment in segments:
        segment_words = []
        for word in segment.words or []:
            item = {
                "word": word.word,
                "start": round(float(word.start), 3),
                "end": round(float(word.end), 3),
                "probability": round(float(word.probability), 4),
            }
            words.append(item)
            segment_words.append(item)
        segment_payload.append(
            {
                "start": round(float(segment.start), 3),
                "end": round(float(segment.end), 3),
                "text": segment.text.strip(),
                "words": segment_words,
            }
        )
        print(
            f"[转写] {segment.start:7.2f}-{segment.end:7.2f} {segment.text.strip()}",
            flush=True,
        )
    payload = {
        "language": info.language,
        "language_probability": info.language_probability,
        "duration": info.duration,
        "words": words,
        "segments": segment_payload,
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return words


def load_transcript(path: Path) -> list[dict]:
    """读取缓存的 Whisper 逐词转写。"""
    return json.loads(path.read_text(encoding="utf-8"))["words"]


def scene_boundaries(
    captions: list[Caption],
    image_count: int,
    audio_duration: float,
) -> list[float]:
    """按故事文本进度分配插图，使画面顺序与旁白叙事同步。"""
    if image_count == 1:
        return [0.0, audio_duration]
    total_chars = sum(len(caption.text) for caption in captions)
    cumulative = 0
    caption_points: list[tuple[int, float]] = [(0, 0.0)]
    for caption in captions:
        cumulative += len(caption.text)
        caption_points.append((cumulative, caption.end))

    boundaries = [0.0]
    for image_index in range(1, image_count):
        target = total_chars * image_index / image_count
        before = caption_points[0]
        after = caption_points[-1]
        for point in caption_points:
            if point[0] <= target:
                before = point
            if point[0] >= target:
                after = point
                break
        if after[0] == before[0]:
            time_value = before[1]
        else:
            fraction = (target - before[0]) / (after[0] - before[0])
            time_value = before[1] + (after[1] - before[1]) * fraction
        boundaries.append(max(boundaries[-1] + 1.0, time_value))
    boundaries.append(audio_duration)
    return boundaries


def _ffmpeg_escape(path: Path) -> str:
    """转义 FFmpeg filter 参数中的 Windows 绝对路径。"""
    return str(path.resolve()).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def detect_encoder(preference: str) -> tuple[str, list[str]]:
    """验证 NVENC 是否实际可用；失败时稳定回退到 libx264。"""
    if preference == "x264":
        return "libx264", ["-preset", "medium", "-crf", "18"]
    if preference in {"auto", "nvenc"}:
        probe = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=size=64x64:rate=1",
                "-frames:v",
                "1",
                "-c:v",
                "h264_nvenc",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
        )
        if probe.returncode == 0:
            return "h264_nvenc", [
                "-preset",
                "p6",
                "-tune",
                "hq",
                "-rc",
                "vbr",
                "-cq",
                "18",
                "-b:v",
                "8M",
                "-maxrate",
                "14M",
                "-bufsize",
                "20M",
            ]
        if preference == "nvenc":
            raise RuntimeError(
                "指定了 NVENC，但当前显卡驱动无法完成 H.264 编码。\n"
                + probe.stderr.decode(errors="replace")
            )
    return "libx264", ["-preset", "medium", "-crf", "18"]


def render_video(
    assets: StoryAssets,
    ass_path: Path,
    output_path: Path,
    captions: list[Caption],
    audio_duration: float,
    encoder_preference: str,
    draft: bool,
) -> None:
    """用 FFmpeg 生成带轻微镜头运动、叠化转场和同步字幕的成片。"""
    width, height = (540, 960) if draft else (1080, 1920)
    fps = 24 if draft else 30
    transition = 0.65
    boundaries = scene_boundaries(captions, len(assets.images), audio_duration)
    encoder, encoder_args = detect_encoder(encoder_preference)
    print(f"[编码] 使用 {encoder}", flush=True)

    command = ["ffmpeg", "-hide_banner", "-y"]
    durations: list[float] = []
    for index, image in enumerate(assets.images):
        scene_length = boundaries[index + 1] - boundaries[index]
        input_duration = scene_length + (transition if index < len(assets.images) - 1 else 0)
        durations.append(input_duration)
        command.extend(["-loop", "1", "-t", f"{input_duration:.3f}", "-i", str(image)])
    audio_index = len(assets.images)
    command.extend(["-i", str(assets.audio_path)])

    filters: list[str] = []
    for index, duration in enumerate(durations):
        frames = max(2, math.ceil(duration * fps))
        mode = index % 4
        if mode == 0:
            zoom = f"1.00+0.065*on/{frames - 1}"
            x_expr = "iw/2-(iw/zoom/2)"
        elif mode == 1:
            zoom = f"1.065-0.045*on/{frames - 1}"
            x_expr = "iw/2-(iw/zoom/2)"
        elif mode == 2:
            zoom = "1.045"
            x_expr = f"(iw-iw/zoom)*on/{frames - 1}"
        else:
            zoom = "1.045"
            x_expr = f"(iw-iw/zoom)*(1-on/{frames - 1})"
        filters.append(
            f"[{index}:v]"
            f"zoompan=z='{zoom}':x='{x_expr}':"
            f"y='ih/2-(ih/zoom/2)':d={frames}:s={width}x{height}:fps={fps},"
            "setsar=1,format=yuv420p"
            f"[v{index}]"
        )

    current = "v0"
    elapsed = durations[0] - transition
    for index in range(1, len(assets.images)):
        output_label = f"x{index}"
        transition_name = "fade" if index % 5 else "smoothleft"
        filters.append(
            f"[{current}][v{index}]"
            f"xfade=transition={transition_name}:duration={transition}:"
            f"offset={elapsed:.3f}[{output_label}]"
        )
        current = output_label
        elapsed += durations[index] - transition

    subtitle_filter = (
        f"subtitles=filename='{_ffmpeg_escape(ass_path)}':"
        f"fontsdir='C\\:/Windows/Fonts'"
    )
    filters.append(
        f"[{current}]{subtitle_filter},"
        "eq=saturation=1.03:contrast=1.015,"
        "format=yuv420p[vout]"
    )
    filters.append(
        f"[{audio_index}:a]"
        "highpass=f=65,lowpass=f=13500,"
        "loudnorm=I=-16:TP=-1.5:LRA=11[aout]"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            encoder,
            *encoder_args,
            "-r",
            str(fps),
            "-g",
            str(fps * 2),
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-movflags",
            "+faststart",
            "-shortest",
            str(output_path),
        ]
    )
    run(command)


def require_tools() -> None:
    """在耗时处理前验证外部依赖。"""
    missing = [name for name in ("ffmpeg", "ffprobe") if shutil.which(name) is None]
    if missing:
        raise RuntimeError("缺少系统命令: " + ", ".join(missing))

