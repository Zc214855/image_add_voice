"""将自动语音识别时间戳可靠地映射回用户提供的原始故事文本。"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

from opencc import OpenCC


SPOKEN_RE = re.compile(r"[\u3400-\u9fffA-Za-z0-9]")
TITLE_RE = re.compile(r"^\s*《[^》]+》\s*")
ALIGNMENT_VERSION = 3
T2S = OpenCC("t2s")


@dataclass
class TimedChar:
    char: str
    start: float
    end: float


@dataclass
class Caption:
    text: str
    chars: list[TimedChar]
    start: float
    end: float


def clean_story_text(text: str) -> str:
    """移除标题与多余空白，保留朗读所需的正文和标点。"""
    text = text.replace("\ufeff", "").replace("\r\n", "\n")
    text = TITLE_RE.sub("", text, count=1)
    return re.sub(r"\s+", "", text).strip()


def match_char(char: str) -> str:
    """繁简统一后再比较，避免 Whisper 繁体输出降低对齐质量。"""
    converted = T2S.convert(char).lower()
    return converted[0] if converted else char.lower()


def spoken_chars(text: str) -> tuple[str, list[int]]:
    """返回可朗读字符序列及其在原文中的索引。"""
    chars: list[str] = []
    indices: list[int] = []
    for index, char in enumerate(text):
        if SPOKEN_RE.fullmatch(char):
            chars.append(match_char(char))
            indices.append(index)
    return "".join(chars), indices


def expand_words(words: Iterable[dict]) -> list[TimedChar]:
    """将 Whisper 的词级时间戳均匀拆成字符级时间戳。"""
    result: list[TimedChar] = []
    for word in words:
        raw = str(word.get("word") or word.get("text") or "").strip()
        chars = [char for char in raw if SPOKEN_RE.fullmatch(char)]
        if not chars:
            continue
        start = float(word["start"])
        end = max(float(word["end"]), start + 0.04)
        step = (end - start) / len(chars)
        for index, char in enumerate(chars):
            result.append(
                TimedChar(
                    char=match_char(char),
                    start=start + step * index,
                    end=start + step * (index + 1),
                )
            )
    return result


def align_original_text(
    original: str,
    recognized_words: list[dict],
    audio_duration: float,
) -> tuple[list[TimedChar], float]:
    """用序列匹配将识别时间映射到原文，缺失字符使用邻近时间线性插值。"""
    clean = clean_story_text(original)
    target, target_indices = spoken_chars(clean)
    recognized = expand_words(recognized_words)
    source = "".join(item.char for item in recognized)
    if not source:
        raise RuntimeError("转写结果没有可用文字，无法生成同步字幕。")

    matcher = SequenceMatcher(None, target, source, autojunk=False)
    timed_by_spoken_index: dict[int, TimedChar] = {}
    matched = 0
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            target_index = block.a + offset
            source_index = block.b + offset
            source_char = recognized[source_index]
            timed_by_spoken_index[target_index] = TimedChar(
                target[target_index],
                source_char.start,
                source_char.end,
            )
            matched += 1

    ratio = matched / max(len(target), 1)
    if ratio < 0.45:
        raise RuntimeError(
            f"原文与旁白匹配率仅 {ratio:.1%}，请确认文本和音频属于同一个故事。"
        )

    known = sorted(timed_by_spoken_index)
    for index in range(len(target)):
        if index in timed_by_spoken_index:
            continue
        left = next((value for value in reversed(known) if value < index), None)
        right = next((value for value in known if value > index), None)
        if left is not None and right is not None:
            left_time = timed_by_spoken_index[left].end
            right_time = timed_by_spoken_index[right].start
            fraction = (index - left) / (right - left)
            center = left_time + (right_time - left_time) * fraction
        elif left is not None:
            center = timed_by_spoken_index[left].end + 0.18 * (index - left)
        elif right is not None:
            center = max(0.0, timed_by_spoken_index[right].start - 0.18 * (right - index))
        else:
            center = audio_duration * index / max(len(target), 1)
        timed_by_spoken_index[index] = TimedChar(
            target[index],
            max(0.0, center - 0.08),
            min(audio_duration, center + 0.08),
        )

    # 将朗读字符时间写回完整原文；标点沿用前一个字符的结束时间。
    timed_text: list[TimedChar] = []
    spoken_position_by_text = {
        text_index: spoken_index
        for spoken_index, text_index in enumerate(target_indices)
    }
    last_end = 0.0
    for text_index, char in enumerate(clean):
        spoken_index = spoken_position_by_text.get(text_index)
        if spoken_index is None:
            timed_text.append(TimedChar(char, last_end, last_end))
            continue
        item = timed_by_spoken_index[spoken_index]
        start = max(last_end - 0.04, item.start)
        end = max(start + 0.04, item.end)
        timed_text.append(TimedChar(char, start, min(end, audio_duration)))
        last_end = timed_text[-1].end
    return timed_text, ratio


def _split_caption_text(text: str, max_chars: int) -> list[str]:
    """优先按标点切句，再把过长片段切成适合手机阅读的短句。"""
    # 结束引号属于前一句，不能让“。”后的 ” 孤立到下一条字幕开头。
    clauses = re.findall(r".+?[，。！？；：、](?:[”’」』》])?|.+$", text)
    result: list[str] = []
    buffer = ""
    for clause in clauses:
        if len(buffer) + len(clause) <= max_chars:
            buffer += clause
            continue
        if buffer:
            result.append(buffer)
            buffer = ""
        if len(clause) > max_chars:
            # 均衡切分，避免把长句切成“汤，”这类孤立短残片。
            part_count = math.ceil(len(clause) / max_chars)
            part_length = math.ceil(len(clause) / part_count)
            while len(clause) > part_length:
                result.append(clause[:part_length])
                clause = clause[part_length:]
        buffer = clause
    if buffer:
        result.append(buffer)
    return result


def build_captions(
    timed_text: list[TimedChar],
    audio_duration: float,
    max_chars: int = 14,
) -> list[Caption]:
    """把完整时间文本组织成一次只显示一条的短字幕。"""
    text = "".join(item.char for item in timed_text)
    chunks = _split_caption_text(text, max_chars)
    captions: list[Caption] = []
    cursor = 0
    for chunk in chunks:
        chars = timed_text[cursor : cursor + len(chunk)]
        cursor += len(chunk)
        spoken = [item for item in chars if SPOKEN_RE.fullmatch(item.char)]
        if not spoken:
            continue
        start = max(0.0, spoken[0].start - 0.08)
        end = min(audio_duration, spoken[-1].end + 0.18)
        if captions:
            start = max(start, captions[-1].end)
        if end <= start:
            end = min(audio_duration, start + 0.35)
        captions.append(Caption(chunk, chars, start, end))
    return captions


def save_alignment(
    path: Path,
    captions: list[Caption],
    match_ratio: float,
) -> None:
    """保存可审查、可复用的字幕对齐结果。"""
    payload = {
        "version": ALIGNMENT_VERSION,
        "match_ratio": match_ratio,
        "captions": [
            {
                "text": caption.text,
                "start": caption.start,
                "end": caption.end,
                "chars": [asdict(item) for item in caption.chars],
            }
            for caption in captions
        ],
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_alignment(path: Path) -> tuple[list[Caption], float]:
    """读取已缓存的对齐结果。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != ALIGNMENT_VERSION:
        raise ValueError("字幕对齐缓存版本已过期。")
    captions = [
        Caption(
            text=item["text"],
            start=float(item["start"]),
            end=float(item["end"]),
            chars=[TimedChar(**char) for char in item["chars"]],
        )
        for item in payload["captions"]
    ]
    return captions, float(payload["match_ratio"])
