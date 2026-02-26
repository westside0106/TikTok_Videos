import logging
import subprocess
import re
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ClipCandidate:
    start: float
    end: float
    score: float
    reason: str


class NoHighlightsError(Exception):
    def __init__(self, message: str = "No highlights detected."):
        self.user_message = "Could not detect any highlights. Try a longer video or different content."
        super().__init__(message)


def detect_scene_changes(video_path, threshold: float = 0.4) -> list:
    """
    Use FFmpeg scene detection filter to find scene change timestamps.
    Samples at 1fps to keep it fast even for long videos.
    Returns list of timestamps in seconds.
    """
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-r", "1",
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-f", "null", "-",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        # Parse pts_time from stderr (showinfo outputs there)
        timestamps = []
        for line in result.stderr.splitlines():
            m = re.search(r"pts_time:([\d.]+)", line)
            if m:
                timestamps.append(float(m.group(1)))
        logger.info("Found %d scene changes", len(timestamps))
        return timestamps
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("Scene detection failed: %s", e)
        return []


def compute_audio_energy(audio_path, window_ms: int = 500, hop_ms: int = 100):
    """
    Compute RMS energy curve from audio file.
    Returns (times_seconds, rms_values) as numpy arrays.
    """
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(str(audio_path))
        audio = audio.set_channels(1)  # mono
        samples = np.array(audio.get_array_of_samples(), dtype=np.float32)
        # Normalize to [-1, 1]
        max_val = float(2 ** (audio.sample_width * 8 - 1))
        samples = samples / max_val

        sr = audio.frame_rate
        window = int(sr * window_ms / 1000)
        hop = int(sr * hop_ms / 1000)

        times = []
        rms_values = []
        for i in range(0, len(samples) - window, hop):
            chunk = samples[i:i + window]
            rms = float(np.sqrt(np.mean(chunk ** 2)))
            times.append(i / sr)
            rms_values.append(rms)

        return np.array(times), np.array(rms_values)

    except Exception as e:
        logger.warning("Audio energy computation failed: %s", e)
        return np.array([]), np.array([])


def find_energy_peaks(times: np.ndarray, rms: np.ndarray, min_gap_s: float = 20.0) -> list:
    """
    Find timestamps where audio energy significantly exceeds the median.
    Enforces a minimum gap between returned peaks.
    """
    if len(rms) == 0:
        return []

    median_rms = float(np.median(rms))
    if median_rms == 0:
        return []

    threshold = median_rms * 1.8
    peak_times = []

    for i, (t, r) in enumerate(zip(times, rms)):
        if r > threshold:
            if not peak_times or (t - peak_times[-1]) >= min_gap_s:
                peak_times.append(float(t))

    logger.info("Found %d audio energy peaks", len(peak_times))
    return peak_times


def score_transcript_keywords(words: list, keywords: list) -> list:
    """
    Find timestamp windows where TikTok keywords appear.
    Returns list of (start, end, density_score) tuples.
    """
    if not words:
        return []

    keyword_set = {k.lower().strip() for k in keywords}
    hits = []

    for i, word in enumerate(words):
        if word.word.lower().strip(".,!?;:\"'") in keyword_set:
            # Expand to a window of ~10 words around the keyword
            ctx_start = max(0, i - 5)
            ctx_end = min(len(words) - 1, i + 10)
            window_words = words[ctx_start:ctx_end]
            if window_words:
                kw_count = sum(
                    1 for w in window_words
                    if w.word.lower().strip(".,!?;:\"'") in keyword_set
                )
                density = kw_count / len(window_words)
                hits.append((window_words[0].start, window_words[-1].end, density))

    return hits


def find_highlights(
    audio_path,
    video_path,
    words: list,
    chapters: list,
    config,
) -> list:
    """
    Main highlight detection entry point.
    Returns a list of ClipCandidate sorted by score descending.
    """
    min_dur = config.clip_min_duration
    max_dur = config.clip_max_duration
    max_clips = config.max_clips_per_video

    # Fast path: use chapters if available and valid
    if chapters:
        chapter_clips = []
        for ch in chapters:
            dur = ch["end_time"] - ch["start_time"]
            if min_dur <= dur <= max_dur:
                chapter_clips.append(ClipCandidate(
                    start=ch["start_time"],
                    end=ch["end_time"],
                    score=1.0,
                    reason=f"Chapter: {ch['title'][:40]}",
                ))
        if len(chapter_clips) >= max_clips:
            logger.info("Using %d chapter-based clips", len(chapter_clips))
            return chapter_clips[:max_clips]

    # Gather signals
    times, rms = compute_audio_energy(audio_path)
    energy_peaks = find_energy_peaks(times, rms, min_gap_s=max_dur * 0.5)
    scene_changes = detect_scene_changes(video_path)
    keyword_regions = score_transcript_keywords(words, config.tiktok_keywords)

    # Determine video duration
    video_duration = words[-1].end if words else 120.0

    # Score sliding windows
    candidates = _score_windows(
        duration=video_duration,
        energy_peaks=energy_peaks,
        keyword_regions=keyword_regions,
        scene_changes=scene_changes,
        times=times,
        rms=rms,
        min_dur=min_dur,
        max_dur=max_dur,
        config=config,
    )

    if not candidates:
        raise NoHighlightsError()

    # Apply non-maximum suppression and boundary refinement
    selected = _select_top_clips(candidates, max_clips, min_dur, max_dur)
    selected = [_refine_boundaries(c, words, min_dur, max_dur) for c in selected]

    logger.info("Selected %d highlight clips", len(selected))
    return selected


def _score_windows(
    duration: float,
    energy_peaks: list,
    keyword_regions: list,
    scene_changes: list,
    times: np.ndarray,
    rms: np.ndarray,
    min_dur: float,
    max_dur: float,
    config,
) -> list:
    """Score all possible clip windows using the three signals."""
    candidates = []
    step = 5.0  # step size in seconds for window sliding

    # Precompute global stats for normalization
    global_max_rms = float(np.max(rms)) if len(rms) > 0 else 1.0
    global_min_rms = float(np.min(rms)) if len(rms) > 0 else 0.0
    rms_range = global_max_rms - global_min_rms or 1.0

    for window_size in [min_dur, (min_dur + max_dur) // 2, max_dur]:
        pos = 0.0
        while pos + window_size <= duration:
            end = pos + window_size

            # Signal 1: Audio energy
            if len(times) > 0:
                mask = (times >= pos) & (times < end)
                window_rms = rms[mask]
                energy_score = float(np.mean((window_rms - global_min_rms) / rms_range)) if len(window_rms) > 0 else 0.0
            else:
                energy_score = 0.0

            # Signal 2: Keyword density
            kw_score = 0.0
            for ks, ke, kd in keyword_regions:
                if ks >= pos and ke <= end:
                    kw_score = max(kw_score, kd)
            kw_score = min(1.0, kw_score * 3)

            # Signal 3: Scene changes
            scenes_in_window = [t for t in scene_changes if pos <= t < end]
            scene_score = min(1.0, len(scenes_in_window) / 2)

            combined = (
                config.audio_energy_weight * energy_score
                + config.keyword_weight * kw_score
                + config.scene_change_weight * scene_score
            )

            reason_parts = []
            if energy_score > 0.6:
                reason_parts.append("high energy")
            if kw_score > 0.3:
                reason_parts.append("keyword")
            if scene_score > 0.5:
                reason_parts.append("scene change")
            reason = ", ".join(reason_parts) if reason_parts else "multi-signal"

            candidates.append(ClipCandidate(
                start=pos,
                end=end,
                score=combined,
                reason=reason,
            ))

            pos += step

    return candidates


def _select_top_clips(candidates: list, max_clips: int, min_dur: float, max_dur: float) -> list:
    """
    Non-maximum suppression: select top-scoring non-overlapping clips.
    """
    valid = [c for c in candidates if min_dur <= (c.end - c.start) <= max_dur]
    valid.sort(key=lambda c: c.score, reverse=True)

    selected = []
    for candidate in valid:
        overlaps = False
        for sel in selected:
            overlap_start = max(candidate.start, sel.start)
            overlap_end = min(candidate.end, sel.end)
            if overlap_end > overlap_start:
                overlap_dur = overlap_end - overlap_start
                candidate_dur = candidate.end - candidate.start
                if overlap_dur > 0.5 * candidate_dur:
                    overlaps = True
                    break
        if not overlaps:
            selected.append(candidate)
        if len(selected) >= max_clips:
            break

    return selected


def _refine_boundaries(clip: ClipCandidate, words: list, min_dur: float, max_dur: float) -> ClipCandidate:
    """
    Snap clip boundaries to nearest sentence/word boundaries in the transcript.
    """
    if not words:
        return clip

    # Find words near the clip start - snap to nearest word boundary (±2s)
    start = clip.start
    end = clip.end

    # Find the closest word start near clip.start
    best_start_diff = float("inf")
    for word in words:
        diff = abs(word.start - start)
        if diff < best_start_diff and diff <= 2.0:
            best_start_diff = diff
            start = word.start

    # Find the closest word end near clip.end (prefer end of sentence)
    best_end_diff = float("inf")
    for word in words:
        diff = abs(word.end - end)
        if diff < best_end_diff and diff <= 2.0:
            best_end_diff = diff
            end = word.end

    # Enforce duration bounds
    dur = end - start
    if dur < min_dur:
        end = start + min_dur
    elif dur > max_dur:
        end = start + max_dur

    return ClipCandidate(start=start, end=end, score=clip.score, reason=clip.reason)
