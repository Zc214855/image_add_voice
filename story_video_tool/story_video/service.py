"""命令行和桌面界面共享的故事视频生成服务。"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Callable

from .alignment import (
    align_original_text,
    build_captions,
    load_alignment,
    save_alignment,
)
from .media import (
    StoryAssets,
    load_transcript,
    media_duration,
    render_video,
    require_tools,
    transcribe,
)
from .subtitles import write_ass


StatusCallback = Callable[[str], None]


def _file_hash(path: Path) -> str:
    """计算素材内容指纹，防止同名素材变化后错误复用缓存。"""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_manifest(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def _safe_cache_name(title: str) -> str:
    """生成 Windows 可用的缓存目录名，同时保留正常中文故事名。"""
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip(" .")
    if not safe:
        safe = "story"
    if safe != title:
        suffix = hashlib.sha1(title.encode("utf-8")).hexdigest()[:8]
        safe = f"{safe}_{suffix}"
    return safe


def generate_story_video(
    assets: StoryAssets,
    project_root: Path,
    output_path: Path,
    *,
    model: str = "small",
    encoder: str = "auto",
    draft: bool = False,
    force_transcribe: bool = False,
    on_status: StatusCallback | None = None,
) -> dict:
    """从任意导入路径生成故事视频，并返回生成报告。"""

    def status(message: str) -> None:
        print(message, flush=True)
        if on_status:
            on_status(message)

    require_tools()
    project_root = project_root.resolve()
    output_path = output_path.resolve()
    duration = media_duration(assets.audio_path)

    cache_dir = (
        project_root
        / "story_video_tool"
        / ".cache"
        / _safe_cache_name(assets.title)
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = cache_dir / "transcript.json"
    alignment_path = cache_dir / "alignment.json"
    ass_path = cache_dir / "subtitles.ass"
    manifest_path = cache_dir / "manifest.json"

    status("[检查] 计算文本和音频指纹")
    audio_hash = _file_hash(assets.audio_path)
    text_hash = _file_hash(assets.text_path)
    manifest = _read_manifest(manifest_path)
    transcript_valid = (
        not force_transcribe
        and transcript_path.is_file()
        and manifest.get("audio_hash") == audio_hash
        and manifest.get("model") == model
    )
    alignment_valid = (
        transcript_valid
        and alignment_path.is_file()
        and manifest.get("text_hash") == text_hash
    )

    if transcript_valid:
        status(f"[缓存] 使用转写: {transcript_path}")
        words = load_transcript(transcript_path)
    else:
        status("[转写] 正在识别旁白并提取逐词时间")
        words = transcribe(assets.audio_path, transcript_path, model)
        alignment_valid = False

    story_text = assets.text_path.read_text(encoding="utf-8-sig")
    if alignment_valid:
        try:
            captions, match_ratio = load_alignment(alignment_path)
            status(f"[缓存] 使用字幕对齐: {alignment_path}")
        except (ValueError, KeyError, TypeError):
            alignment_valid = False

    if not alignment_valid:
        status("[对齐] 正在将旁白时间映射到原始故事文本")
        timed_text, match_ratio = align_original_text(story_text, words, duration)
        captions = build_captions(timed_text, duration)
        save_alignment(alignment_path, captions, match_ratio)

    if not captions:
        raise RuntimeError("没有生成任何字幕。")

    width, height = (540, 960) if draft else (1080, 1920)
    write_ass(
        ass_path,
        assets.title,
        captions,
        width,
        height,
        duration,
    )
    status("[渲染] 正在合成插图、转场、字幕和旁白")
    render_video(
        assets,
        ass_path,
        output_path,
        captions,
        duration,
        encoder,
        draft,
    )

    report = {
        "story": assets.title,
        "duration_seconds": round(duration, 3),
        "image_count": len(assets.images),
        "caption_count": len(captions),
        "text_audio_match_ratio": round(match_ratio, 4),
        "output": str(output_path),
    }
    (cache_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    manifest_path.write_text(
        json.dumps(
            {
                "audio_hash": audio_hash,
                "text_hash": text_hash,
                "model": model,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    status(f"[完成] 视频已生成: {output_path}")
    return report
