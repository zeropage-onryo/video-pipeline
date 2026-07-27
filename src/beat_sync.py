MAX_SNAP_SECONDS = 0.4
SYNTHETIC_BEAT_GRID_DURATION = 20.0  # comfortably covers any 13-17s edit


def detect_beats(music_path: str) -> list[float]:
    import librosa

    y, sr = librosa.load(music_path, sr=None)
    _tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    return librosa.frames_to_time(beat_frames, sr=sr).tolist()


def synthetic_beats(bpm: float, offset: float = 0.0, duration: float = SYNTHETIC_BEAT_GRID_DURATION) -> list[float]:
    """Generates an evenly-spaced beat grid from a known tempo, for when you
    know a track's BPM (e.g. a platform-native sound you can't download) but
    don't have the audio file itself to analyze."""
    interval = 60.0 / bpm
    beats = []
    t = offset
    while t <= duration:
        beats.append(round(t, 3))
        t += interval
    return beats


def nearest_beat(t: float, beat_times: list[float], max_snap: float = MAX_SNAP_SECONDS):
    if not beat_times:
        return None
    closest = min(beat_times, key=lambda b: abs(b - t))
    return closest if abs(closest - t) <= max_snap else None


def snap_edit_to_beats(edit: dict, beat_times: list[float], manifest_by_name: dict, cut_field) -> list[str]:
    """Snaps the transition points between cuts to the nearest detected beat,
    keeping the first cut's start and the last cut's end fixed. Mutates
    edit['edit_list'] in place with adjusted out points."""
    warnings = []
    edit_list = edit.get("edit_list", [])
    if len(edit_list) < 2 or not beat_times:
        return warnings

    durations = []
    for cut in edit_list:
        in_point = cut_field(cut, "in", "in_point", "start")
        out_point = cut_field(cut, "out", "out_point", "end")
        if in_point is None or out_point is None:
            return warnings  # let validate_edit report the missing fields
        durations.append(out_point - in_point)

    boundaries = [0.0]
    for d in durations:
        boundaries.append(boundaries[-1] + d)

    for i in range(1, len(boundaries) - 1):
        snapped = nearest_beat(boundaries[i], beat_times)
        if snapped is not None:
            boundaries[i] = snapped
        else:
            warnings.append(
                f"cut {i} transition at {boundaries[i]:.2f}s had no beat within "
                f"{MAX_SNAP_SECONDS}s, left un-synced"
            )

    for i in range(1, len(boundaries)):
        if boundaries[i] <= boundaries[i - 1]:
            warnings.append("beat snapping produced out-of-order cut boundaries; skipped for this edit")
            return warnings

    for i, cut in enumerate(edit_list):
        filename = cut_field(cut, "clip", "filename", "file")
        in_point = cut_field(cut, "in", "in_point", "start")
        new_duration = boundaries[i + 1] - boundaries[i]
        new_out = in_point + new_duration

        real_duration = (manifest_by_name.get(filename) or {}).get("duration_seconds")
        if real_duration and new_out > real_duration:
            warnings.append(f"'{filename}' beat-synced duration exceeded clip length; clamped")
            new_out = real_duration

        cut["out"] = round(new_out, 2)
        for alt_key in ("out_point", "end"):
            if alt_key in cut:
                cut[alt_key] = cut["out"]

    return warnings
