#!/usr/bin/env python
"""Minimal MIDI -> ASM converter (NGPC T6W28).

Stage 1: MIDI parsing + basic event extraction.
Stage 2: Quantize + simple streams (mono by default).
Stage 3: Emit NGPC note table (T6W28 byte1/byte2 pairs).
"""

import sys
import argparse
import json
from bisect import bisect_right
from collections import defaultdict

import mido

NOTE_BASE_MIDI = 45  # A2
NOTE_MAX_INDEX = 50  # A2..B6 inclusive
REST_CODE = 0xFF
DEFAULT_GRID = 48
DEFAULT_MAX_CHANNELS = 3
DEFAULT_FPS = 60
DEFAULT_TEMPO_US = 500000  # 120 BPM

BGM_OP_SET_ATTN = 0xF0
BGM_OP_SET_ENV = 0xF1
BGM_OP_SET_VIB = 0xF2
BGM_OP_SET_SWEEP = 0xF3
BGM_OP_SET_INST = 0xF4

# Note table from 03_HOMEBREW/Columns/sound.asm (A2..B6)
NOTE_TABLE = [
    (0x08, 0x36), (0x07, 0x33), (0x09, 0x30), (0x0D, 0x2D),
    (0x04, 0x2B), (0x0D, 0x28), (0x09, 0x26), (0x06, 0x24),
    (0x05, 0x22), (0x06, 0x20), (0x09, 0x1E), (0x0E, 0x1C),
    (0x04, 0x1B), (0x0B, 0x19), (0x04, 0x18), (0x0E, 0x16),
    (0x09, 0x15), (0x06, 0x14), (0x04, 0x13), (0x03, 0x12),
    (0x02, 0x11), (0x03, 0x10), (0x04, 0x0F), (0x07, 0x0E),
    (0x0A, 0x0D), (0x0D, 0x0C), (0x02, 0x0C), (0x07, 0x0B),
    (0x0D, 0x0A), (0x03, 0x0A), (0x0A, 0x09), (0x01, 0x09),
    (0x09, 0x08), (0x01, 0x08), (0x0A, 0x07), (0x03, 0x07),
    (0x0D, 0x06), (0x06, 0x06), (0x01, 0x06), (0x0B, 0x05),
    (0x06, 0x05), (0x01, 0x05), (0x0D, 0x04), (0x08, 0x04),
    (0x04, 0x04), (0x00, 0x04), (0x0D, 0x03), (0x09, 0x03),
    (0x06, 0x03), (0x03, 0x03), (0x00, 0x03),
]


def _extract_note_events(
    mid: mido.MidiFile,
    use_cc_volume: bool,
    use_sustain: bool,
) -> tuple[
    list[dict],
    dict,
    dict[int, list[tuple[int, int]]],
    dict[int, list[tuple[int, int, int]]],
    dict[int, list[tuple[int, int]]],
]:
    merged = mido.merge_tracks(mid.tracks)
    abs_tick = 0
    last_tick = 0

    # (channel, note) -> (start_tick, velocity)
    active: dict[tuple[int, int], tuple[int, int]] = {}
    active_by_channel = defaultdict(int)
    current_bend = defaultdict(int)
    current_volume = defaultdict(lambda: 127)
    current_expression = defaultdict(lambda: 127)
    cc_events_by_channel: dict[int, list[tuple[int, int, int]]] = defaultdict(list)
    sustain_on = defaultdict(bool)
    sustained: dict[tuple[int, int], tuple[int, int, int]] = {}
    bend_events_by_channel: dict[int, list[tuple[int, int]]] = defaultdict(list)
    program_events_by_channel: dict[int, list[tuple[int, int]]] = defaultdict(list)
    events: list[dict] = []
    bend_event_count = 0
    bend_during_note = 0
    cc_volume_events = 0
    cc_expression_events = 0
    cc_sustain_events = 0
    program_change_events = 0

    for msg in merged:
        abs_tick += msg.time
        last_tick = abs_tick

        if msg.type == "pitchwheel":
            channel = getattr(msg, "channel", 0)
            current_bend[channel] = int(msg.pitch)
            bend_events_by_channel[channel].append((abs_tick, int(msg.pitch)))
            bend_event_count += 1
            if active_by_channel[channel] > 0:
                bend_during_note += 1
            continue
        if msg.type == "program_change":
            channel = getattr(msg, "channel", 0)
            program = int(getattr(msg, "program", 0))
            program_events_by_channel[channel].append((abs_tick, program))
            program_change_events += 1
            continue
        if msg.type == "control_change":
            channel = getattr(msg, "channel", 0)
            if msg.control == 7:
                current_volume[channel] = int(msg.value)
                cc_volume_events += 1
                cc_events_by_channel[channel].append(
                    (abs_tick, current_volume[channel], current_expression[channel])
                )
            elif msg.control == 11:
                current_expression[channel] = int(msg.value)
                cc_expression_events += 1
                cc_events_by_channel[channel].append(
                    (abs_tick, current_volume[channel], current_expression[channel])
                )
            elif msg.control == 64 and use_sustain:
                cc_sustain_events += 1
                sustain_on[channel] = msg.value >= 64
                if not sustain_on[channel]:
                    release_keys = [k for k in sustained.keys() if k[0] == channel]
                    for key in release_keys:
                        start_tick, start_vel, start_bend = sustained.pop(key)
                        duration = max(0, abs_tick - start_tick)
                        events.append(
                            {
                                "start": start_tick,
                                "duration": duration,
                                "note": key[1],
                                "channel": channel,
                                "velocity": start_vel,
                                "bend": start_bend,
                            }
                        )
                        active_by_channel[channel] = max(0, active_by_channel[channel] - 1)
            continue

        if msg.type not in ("note_on", "note_off"):
            continue

        channel = getattr(msg, "channel", 0)
        note = msg.note
        velocity = getattr(msg, "velocity", 0)
        # Velocity scaling by CC is applied later (after potential splitting).

        is_note_on = msg.type == "note_on" and velocity > 0
        key = (channel, note)

        if is_note_on:
            # If a note is already active, close it first.
            if key in active:
                start_tick, start_vel, start_bend = active.pop(key)
                active_by_channel[channel] = max(0, active_by_channel[channel] - 1)
                duration = max(0, abs_tick - start_tick)
                events.append(
                    {
                        "start": start_tick,
                        "duration": duration,
                        "note": note,
                        "channel": channel,
                        "velocity": start_vel,
                        "bend": start_bend,
                    }
                )
            if key in sustained:
                start_tick, start_vel, start_bend = sustained.pop(key)
                active_by_channel[channel] = max(0, active_by_channel[channel] - 1)
                duration = max(0, abs_tick - start_tick)
                events.append(
                    {
                        "start": start_tick,
                        "duration": duration,
                        "note": note,
                        "channel": channel,
                        "velocity": start_vel,
                        "bend": start_bend,
                    }
                )
            active[key] = (abs_tick, velocity, current_bend[channel])
            active_by_channel[channel] += 1
        else:
            if key in active:
                start_tick, start_vel, start_bend = active.pop(key)
                if use_sustain and sustain_on[channel]:
                    sustained[key] = (start_tick, start_vel, start_bend)
                else:
                    active_by_channel[channel] = max(0, active_by_channel[channel] - 1)
                    duration = max(0, abs_tick - start_tick)
                    events.append(
                        {
                            "start": start_tick,
                            "duration": duration,
                            "note": note,
                            "channel": channel,
                            "velocity": start_vel,
                            "bend": start_bend,
                        }
                    )

    # Close any hanging notes at end-of-track.
    for (channel, note), (start_tick, start_vel, start_bend) in active.items():
        duration = max(0, last_tick - start_tick)
        events.append(
            {
                "start": start_tick,
                "duration": duration,
                "note": note,
                "channel": channel,
                "velocity": start_vel,
                "bend": start_bend,
            }
        )
    for (channel, note), (start_tick, start_vel, start_bend) in sustained.items():
        duration = max(0, last_tick - start_tick)
        events.append(
            {
                "start": start_tick,
                "duration": duration,
                "note": note,
                "channel": channel,
                "velocity": start_vel,
                "bend": start_bend,
            }
        )

    events.sort(key=lambda e: (e["start"], e["channel"], e["note"]))

    stats = {
        "ticks_per_beat": mid.ticks_per_beat,
        "total_ticks": last_tick,
        "event_count": len(events),
        "pitch_bend_events": bend_event_count,
        "pitch_bend_during_note": bend_during_note,
        "cc_volume_events": cc_volume_events,
        "cc_expression_events": cc_expression_events,
        "cc_sustain_events": cc_sustain_events,
        "program_change_events": program_change_events,
    }

    return events, stats, bend_events_by_channel, cc_events_by_channel, program_events_by_channel


def _get_tempo_events(mid: mido.MidiFile) -> list[tuple[int, int]]:
    events: list[tuple[int, int]] = []
    for track in mid.tracks:
        tick = 0
        for msg in track:
            tick += msg.time
            if msg.type == "set_tempo":
                events.append((tick, int(msg.tempo)))
    events.sort(key=lambda x: x[0])
    if not events or events[0][0] != 0:
        events.insert(0, (0, DEFAULT_TEMPO_US))
    return events


def _build_tempo_segments(mid: mido.MidiFile) -> list[dict]:
    events = _get_tempo_events(mid)
    segments = []
    tpb = mid.ticks_per_beat
    seconds_at_start = 0.0

    for i, (tick, tempo) in enumerate(events):
        next_tick = events[i + 1][0] if i + 1 < len(events) else None
        segments.append(
            {
                "tick_start": tick,
                "tick_end": next_tick,
                "tempo_us": tempo,
                "seconds_at_start": seconds_at_start,
            }
        )
        if next_tick is not None:
            dticks = next_tick - tick
            seconds_at_start += (tempo / 1_000_000.0) * (dticks / tpb)

    return segments


def _ticks_to_frames(tick: int, segments: list[dict], tpb: int, fps: int) -> int:
    for seg in segments:
        if seg["tick_end"] is None or tick < seg["tick_end"]:
            dticks = tick - seg["tick_start"]
            seconds = seg["seconds_at_start"] + (seg["tempo_us"] / 1_000_000.0) * (dticks / tpb)
            return int(round(seconds * fps))
    # Fallback when tick exceeds the last tempo segment.
    seg = segments[-1]
    dticks = tick - seg["tick_start"]
    seconds = seg["seconds_at_start"] + (seg["tempo_us"] / 1_000_000.0) * (dticks / tpb)
    return int(round(seconds * fps))


def _format_summary(events: list[dict], stats: dict, comment: str) -> str:
    per_channel = defaultdict(int)
    for ev in events:
        per_channel[ev["channel"]] += 1

    lines = [
        f"{comment} MIDI summary: ticks_per_beat={stats['ticks_per_beat']}, "
        f"total_ticks={stats['total_ticks']}, events={stats['event_count']}",
    ]
    if stats.get("pitch_bend_events", 0):
        lines.append(
            f"{comment} Pitch bend: events={stats['pitch_bend_events']}, "
            f"during_notes={stats.get('pitch_bend_during_note', 0)}"
        )
    if stats.get("cc_volume_events", 0) or stats.get("cc_expression_events", 0):
        lines.append(
            f"{comment} CC volume/expression: cc7={stats.get('cc_volume_events', 0)} "
            f"cc11={stats.get('cc_expression_events', 0)}"
        )
    if stats.get("cc_sustain_events", 0):
        lines.append(f"{comment} CC sustain: events={stats.get('cc_sustain_events', 0)}")
    if stats.get("program_change_events", 0):
        lines.append(f"{comment} Program change: events={stats.get('program_change_events', 0)}")

    if per_channel:
        channels = " ".join(f"ch{ch}:{count}" for ch, count in sorted(per_channel.items()))
        lines.append(f"{comment} Channel usage: {channels}")

    preview = events[:20]
    if preview:
        lines.append(f"{comment} First events (start/dur/note/ch/vel):")
        for ev in preview:
            lines.append(
                f"{comment} t={ev['start']:6d} d={ev['duration']:4d} "
                f"n={ev['note']:3d} ch={ev['channel']:2d} v={ev['velocity']:3d}"
            )

    return "\n".join(lines) + "\n"


def _clamp_int(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def _note_idx_to_div(note_idx: int) -> int:
    idx = int(note_idx) - 1
    if idx < 0 or idx > NOTE_MAX_INDEX:
        return 1
    lo = NOTE_TABLE[idx * 2 + 0] & 0x0F
    hi = NOTE_TABLE[idx * 2 + 1] & 0x3F
    return (hi << 4) | lo


def _normalize_instrument(raw: dict | None, defaults: dict) -> dict:
    inst = dict(defaults)
    if not raw:
        return inst
    if "attn" in raw:
        inst["attn"] = _clamp_int(raw["attn"], 0, 15)
    env = raw.get("env")
    if env:
        if "step" in env:
            inst["env_step"] = _clamp_int(env["step"], 0, 4)
        if "speed" in env:
            inst["env_speed"] = _clamp_int(env["speed"], 1, 10)
    if "env_step" in raw:
        inst["env_step"] = _clamp_int(raw["env_step"], 0, 4)
    if "env_speed" in raw:
        inst["env_speed"] = _clamp_int(raw["env_speed"], 1, 10)

    vib = raw.get("vib")
    if vib:
        if "depth" in vib:
            inst["vib_depth"] = _clamp_int(vib["depth"], 0, 63)
        if "speed" in vib:
            inst["vib_speed"] = _clamp_int(vib["speed"], 1, 30)
        if "delay" in vib:
            inst["vib_delay"] = _clamp_int(vib["delay"], 0, 255)
    if "vib_depth" in raw:
        inst["vib_depth"] = _clamp_int(raw["vib_depth"], 0, 63)
    if "vib_speed" in raw:
        inst["vib_speed"] = _clamp_int(raw["vib_speed"], 1, 30)
    if "vib_delay" in raw:
        inst["vib_delay"] = _clamp_int(raw["vib_delay"], 0, 255)

    sweep = raw.get("sweep")
    if sweep:
        if "end" in sweep:
            inst["sweep_end"] = _clamp_int(sweep["end"], 1, 1023)
        if "end_idx" in sweep:
            inst["sweep_end"] = _note_idx_to_div(_clamp_int(sweep["end_idx"], 1, NOTE_MAX_INDEX + 1))
        if "step" in sweep:
            inst["sweep_step"] = _clamp_int(sweep["step"], -127, 127)
        if "speed" in sweep:
            inst["sweep_speed"] = _clamp_int(sweep["speed"], 1, 30)
    if "sweep_end" in raw:
        inst["sweep_end"] = _clamp_int(raw["sweep_end"], 1, 1023)
    if "sweep_end_idx" in raw:
        inst["sweep_end"] = _note_idx_to_div(_clamp_int(raw["sweep_end_idx"], 1, NOTE_MAX_INDEX + 1))
    if "sweep_step" in raw:
        inst["sweep_step"] = _clamp_int(raw["sweep_step"], -127, 127)
    if "sweep_speed" in raw:
        inst["sweep_speed"] = _clamp_int(raw["sweep_speed"], 1, 30)
    return inst


def _load_instrument_map(path: str) -> tuple[dict, dict[int, dict], int]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    defaults = {
        "attn": 2,
        "env_step": 0,
        "env_speed": 1,
        "vib_depth": 0,
        "vib_speed": 3,
        "vib_delay": 0,
        "sweep_end": 1,
        "sweep_step": 0,
        "sweep_speed": 1,
    }
    defaults = _normalize_instrument(data.get("default"), defaults)
    programs: dict[int, dict] = {}
    for key, raw in data.get("programs", {}).items():
        try:
            prog = int(key)
        except ValueError:
            continue
        programs[prog] = _normalize_instrument(raw, defaults)
    default_program = int(data.get("default_program", 0))
    return defaults, programs, default_program


def _instrument_to_opcodes(inst: dict) -> list[int]:
    return [
        BGM_OP_SET_ATTN,
        inst["attn"],
        BGM_OP_SET_ENV,
        inst["env_step"],
        inst["env_speed"],
        BGM_OP_SET_VIB,
        inst["vib_depth"],
        inst["vib_speed"],
        inst["vib_delay"],
        BGM_OP_SET_SWEEP,
        inst["sweep_end"] & 0xFF,
        (inst["sweep_end"] >> 8) & 0xFF,
        inst["sweep_step"] & 0xFF,
        inst["sweep_speed"],
    ]


def _format_inst(inst: dict) -> str:
    return (
        f"attn={inst['attn']} "
        f"env={inst['env_step']}/{inst['env_speed']} "
        f"vib={inst['vib_depth']}/{inst['vib_speed']}/{inst['vib_delay']} "
        f"sweep={inst['sweep_end']},{inst['sweep_step']},{inst['sweep_speed']}"
    )


def _count_out_of_range_events(events: list[dict], base_midi: int) -> int:
    count = 0
    for ev in events:
        if _note_to_index(ev["note"], base_midi) is None:
            count += 1
    return count


def _max_end_frame(events: list[dict]) -> int:
    if not events:
        return 0
    return max(ev["start_frame"] + ev["duration_frame"] for ev in events)


def _max_polyphony(events: list[dict]) -> int:
    if not events:
        return 0
    points = []
    for ev in events:
        start = ev["start_frame"]
        end = ev["start_frame"] + ev["duration_frame"]
        points.append((start, 1))
        points.append((end, -1))
    points.sort(key=lambda x: (x[0], -x[1]))
    cur = 0
    max_cur = 0
    for _, delta in points:
        cur += delta
        if cur > max_cur:
            max_cur = cur
    return max_cur


def _density_score(ev: dict, channel_bias: int, bass_bias: int) -> int:
    # Prefer longer notes, then velocity, then lower channel numbers and lower pitches.
    pitch_bonus = bass_bias * (127 - ev["note"])
    return (ev["duration_frame"] * 2) + ev["velocity"] + channel_bias * (15 - ev["channel"]) + pitch_bonus


def _limit_density(
    events: list[dict],
    limit: int,
    channel_bias: int,
    bass_bias: int,
) -> tuple[list[dict], int]:
    if limit <= 0:
        return events, 0
    by_start: dict[int, list[dict]] = defaultdict(list)
    for ev in events:
        by_start[ev["start_frame"]].append(ev)
    kept: list[dict] = []
    dropped = 0
    for start in sorted(by_start.keys()):
        group = by_start[start]
        if len(group) <= limit:
            kept.extend(group)
            continue
        group_sorted = sorted(
            group, key=lambda e: _density_score(e, channel_bias, bass_bias), reverse=True
        )
        kept.extend(group_sorted[:limit])
        dropped += len(group_sorted) - limit
    kept.sort(key=lambda e: (e["start_frame"], e["channel"], e["note"]))
    return kept, dropped

def _apply_transpose_and_clamp(
    events: list[dict],
    base_midi: int,
    auto_transpose: bool,
    clamp: bool,
    noise_channel: int | None = None,
) -> tuple[list[dict], int]:
    if not events:
        return events, 0

    tonal = [ev for ev in events if noise_channel is None or ev["channel"] != noise_channel]
    if not tonal:
        return events, 0
    min_note = min(ev["note"] for ev in tonal)
    max_note = max(ev["note"] for ev in tonal)
    low = base_midi
    high = base_midi + NOTE_MAX_INDEX

    transpose = 0
    if auto_transpose:
        # Find minimal transpose that fits the range.
        candidates = []
        for t in range(-48, 49):
            if min_note + t >= low and max_note + t <= high:
                candidates.append(t)
        if candidates:
            transpose = min(candidates, key=lambda x: (abs(x), x))

    out = []
    for ev in events:
        if noise_channel is not None and ev["channel"] == noise_channel:
            note = ev["note"]
            out.append(
                {
                    "start": ev["start"],
                    "duration": ev["duration"],
                    "note": note,
                    "channel": ev["channel"],
                    "velocity": ev["velocity"],
                }
            )
            continue
        else:
            note = ev["note"] + transpose
        if clamp:
            if note < low:
                note = low
            elif note > high:
                note = high
        out.append(
            {
                "start": ev["start"],
                "duration": ev["duration"],
                "note": note,
                "channel": ev["channel"],
                "velocity": ev["velocity"],
            }
        )

    return out, transpose


def _quantize_events(events: list[dict], grid: int) -> list[dict]:
    quantized = []
    for ev in events:
        start = int((ev["start"] + grid / 2) // grid) * grid
        end = int((ev["start"] + ev["duration"] + grid / 2) // grid) * grid
        if end <= start:
            end = start + grid
        quantized.append(
            {
                "start": start,
                "duration": end - start,
                "note": ev["note"],
                "channel": ev["channel"],
                "velocity": ev["velocity"],
                "bend": ev.get("bend", 0),
            }
        )
    quantized.sort(key=lambda e: (e["start"], e["channel"], e["note"]))
    return quantized


def _split_events_by_bend(
    events: list[dict],
    bend_events_by_channel: dict[int, list[tuple[int, int]]],
) -> tuple[list[dict], int]:
    if not bend_events_by_channel:
        return events, 0
    out: list[dict] = []
    split_count = 0
    for ev in events:
        ch = ev["channel"]
        bends = bend_events_by_channel.get(ch)
        if not bends:
            out.append(
                {
                    "start": ev["start"],
                    "duration": ev["duration"],
                    "note": ev["note"],
                    "channel": ch,
                    "velocity": ev["velocity"],
                    "bend": ev.get("bend", 0),
                }
            )
            continue
        start = ev["start"]
        end = ev["start"] + ev["duration"]
        if end <= start:
            continue
        current_bend = 0
        idx = 0
        while idx < len(bends) and bends[idx][0] <= start:
            current_bend = bends[idx][1]
            idx += 1
        cur_start = start
        while idx < len(bends) and bends[idx][0] < end:
            tick, bend = bends[idx]
            if tick > cur_start:
                out.append(
                    {
                        "start": cur_start,
                        "duration": tick - cur_start,
                        "note": ev["note"],
                        "channel": ch,
                        "velocity": ev["velocity"],
                        "bend": current_bend,
                    }
                )
                split_count += 1
            current_bend = bend
            cur_start = tick
            idx += 1
        if cur_start < end:
            out.append(
                {
                    "start": cur_start,
                    "duration": end - cur_start,
                    "note": ev["note"],
                    "channel": ch,
                    "velocity": ev["velocity"],
                    "bend": current_bend,
                }
            )
    out.sort(key=lambda e: (e["start"], e["channel"], e["note"]))
    return out, split_count


def _apply_pitch_bend(
    events: list[dict],
    bend_range: int,
    noise_channel: int | None = None,
) -> tuple[list[dict], int, int]:
    if bend_range <= 0:
        return events, 0, 0
    out = []
    shifted = 0
    max_shift = 0
    for ev in events:
        if noise_channel is not None and ev["channel"] == noise_channel:
            out.append(
                {
                    "start": ev["start"],
                    "duration": ev["duration"],
                    "note": ev["note"],
                    "channel": ev["channel"],
                    "velocity": ev["velocity"],
                }
            )
            continue
        bend = int(ev.get("bend", 0))
        if bend:
            semis = int(round((bend / 8192.0) * bend_range))
        else:
            semis = 0
        note = ev["note"] + semis
        if semis != 0:
            shifted += 1
            if abs(semis) > max_shift:
                max_shift = abs(semis)
        out.append(
            {
                "start": ev["start"],
                "duration": ev["duration"],
                "note": note,
                "channel": ev["channel"],
                "velocity": ev["velocity"],
            }
        )
    return out, shifted, max_shift


def _split_events_by_cc_volume(
    events: list[dict],
    cc_events_by_channel: dict[int, list[tuple[int, int, int]]],
) -> tuple[list[dict], int, int]:
    if not cc_events_by_channel:
        return events, 0, 0
    out: list[dict] = []
    split_count = 0
    scaled_count = 0
    for ev in events:
        ch = ev["channel"]
        ccs = cc_events_by_channel.get(ch)
        if not ccs:
            out.append(
                {
                    "start": ev["start"],
                    "duration": ev["duration"],
                    "note": ev["note"],
                    "channel": ch,
                    "velocity": ev["velocity"],
                    "bend": ev.get("bend", 0),
                }
            )
            continue
        start = ev["start"]
        end = ev["start"] + ev["duration"]
        if end <= start:
            continue
        cur_vol = 127
        cur_expr = 127
        idx = 0
        while idx < len(ccs) and ccs[idx][0] <= start:
            _, cur_vol, cur_expr = ccs[idx]
            idx += 1
        cur_start = start
        while idx < len(ccs) and ccs[idx][0] < end:
            tick, vol, expr = ccs[idx]
            if tick > cur_start:
                vel = int(round(ev["velocity"] * (cur_vol / 127.0) * (cur_expr / 127.0)))
                if vel < 0:
                    vel = 0
                elif vel > 127:
                    vel = 127
                out.append(
                    {
                        "start": cur_start,
                        "duration": tick - cur_start,
                        "note": ev["note"],
                        "channel": ch,
                        "velocity": vel,
                        "bend": ev.get("bend", 0),
                    }
                )
                split_count += 1
                scaled_count += 1
            cur_vol = vol
            cur_expr = expr
            cur_start = tick
            idx += 1
        if cur_start < end:
            vel = int(round(ev["velocity"] * (cur_vol / 127.0) * (cur_expr / 127.0)))
            if vel < 0:
                vel = 0
            elif vel > 127:
                vel = 127
            out.append(
                {
                    "start": cur_start,
                    "duration": end - cur_start,
                    "note": ev["note"],
                    "channel": ch,
                    "velocity": vel,
                    "bend": ev.get("bend", 0),
                }
            )
            scaled_count += 1
    out.sort(key=lambda e: (e["start"], e["channel"], e["note"]))
    return out, split_count, scaled_count


def _pick_channels(events: list[dict], max_channels: int, exclude: set[int] | None = None) -> set[int]:
    counts = defaultdict(int)
    exclude = exclude or set()
    for ev in events:
        if ev["channel"] not in exclude:
            counts[ev["channel"]] += 1
    ordered = [ch for ch, _ in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)]
    return set(ordered[:max_channels])


def _events_to_frame_events(
    events: list[dict],
    tpb: int,
    fps: int,
    segments: list[dict],
) -> list[dict]:
    frame_events = []
    for ev in events:
        start_frame = _ticks_to_frames(ev["start"], segments, tpb, fps)
        end_frame = _ticks_to_frames(ev["start"] + ev["duration"], segments, tpb, fps)
        if end_frame <= start_frame:
            end_frame = start_frame + 1
        frame_events.append(
            {
                "start_frame": start_frame,
                "duration_frame": end_frame - start_frame,
                "note": ev["note"],
                "channel": ev["channel"],
                "velocity": ev["velocity"],
            }
        )
    frame_events.sort(key=lambda e: (e["start_frame"], e["channel"], e["note"]))
    return frame_events


def _program_events_to_frames(
    program_events_by_channel: dict[int, list[tuple[int, int]]],
    tpb: int,
    fps: int,
    segments: list[dict],
    grid: int,
) -> dict[int, tuple[list[int], list[int]]]:
    timelines: dict[int, tuple[list[int], list[int]]] = {}
    for ch, events in program_events_by_channel.items():
        if not events:
            continue
        events_sorted = sorted(events, key=lambda e: e[0])
        frames: list[int] = []
        programs: list[int] = []
        for tick, program in events_sorted:
            if grid > 1:
                tick = int((tick + grid / 2) // grid) * grid
            frame = _ticks_to_frames(tick, segments, tpb, fps)
            if frames and frames[-1] == frame:
                programs[-1] = int(program)
            else:
                frames.append(frame)
                programs.append(int(program))
        timelines[ch] = (frames, programs)
    return timelines


def _program_at_frame(
    timeline: tuple[list[int], list[int]] | None,
    frame: int,
    default_program: int,
) -> int:
    if not timeline:
        return default_program
    frames, programs = timeline
    if not frames:
        return default_program
    idx = bisect_right(frames, frame) - 1
    if idx < 0:
        return default_program
    return programs[idx]


def _build_fx_events_for_voice(
    voice_events: list[dict],
    program_timelines: dict[int, tuple[list[int], list[int]]],
    default_program: int,
    default_inst: dict,
    program_instruments: dict[int, dict],
) -> list[dict]:
    fx_events: list[dict] = []
    last_program = None
    for ev in sorted(voice_events, key=lambda e: (e["start_frame"], e["channel"], e["note"])):
        timeline = program_timelines.get(ev["channel"])
        program = _program_at_frame(timeline, ev["start_frame"], default_program)
        if program != last_program:
            inst = program_instruments.get(program, default_inst)
            fx_events.append(
                {
                    "frame": ev["start_frame"],
                    "ops": _instrument_to_opcodes(inst),
                    "program": program,
                    "inst": inst,
                    "channel": ev["channel"],
                }
            )
            last_program = program
    return fx_events


def _note_to_index(note: int, base_midi: int) -> int | None:
    idx = note - base_midi
    if 0 <= idx <= NOTE_MAX_INDEX:
        # Reserve 0x00 as end marker in streams.
        return idx + 1
    return None


def _build_stream(
    events: list[dict],
    base_midi: int,
    loop_start_frame: int | None = None,
) -> tuple[list[int], dict]:
    cursor = 0
    out: list[int] = []
    dropped = 0
    dropped_overlap = 0
    out_of_range = 0
    loop_offset = None

    for ev in events:
        if ev["start_frame"] < cursor:
            dropped_overlap += 1
            continue
        if ev["start_frame"] > cursor:
            if loop_offset is None and loop_start_frame is not None and cursor >= loop_start_frame:
                loop_offset = len(out)
            rest_units = ev["start_frame"] - cursor
            if rest_units > 0:
                while rest_units > 0:
                    chunk = min(255, rest_units)
                    out.extend([REST_CODE, chunk])
                    rest_units -= chunk
            cursor = ev["start_frame"]

        if loop_offset is None and loop_start_frame is not None and ev["start_frame"] >= loop_start_frame:
            loop_offset = len(out)

        note_idx = _note_to_index(ev["note"], base_midi)
        dur_units = ev["duration_frame"]
        if dur_units <= 0:
            dur_units = 1

        if note_idx is None:
            out_of_range += 1
            # Treat out-of-range as rest.
            while dur_units > 0:
                chunk = min(255, dur_units)
                out.extend([REST_CODE, chunk])
                dur_units -= chunk
        else:
            while dur_units > 0:
                chunk = min(255, dur_units)
                out.extend([note_idx, chunk])
                dur_units -= chunk

        cursor += ev["duration_frame"]

    if loop_offset is None and loop_start_frame is not None:
        loop_offset = len(out)

    out.append(0)
    return out, {
        "dropped": dropped,
        "dropped_overlap": dropped_overlap,
        "out_of_range": out_of_range,
        "bytes": len(out),
        "loop_offset": loop_offset if loop_offset is not None else 0,
    }


def _build_stream_with_fx(
    events: list[dict],
    base_midi: int,
    loop_start_frame: int | None,
    fx_events: list[dict],
) -> tuple[list[int], dict]:
    cursor = 0
    out: list[int] = []
    dropped = 0
    dropped_overlap = 0
    out_of_range = 0
    loop_offset = None
    fx_sorted = sorted(fx_events, key=lambda e: e["frame"])
    fx_idx = 0

    def maybe_set_loop_offset(target_frame: int) -> None:
        nonlocal loop_offset
        if loop_offset is None and loop_start_frame is not None and target_frame >= loop_start_frame:
            loop_offset = len(out)

    for ev in events:
        if ev["start_frame"] < cursor:
            dropped_overlap += 1
            continue

        while fx_idx < len(fx_sorted) and fx_sorted[fx_idx]["frame"] <= ev["start_frame"]:
            fx_frame = fx_sorted[fx_idx]["frame"]
            if fx_frame > cursor:
                maybe_set_loop_offset(fx_frame)
                rest_units = fx_frame - cursor
                while rest_units > 0:
                    chunk = min(255, rest_units)
                    out.extend([REST_CODE, chunk])
                    rest_units -= chunk
                cursor = fx_frame
            maybe_set_loop_offset(cursor)
            out.extend(fx_sorted[fx_idx]["ops"])
            fx_idx += 1

        if ev["start_frame"] > cursor:
            maybe_set_loop_offset(ev["start_frame"])
            rest_units = ev["start_frame"] - cursor
            while rest_units > 0:
                chunk = min(255, rest_units)
                out.extend([REST_CODE, chunk])
                rest_units -= chunk
            cursor = ev["start_frame"]

        maybe_set_loop_offset(ev["start_frame"])
        note_idx = _note_to_index(ev["note"], base_midi)
        dur_units = ev["duration_frame"]
        if dur_units <= 0:
            dur_units = 1
        if note_idx is None:
            out_of_range += 1
            while dur_units > 0:
                chunk = min(255, dur_units)
                out.extend([REST_CODE, chunk])
                dur_units -= chunk
        else:
            while dur_units > 0:
                chunk = min(255, dur_units)
                out.extend([note_idx, chunk])
                dur_units -= chunk
        cursor += ev["duration_frame"]

    if loop_offset is None and loop_start_frame is not None:
        loop_offset = len(out)

    out.append(0)
    return out, {
        "dropped": dropped,
        "dropped_overlap": dropped_overlap,
        "out_of_range": out_of_range,
        "bytes": len(out),
        "loop_offset": loop_offset if loop_offset is not None else 0,
    }


def _build_noise_stream(events: list[dict], loop_start_frame: int | None = None) -> tuple[list[int], dict]:
    cursor = 0
    out: list[int] = []
    dropped_overlap = 0
    loop_offset = None

    for ev in events:
        if ev["start_frame"] < cursor:
            dropped_overlap += 1
            continue
        if ev["start_frame"] > cursor:
            if loop_offset is None and loop_start_frame is not None and cursor >= loop_start_frame:
                loop_offset = len(out)
            rest_units = ev["start_frame"] - cursor
            if rest_units > 0:
                while rest_units > 0:
                    chunk = min(255, rest_units)
                    out.extend([REST_CODE, chunk])
                    rest_units -= chunk
            cursor = ev["start_frame"]

        if loop_offset is None and loop_start_frame is not None and ev["start_frame"] >= loop_start_frame:
            loop_offset = len(out)

        # Reserve 0x00 as end marker; store 1..8
        note_idx = (ev["note"] & 0x07) + 1
        dur_units = ev["duration_frame"]
        if dur_units <= 0:
            dur_units = 1
        while dur_units > 0:
            chunk = min(255, dur_units)
            out.extend([note_idx, chunk])
            dur_units -= chunk

        cursor += ev["duration_frame"]

    if loop_offset is None and loop_start_frame is not None:
        loop_offset = len(out)

    out.append(0)
    return out, {
        "dropped": 0,
        "dropped_overlap": dropped_overlap,
        "out_of_range": 0,
        "bytes": len(out),
        "loop_offset": loop_offset if loop_offset is not None else 0,
    }


def _build_noise_stream_with_fx(
    events: list[dict],
    loop_start_frame: int | None,
    fx_events: list[dict],
) -> tuple[list[int], dict]:
    cursor = 0
    out: list[int] = []
    dropped_overlap = 0
    loop_offset = None
    fx_sorted = sorted(fx_events, key=lambda e: e["frame"])
    fx_idx = 0

    def maybe_set_loop_offset(target_frame: int) -> None:
        nonlocal loop_offset
        if loop_offset is None and loop_start_frame is not None and target_frame >= loop_start_frame:
            loop_offset = len(out)

    for ev in events:
        if ev["start_frame"] < cursor:
            dropped_overlap += 1
            continue

        while fx_idx < len(fx_sorted) and fx_sorted[fx_idx]["frame"] <= ev["start_frame"]:
            fx_frame = fx_sorted[fx_idx]["frame"]
            if fx_frame > cursor:
                maybe_set_loop_offset(fx_frame)
                rest_units = fx_frame - cursor
                while rest_units > 0:
                    chunk = min(255, rest_units)
                    out.extend([REST_CODE, chunk])
                    rest_units -= chunk
                cursor = fx_frame
            maybe_set_loop_offset(cursor)
            out.extend(fx_sorted[fx_idx]["ops"])
            fx_idx += 1

        if ev["start_frame"] > cursor:
            maybe_set_loop_offset(ev["start_frame"])
            rest_units = ev["start_frame"] - cursor
            while rest_units > 0:
                chunk = min(255, rest_units)
                out.extend([REST_CODE, chunk])
                rest_units -= chunk
            cursor = ev["start_frame"]

        maybe_set_loop_offset(ev["start_frame"])
        note_idx = (ev["note"] & 0x07) + 1
        dur_units = ev["duration_frame"]
        if dur_units <= 0:
            dur_units = 1
        while dur_units > 0:
            chunk = min(255, dur_units)
            out.extend([note_idx, chunk])
            dur_units -= chunk
        cursor += ev["duration_frame"]

    if loop_offset is None and loop_start_frame is not None:
        loop_offset = len(out)

    out.append(0)
    return out, {
        "dropped": 0,
        "dropped_overlap": dropped_overlap,
        "out_of_range": 0,
        "bytes": len(out),
        "loop_offset": loop_offset if loop_offset is not None else 0,
    }


def _add_loop_reset_fx(
    fx_events: list[dict],
    loop_start_frame: int | None,
    program_timelines: dict[int, tuple[list[int], list[int]]],
    default_program: int,
    default_inst: dict,
    program_instruments: dict[int, dict],
    channel: int,
) -> None:
    if loop_start_frame is None:
        return
    timeline = program_timelines.get(channel)
    program = _program_at_frame(timeline, loop_start_frame, default_program)
    inst = program_instruments.get(program, default_inst)
    fx_events.append(
        {
            "frame": loop_start_frame,
            "ops": _instrument_to_opcodes(inst),
            "program": program,
            "inst": inst,
            "channel": channel,
        }
    )


def _find_common_rest_frame(
    streams: list[list[dict]],
    total_frames: int,
    min_frame: int,
) -> int | None:
    """Find earliest frame where all streams are at rest."""
    if total_frames <= 0:
        return None
    if min_frame < 0:
        min_frame = 0
    # Precompute note intervals for each stream.
    intervals = []
    for events in streams:
        spans = []
        for ev in events:
            start = ev["start_frame"]
            end = start + ev["duration_frame"]
            if end > start:
                spans.append((start, end))
        intervals.append(spans)

    for t in range(min_frame, total_frames):
        all_rest = True
        for spans in intervals:
            active = False
            for start, end in spans:
                if start <= t < end:
                    active = True
                    break
            if active:
                all_rest = False
                break
        if all_rest:
            return t
    return None


def _program_inst_at_frame(
    program_timelines: dict[int, tuple[list[int], list[int]]],
    default_program: int,
    default_inst: dict,
    program_instruments: dict[int, dict],
    channel: int,
    frame: int,
) -> tuple[int, dict]:
    timeline = program_timelines.get(channel)
    program = _program_at_frame(timeline, frame, default_program)
    inst = program_instruments.get(program, default_inst)
    return program, inst


def _write_trace(
    path: str,
    header_lines: list[str],
    stream_entries: list[tuple[str, list[dict]]],
    program_timelines: dict[int, tuple[list[int], list[int]]],
    default_program: int,
    default_inst: dict,
    program_instruments: dict[int, dict],
    loop_start_frame: int | None,
) -> None:
    if not path:
        return
    lines = []
    lines.extend(header_lines)
    if loop_start_frame is not None:
        lines.append(f"loop_start_frame={loop_start_frame}")
    lines.append("")
    for label, events in stream_entries:
        lines.append(f"[{label}]")
        for ev in sorted(events, key=lambda e: (e["start_frame"], e["note"])):
            frame = ev["start_frame"]
            prog, inst = _program_inst_at_frame(
                program_timelines,
                default_program,
                default_inst,
                program_instruments,
                ev["channel"],
                frame,
            )
            inst_str = _format_inst(inst) if inst else "inst=none"
            lines.append(
                f"frame={frame} dur={ev['duration_frame']} note={ev['note']} "
                f"ch={ev['channel']} vel={ev['velocity']} prog={prog} {inst_str}"
            )
        lines.append("")
    with open(path, "w", encoding="ascii", errors="ignore") as f:
        f.write("\n".join(lines) + "\n")


def _drum_snk_map(noise_events: list[dict], base_midi: int) -> tuple[list[dict], list[dict], int]:
    """Map GM drums to a more SNK-like mix: kick on tone, snare on noise, hats optional."""
    tone_events: list[dict] = []
    noise_out: list[dict] = []
    dropped = 0

    for ev in noise_events:
        note = ev["note"]
        start = ev["start_frame"]
        dur = ev["duration_frame"]
        if note in (35, 36):  # Kick
            tone_events.append(
                {
                    "start_frame": start,
                    "duration_frame": min(6, max(1, dur)),
                    "note": base_midi,  # low thump
                    "channel": 0,
                    "velocity": max(100, ev["velocity"]),
                }
            )
        elif note in (38, 40):  # Snare
            noise_out.append(
                {
                    "start_frame": start,
                    "duration_frame": min(4, max(1, dur)),
                    "note": 2,  # noise index (0..7)
                    "channel": ev["channel"],
                    "velocity": ev["velocity"],
                }
            )
        elif note in (42, 44, 46):  # Hats
            noise_out.append(
                {
                    "start_frame": start,
                    "duration_frame": min(2, max(1, dur)),
                    "note": 5,  # brighter noise index
                    "channel": ev["channel"],
                    "velocity": ev["velocity"],
                }
            )
        else:
            dropped += 1

    return tone_events, noise_out, dropped


def _format_stream(label: str, stream: list[int]) -> str:
    lines = [f"{label}:"]
    line = "  .db "
    for i, b in enumerate(stream):
        entry = f"${b:02X}"
        if line.strip() == ".db":
            line += entry
        else:
            line += f", {entry}"
        if len(line) > 70:
            lines.append(line)
            line = "  .db "
    if line.strip() != ".db":
        lines.append(line)
    return "\n".join(lines) + "\n"


def _stream_total_frames(stream: list[int], rest_code: int = REST_CODE) -> int:
    total = 0
    i = 0
    while i < len(stream):
        note = stream[i]
        if note == 0x00:
            break
        if note >= BGM_OP_SET_ATTN:
            if note == BGM_OP_SET_ATTN:
                i += 2
                continue
            if note == BGM_OP_SET_ENV:
                i += 3
                continue
            if note == BGM_OP_SET_VIB:
                i += 4
                continue
            if note == BGM_OP_SET_SWEEP:
                i += 5
                continue
            if note == BGM_OP_SET_INST:
                i += 2
                continue
            i += 1
            continue
        if i + 1 >= len(stream):
            break
        total += stream[i + 1]
        i += 2
    return total

def _format_c_array(label: str, stream: list[int]) -> str:
    lines = [f"const unsigned char {label}[] = {{"]
    line = "  "
    for i, b in enumerate(stream):
        entry = f"0x{b:02X}"
        if i == 0:
            line += entry
        else:
            line += f", {entry}"
        if len(line) > 70:
            lines.append(line)
            line = "  "
    if line.strip():
        lines.append(line)
    lines.append("};")
    return "\n".join(lines) + "\n"


def _format_note_table(label: str) -> str:
    lines = [f"{label}:"]
    line = "  .db "
    for b1, b2 in NOTE_TABLE:
        for b in (b1, b2):
            if line.strip() == ".db":
                line += f"${b:02X}"
            else:
                line += f", ${b:02X}"
            if len(line) > 70:
                lines.append(line)
                line = "  .db "
    if line.strip() != ".db":
        lines.append(line)
    return "\n".join(lines) + "\n"


def _velocity_to_attn(velocity: int, min_attn: int, max_attn: int) -> int:
    # velocity 1..127 -> attn 0..15 (0 = loudest)
    if velocity <= 0:
        velocity = 1
    velocity = min(127, velocity)
    scale = 1.0 - (velocity / 127.0)
    attn = int(round(min_attn + (max_attn - min_attn) * scale))
    return max(0, min(15, attn))


def _build_attn_stream(
    events: list[dict],
    min_attn: int,
    max_attn: int,
) -> list[int]:
    out = []
    for ev in events:
        dur_units = ev["duration_frame"]
        if dur_units <= 0:
            dur_units = 1
        attn = _velocity_to_attn(ev["velocity"], min_attn, max_attn)
        while dur_units > 0:
            chunk = min(255, dur_units)
            out.extend([attn, chunk])
            dur_units -= chunk
    out.append(0xFF)  # terminator (attn values are 0..15)
    return out

def _build_mono_events(events: list[dict]) -> list[dict]:
    # Keep one note at a time, preferring higher velocity on same frame.
    ordered = sorted(
        events, key=lambda e: (e["start_frame"], -e["velocity"], e["channel"], e["note"])
    )
    mono = []
    cursor = -1
    for ev in ordered:
        if ev["start_frame"] == cursor:
            # Already picked a note for this frame.
            continue
        mono.append(ev)
        cursor = ev["start_frame"]
    return mono


def _event_priority(ev: dict) -> int:
    # Prefer longer notes, then higher velocity.
    return (ev["duration_frame"] << 8) + ev["velocity"]


def _split_events_to_voices(
    events: list[dict],
    voices: int,
    allow_preempt: bool,
) -> tuple[list[list[dict]], dict]:
    """Greedy allocator with priority and optional preemption.

    Assign each event to the first free voice. If all voices are busy,
    compare priority against the weakest active note; if stronger, preempt
    by truncating the active note and assign the new one. Otherwise drop.
    """
    by_voice = [[] for _ in range(max(1, voices))]
    voice_busy_until = [0 for _ in range(max(1, voices))]
    voice_active_idx = [-1 for _ in range(max(1, voices))]
    dropped = 0
    preempted = 0

    ordered = sorted(events, key=lambda e: (e["start_frame"], -e["velocity"], e["note"]))
    for ev in ordered:
        assigned = -1
        for i in range(len(by_voice)):
            if voice_busy_until[i] <= ev["start_frame"]:
                assigned = i
                break
        if assigned >= 0:
            by_voice[assigned].append(ev)
            voice_active_idx[assigned] = len(by_voice[assigned]) - 1
            voice_busy_until[assigned] = ev["start_frame"] + ev["duration_frame"]
            continue

        # All voices busy: consider preemption.
        if not allow_preempt:
            dropped += 1
            continue
        weakest_voice = -1
        weakest_score = None
        for i in range(len(by_voice)):
            idx = voice_active_idx[i]
            if idx < 0:
                continue
            active = by_voice[i][idx]
            if active["start_frame"] <= ev["start_frame"] < active["start_frame"] + active["duration_frame"]:
                score = _event_priority(active)
                if weakest_score is None or score < weakest_score:
                    weakest_score = score
                    weakest_voice = i

        if weakest_voice < 0:
            dropped += 1
            continue

        if _event_priority(ev) <= weakest_score:
            dropped += 1
            continue

        # Preempt: truncate active note to end at new start.
        idx = voice_active_idx[weakest_voice]
        active = by_voice[weakest_voice][idx]
        new_dur = ev["start_frame"] - active["start_frame"]
        if new_dur <= 0:
            dropped += 1
            continue
        active["duration_frame"] = new_dur
        preempted += 1
        by_voice[weakest_voice].append(ev)
        voice_active_idx[weakest_voice] = len(by_voice[weakest_voice]) - 1
        voice_busy_until[weakest_voice] = ev["start_frame"] + ev["duration_frame"]

    return by_voice, {"dropped": dropped, "preempted": preempted}


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Minimal MIDI -> ASM for NGPC T6W28")
    parser.add_argument("input_mid")
    parser.add_argument("output_asm")
    parser.add_argument(
        "--profile",
        choices=["mono_strict", "poly2", "timing", "fidelity"],
        help="Quick presets: mono_strict, poly2, timing, fidelity",
    )
    parser.add_argument("--grid", type=int, default=DEFAULT_GRID, help="Quantize grid in ticks")
    parser.add_argument("--channels", type=int, default=DEFAULT_MAX_CHANNELS, help="Max channels to keep")
    parser.add_argument("--base-midi", type=int, default=NOTE_BASE_MIDI, help="Base MIDI note for index 0")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS, help="Target playback FPS (default 60)")
    parser.add_argument("--mono", action="store_true", default=True, help="Force mono output (default)")
    parser.add_argument("--poly", action="store_true", default=False, help="Use per-channel streams")
    parser.add_argument("--split-voices", action="store_true", default=True, help="Split notes across voices in poly mode (default)")
    parser.add_argument("--no-split-voices", dest="split_voices", action="store_false", help="Disable voice splitting")
    parser.add_argument("--preempt", action="store_true", default=True, help="Allow voice preemption in poly split (default)")
    parser.add_argument("--no-preempt", dest="preempt", action="store_false", help="Disable voice preemption")
    parser.add_argument("--auto-transpose", action="store_true", default=True, help="Auto-fit notes to table (default)")
    parser.add_argument("--no-auto-transpose", dest="auto_transpose", action="store_false", help="Disable auto transpose")
    parser.add_argument("--clamp", action="store_true", default=True, help="Clamp out-of-range notes (default)")
    parser.add_argument("--no-clamp", dest="clamp", action="store_false", help="Disable clamping")
    parser.add_argument("--use-velocity", action="store_true", default=False, help="Emit attenuation stream")
    parser.add_argument("--attn-min", type=int, default=0, help="Loudest attenuation (0..15)")
    parser.add_argument("--attn-max", type=int, default=12, help="Quietest attenuation (0..15)")
    parser.add_argument("--c-array", action="store_true", default=False, help="Emit C arrays instead of ASM")
    parser.add_argument(
        "--pitchbend-range",
        type=int,
        default=2,
        help="Pitch bend range in semitones (applied at note start, default 2)",
    )
    parser.add_argument(
        "--no-pitchbend",
        dest="pitchbend_range",
        action="store_const",
        const=0,
        help="Disable pitch bend mapping",
    )
    parser.add_argument(
        "--use-cc-volume",
        action="store_true",
        default=False,
        help="Apply CC7/CC11 to note velocity",
    )
    parser.add_argument(
        "--no-sustain",
        dest="use_sustain",
        action="store_false",
        default=True,
        help="Disable CC64 sustain handling",
    )
    parser.add_argument("--noise-channel", type=int, default=9, help="MIDI channel used as noise (default 9, GM drums)")
    parser.add_argument(
        "--force-noise-stream",
        action="store_true",
        default=False,
        help="Emit BGM_CHN even if no noise events (empty stream)",
    )
    parser.add_argument(
        "--force-tone-streams",
        action="store_true",
        default=False,
        help="Emit BGM_CH0..CH2 even if no tone events (empty streams)",
    )
    parser.add_argument(
        "--drum-mode",
        choices=["off", "snk"],
        default="snk",
        help="Drum handling for noise channel: off (raw noise) or snk (kick->tone, snare->noise)",
    )
    parser.add_argument(
        "--instrument-map",
        type=str,
        default=None,
        help="JSON instrument map (Program Change -> FX opcodes)",
    )
    parser.add_argument(
        "--opcodes",
        dest="emit_opcodes",
        action="store_true",
        default=None,
        help="Emit FX opcodes in streams (requires --instrument-map)",
    )
    parser.add_argument(
        "--no-opcodes",
        dest="emit_opcodes",
        action="store_false",
        default=None,
        help="Disable FX opcodes",
    )
    parser.add_argument(
        "--density-mode",
        choices=["auto", "off", "soft", "hard"],
        default="auto",
        help="Limit dense chords: auto/off/soft/hard (auto keeps closer to MIDI)",
    )
    parser.add_argument(
        "--density-bias",
        type=int,
        default=6,
        help="Extra weight for lower channel numbers when thinning dense chords",
    )
    parser.add_argument(
        "--density-bass",
        type=int,
        default=2,
        help="Extra weight for lower pitches when thinning dense chords",
    )
    parser.add_argument("--loop-start-frame", type=int, default=None, help="Loop start position in frames (optional)")
    parser.add_argument("--loop-start-tick", type=int, default=None, help="Loop start position in MIDI ticks (optional)")
    parser.add_argument(
        "--auto-loop-rest",
        type=float,
        default=None,
        help="Auto-pick loop start on a common rest (min percent of song, e.g. 0.5)",
    )
    parser.add_argument(
        "--loop-reset-fx",
        action="store_true",
        help="Re-emit instrument FX at loop start (requires --instrument-map/--opcodes)",
    )
    parser.add_argument(
        "--trace-output",
        type=str,
        default="",
        help="Write a trace log (per-stream events and FX decisions) to this file",
    )
    return parser.parse_args(argv[1:])


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    input_mid = args.input_mid
    output_asm = args.output_asm
    warnings: list[str] = []
    density_dropped = 0

    if args.profile == "mono_strict":
        args.mono = True
        args.poly = False
        args.channels = 1
    elif args.profile == "poly2":
        args.mono = False
        args.poly = True
        args.channels = 2
        args.split_voices = True
        args.preempt = True
    elif args.profile == "timing":
        args.mono = True
        args.poly = False
        args.channels = 1
        args.grid = 1
    elif args.profile == "fidelity":
        args.mono = False
        args.poly = True
        args.channels = 4
        args.split_voices = False
        args.preempt = False
        args.grid = 1
        args.density_mode = "off"
        args.use_cc_volume = True
        args.use_sustain = True
        args.force_noise_stream = True
        args.force_tone_streams = True

    if args.grid <= 0:
        print("Error: --grid must be > 0.")
        return 2
    if args.fps <= 0:
        print("Error: --fps must be > 0.")
        return 2
    if args.channels <= 0:
        print("Error: --channels must be > 0.")
        return 2

    default_inst = None
    program_instruments: dict[int, dict] = {}
    default_program = 0
    emit_opcodes = args.emit_opcodes
    if args.instrument_map:
        default_inst, program_instruments, default_program = _load_instrument_map(args.instrument_map)
        if emit_opcodes is None:
            emit_opcodes = True
    if emit_opcodes and not args.instrument_map:
        print("Error: --opcodes requires --instrument-map.")
        return 2
    if emit_opcodes is None:
        emit_opcodes = False
    if args.loop_reset_fx and not emit_opcodes:
        print("Error: --loop-reset-fx requires --instrument-map/--opcodes.")
        return 2

    mid = mido.MidiFile(input_mid)
    if mid.type not in (0, 1):
        print("Error: unsupported MIDI type. Use Type 0 or Type 1.")
        return 2
    segments = _build_tempo_segments(mid)
    if not segments:
        print("Error: no tempo info found.")
        return 2
    tempo_first = segments[0]["tempo_us"]
    tempo_last = segments[-1]["tempo_us"]
    events, stats, bend_events_by_channel, cc_events_by_channel, program_events_by_channel = _extract_note_events(
        mid, args.use_cc_volume, args.use_sustain
    )
    if not events:
        print("Error: no note events found in MIDI.")
        return 2
    bend_splits = 0
    cc_splits = 0
    cc_scaled = 0
    if args.pitchbend_range > 0 and stats.get("pitch_bend_events", 0) > 0:
        events, bend_splits = _split_events_by_bend(events, bend_events_by_channel)
    if args.use_cc_volume and (stats.get("cc_volume_events", 0) or stats.get("cc_expression_events", 0)):
        events, cc_splits, cc_scaled = _split_events_by_cc_volume(events, cc_events_by_channel)
    events_q = _quantize_events(events, args.grid)
    events_bent, bend_shifted, bend_max = _apply_pitch_bend(
        events_q, args.pitchbend_range, args.noise_channel
    )
    events, transpose = _apply_transpose_and_clamp(
        events_bent, args.base_midi, args.auto_transpose, args.clamp, args.noise_channel
    )
    frame_events = _events_to_frame_events(events, mid.ticks_per_beat, args.fps, segments)
    program_timelines = {}
    if emit_opcodes:
        program_timelines = _program_events_to_frames(
            program_events_by_channel,
            mid.ticks_per_beat,
            args.fps,
            segments,
            args.grid,
        )
    loop_start_frame = args.loop_start_frame
    if loop_start_frame is None and args.loop_start_tick is not None:
        loop_start_frame = _ticks_to_frames(args.loop_start_tick, segments, mid.ticks_per_beat, args.fps)
    noise_channel = args.noise_channel
    noise_events = [ev for ev in frame_events if ev["channel"] == noise_channel]
    drum_dropped = 0
    if noise_events and args.drum_mode == "snk":
        drum_tone, noise_events, drum_dropped = _drum_snk_map(noise_events, args.base_midi)
        frame_events = [ev for ev in frame_events if ev["channel"] != noise_channel] + noise_events + drum_tone
        frame_events.sort(key=lambda e: (e["start_frame"], e["channel"], e["note"]))
    noise_enabled = args.poly and args.channels >= 4 and (len(noise_events) > 0 or args.force_noise_stream)
    tone_channels = args.channels - 1 if noise_enabled else args.channels
    channels = _pick_channels(events_q, tone_channels, exclude={noise_channel})

    if args.poly and args.density_mode != "off":
        tone_events = [ev for ev in frame_events if ev["channel"] != noise_channel]
        max_poly = _max_polyphony(tone_events)
        if args.density_mode == "hard":
            limit = max(1, tone_channels)
        elif args.density_mode == "soft":
            limit = max(1, tone_channels * 2)
        else:
            limit = max(1, tone_channels * 2)
            if max_poly <= limit:
                limit = 0
        if limit:
            tone_events, density_dropped = _limit_density(
                tone_events, limit, args.density_bias, args.density_bass
            )
            frame_events = tone_events + noise_events
            frame_events.sort(key=lambda e: (e["start_frame"], e["channel"], e["note"]))
            if density_dropped:
                warnings.append(f"density thinning dropped {density_dropped} notes (mode={args.density_mode})")

    per_channel = defaultdict(list)
    for ev in frame_events:
        if ev["channel"] in channels:
            per_channel[ev["channel"]].append(ev)

    comment = "//" if args.c_array else ";"
    summary = _format_summary(events, stats, comment)
    auto_loop_used = False
    trace_entries: list[tuple[str, list[dict]]] = []
    summary += f"{comment} Quantize grid: {args.grid} ticks\n"
    if bend_shifted:
        summary += f"{comment} Pitch bend: shifted_notes={bend_shifted} max_shift={bend_max} semitone(s)\n"
    if bend_splits:
        summary += f"{comment} Pitch bend: split_events={bend_splits}\n"
    if cc_scaled:
        summary += f"{comment} CC7/11: scaled_events={cc_scaled} split_events={cc_splits}\n"
    summary += f"{comment} Channels used: {', '.join(str(c) for c in sorted(channels))}\n"
    if noise_events:
        summary += f"{comment} Noise channel: {noise_channel} (events={len(noise_events)})\n"
    if drum_dropped:
        summary += f"{comment} Drum map dropped: {drum_dropped}\n"
    summary += f"{comment} Base MIDI note: {args.base_midi} (index 0)\n"
    summary += f"{comment} Auto-transpose: {args.auto_transpose} (shift {transpose})\n"
    summary += f"{comment} Clamp: {args.clamp}\n"
    if emit_opcodes:
        summary += f"{comment} FX opcodes: enabled (instrument_map={args.instrument_map})\n"
    out_of_range_raw = _count_out_of_range_events(events, args.base_midi)
    if out_of_range_raw and not args.clamp:
        warnings.append(f"{out_of_range_raw} notes out of range (no clamp)")
    summary += (
        f"{comment} Tempo: first={tempo_first} us/beat, last={tempo_last} us/beat, "
        f"changes={len(segments)-1}, fps={args.fps}\n"
    )
    if len(segments) > 6:
        warnings.append(f"many tempo changes ({len(segments)-1})")
    if mid.ticks_per_beat % args.grid != 0:
        warnings.append("grid not aligned with ticks_per_beat (quantization may drift)")
    if bend_splits:
        warnings.append(
            "pitch bend changes split notes into segments (may increase density)"
        )
    if cc_splits:
        warnings.append(
            "CC7/CC11 changes split notes into segments (may increase density)"
        )
    if stats.get("cc_sustain_events", 0) and not args.use_sustain:
        warnings.append("CC64 sustain present but disabled (--no-sustain)")
    if (stats.get("cc_volume_events", 0) or stats.get("cc_expression_events", 0)) and not args.use_cc_volume:
        warnings.append("CC7/CC11 present but ignored (--use-cc-volume to apply)")
    if stats.get("program_change_events", 0) and not emit_opcodes:
        warnings.append("Program Change present but FX opcodes disabled (--instrument-map to enable)")

    if args.c_array:
        parts = [summary, _format_c_array("NOTE_TABLE", [b for pair in NOTE_TABLE for b in pair])]
    else:
        parts = [summary, _format_note_table("NOTE_TABLE")]
    dropped_mono = 0
    if args.poly:
        filtered = [ev for ev in frame_events if ev["channel"] in channels]
        total_events = len(filtered)
        max_poly = _max_polyphony(filtered)
        if max_poly > tone_channels:
            warnings.append(f"max polyphony {max_poly} exceeds voice count {tone_channels}")
        if not filtered and args.force_tone_streams:
            for idx in range(tone_channels):
                stream = [0]
                st = {
                    "dropped": 0,
                    "dropped_overlap": 0,
                    "out_of_range": 0,
                    "bytes": len(stream),
                    "loop_offset": 0,
                }
                parts.append(
                    f"{comment} CH{idx} stream: bytes={st['bytes']} kept=0 "
                    f"out_of_range=0 overlap_dropped=0\n"
                )
                parts.append(
                    f"{comment} CH{idx} duration: 0 frames (~0.000s) "
                    f"target=0 delta=0\n"
                )
                if args.c_array:
                    parts.append(_format_c_array(f"BGM_CH{idx}", stream))
                else:
                    parts.append(_format_stream(f"BGM_CH{idx}", stream))
            # Still emit noise if requested.
            if noise_enabled:
                n_stream, n_st = _build_noise_stream(noise_events, loop_start_frame)
                n_total = _stream_total_frames(n_stream)
                n_target = _max_end_frame(noise_events)
                parts.append(
                    f"{comment} CHN stream: bytes={n_st['bytes']} kept={len(noise_events)} "
                    f"overlap_dropped={n_st['dropped_overlap']}\n"
                )
                parts.append(
                    f"{comment} CHN duration: {n_total} frames (~{n_total/args.fps:.3f}s) "
                    f"target={n_target} delta={n_total - n_target}\n"
                )
                if loop_start_frame is not None:
                    parts.append(f"{comment} CHN loop_offset: {n_st['loop_offset']}\n")
                    if args.c_array:
                        parts.append(f"const unsigned short BGM_CHN_LOOP = {n_st['loop_offset']};\n")
                    else:
                        parts.append(f"BGM_CHN_LOOP EQU {n_st['loop_offset']}\n")
                if args.c_array:
                    parts.append(_format_c_array("BGM_CHN", n_stream))
                else:
                    parts.append(_format_stream("BGM_CHN", n_stream))
            output = "\n".join(parts)
            with open(output_asm, "w", encoding="ascii") as f:
                f.write(output)
            return 0
        if args.split_voices:
            voice_streams, poly_stats = _split_events_to_voices(
                filtered, tone_channels, args.preempt
            )
            if loop_start_frame is None and args.auto_loop_rest is not None:
                total_frames = _max_end_frame(filtered + (noise_events if noise_enabled else []))
                min_frame = int(total_frames * args.auto_loop_rest)
                rest_frame = _find_common_rest_frame(
                    voice_streams + ([noise_events] if noise_enabled else []),
                    total_frames,
                    min_frame,
                )
                if rest_frame is not None:
                    loop_start_frame = rest_frame
                    auto_loop_used = True
            parts.append(
                f"{comment} Poly voice split: voices={tone_channels} dropped={poly_stats['dropped']} "
                f"preempted={poly_stats['preempted']}\n"
            )
            for idx, voice_events in enumerate(voice_streams):
                trace_entries.append((f"CH{idx}", voice_events))
                if emit_opcodes:
                    fx_events = _build_fx_events_for_voice(
                        voice_events,
                        program_timelines,
                        default_program,
                        default_inst,
                        program_instruments,
                    )
                    if args.loop_reset_fx:
                        channel = voice_events[0]["channel"] if voice_events else channels[idx % len(channels)]
                        _add_loop_reset_fx(
                            fx_events,
                            loop_start_frame,
                            program_timelines,
                            default_program,
                            default_inst,
                            program_instruments,
                            channel,
                        )
                    stream, st = _build_stream_with_fx(
                        voice_events, args.base_midi, loop_start_frame, fx_events
                    )
                else:
                    stream, st = _build_stream(voice_events, args.base_midi, loop_start_frame)
                total_frames = _stream_total_frames(stream)
                target_frames = _max_end_frame(voice_events)
                kept = len(voice_events)
                parts.append(
                    f"{comment} CH{idx} stream: bytes={st['bytes']} kept={kept} "
                    f"out_of_range={st['out_of_range']} overlap_dropped={st['dropped_overlap']}\n"
                )
                parts.append(
                    f"{comment} CH{idx} duration: {total_frames} frames (~{total_frames/args.fps:.3f}s) "
                    f"target={target_frames} delta={total_frames - target_frames}\n"
                )
                if loop_start_frame is not None:
                    parts.append(f"{comment} CH{idx} loop_offset: {st['loop_offset']}\n")
                    if args.c_array:
                        parts.append(f"const unsigned short BGM_CH{idx}_LOOP = {st['loop_offset']};\n")
                    else:
                        parts.append(f"BGM_CH{idx}_LOOP EQU {st['loop_offset']}\n")
                if args.c_array:
                    parts.append(_format_c_array(f"BGM_CH{idx}", stream))
                else:
                    parts.append(_format_stream(f"BGM_CH{idx}", stream))
            if noise_enabled:
                trace_entries.append(("CHN", noise_events))
                if emit_opcodes:
                    n_fx = _build_fx_events_for_voice(
                        noise_events,
                        program_timelines,
                        default_program,
                        default_inst,
                        program_instruments,
                    )
                    if args.loop_reset_fx:
                        _add_loop_reset_fx(
                            n_fx,
                            loop_start_frame,
                            program_timelines,
                            default_program,
                            default_inst,
                            program_instruments,
                            noise_channel,
                        )
                    n_stream, n_st = _build_noise_stream_with_fx(
                        noise_events, loop_start_frame, n_fx
                    )
                else:
                    n_stream, n_st = _build_noise_stream(noise_events, loop_start_frame)
                n_total = _stream_total_frames(n_stream)
                n_target = _max_end_frame(noise_events)
                parts.append(
                    f"{comment} CHN stream: bytes={n_st['bytes']} kept={len(noise_events)} "
                    f"overlap_dropped={n_st['dropped_overlap']}\n"
                )
                parts.append(
                    f"{comment} CHN duration: {n_total} frames (~{n_total/args.fps:.3f}s) "
                    f"target={n_target} delta={n_total - n_target}\n"
                )
                if loop_start_frame is not None:
                    parts.append(f"{comment} CHN loop_offset: {n_st['loop_offset']}\n")
                    if args.c_array:
                        parts.append(f"const unsigned short BGM_CHN_LOOP = {n_st['loop_offset']};\n")
                    else:
                        parts.append(f"BGM_CHN_LOOP EQU {n_st['loop_offset']}\n")
                if args.c_array:
                    parts.append(_format_c_array("BGM_CHN", n_stream))
                else:
                    parts.append(_format_stream("BGM_CHN", n_stream))
            parts.append(
                f"{comment} Poly report: total_events={total_events} kept={total_events - poly_stats['dropped']} "
                f"dropped={poly_stats['dropped']} preempted={poly_stats['preempted']}\n"
            )
        else:
            if loop_start_frame is None and args.auto_loop_rest is not None:
                total_frames = _max_end_frame(filtered + (noise_events if noise_enabled else []))
                stream_lists = [per_channel[ch] for ch in sorted(per_channel.keys())]
                if noise_enabled:
                    stream_lists.append(noise_events)
                min_frame = int(total_frames * args.auto_loop_rest)
                rest_frame = _find_common_rest_frame(stream_lists, total_frames, min_frame)
                if rest_frame is not None:
                    loop_start_frame = rest_frame
                    auto_loop_used = True
            for idx, ch in enumerate(sorted(per_channel.keys())):
                voice_events = per_channel[ch]
                trace_entries.append((f"CH{idx}", voice_events))
                if emit_opcodes:
                    fx_events = _build_fx_events_for_voice(
                        voice_events,
                        program_timelines,
                        default_program,
                        default_inst,
                        program_instruments,
                    )
                    if args.loop_reset_fx:
                        _add_loop_reset_fx(
                            fx_events,
                            loop_start_frame,
                            program_timelines,
                            default_program,
                            default_inst,
                            program_instruments,
                            ch,
                        )
                    stream, st = _build_stream_with_fx(
                        voice_events, args.base_midi, loop_start_frame, fx_events
                    )
                else:
                    stream, st = _build_stream(voice_events, args.base_midi, loop_start_frame)
                total_frames = _stream_total_frames(stream)
                target_frames = _max_end_frame(voice_events)
                kept = len(voice_events) - st["dropped_overlap"]
                parts.append(
                    f"{comment} CH{ch} stream: bytes={st['bytes']} kept={kept} "
                    f"out_of_range={st['out_of_range']} overlap_dropped={st['dropped_overlap']}\n"
                )
                parts.append(
                    f"{comment} CH{ch} duration: {total_frames} frames (~{total_frames/args.fps:.3f}s) "
                    f"target={target_frames} delta={total_frames - target_frames}\n"
                )
                if loop_start_frame is not None:
                    parts.append(f"{comment} CH{ch} loop_offset: {st['loop_offset']}\n")
                    if args.c_array:
                        parts.append(f"const unsigned short BGM_CH{idx}_LOOP = {st['loop_offset']};\n")
                    else:
                        parts.append(f"BGM_CH{idx}_LOOP EQU {st['loop_offset']}\n")
                if args.c_array:
                    parts.append(_format_c_array(f"BGM_CH{idx}", stream))
                else:
                    parts.append(_format_stream(f"BGM_CH{idx}", stream))
            if args.force_tone_streams:
                for ch in range(tone_channels):
                    if ch in per_channel:
                        continue
                    stream = [0]
                    st = {
                        "dropped": 0,
                        "dropped_overlap": 0,
                        "out_of_range": 0,
                        "bytes": len(stream),
                        "loop_offset": 0,
                    }
                    parts.append(
                        f"{comment} CH{ch} stream: bytes={st['bytes']} kept=0 "
                        f"out_of_range=0 overlap_dropped=0\n"
                    )
                    parts.append(
                        f"{comment} CH{ch} duration: 0 frames (~0.000s) "
                        f"target=0 delta=0\n"
                    )
                    if args.c_array:
                        parts.append(_format_c_array(f"BGM_CH{ch}", stream))
                    else:
                        parts.append(_format_stream(f"BGM_CH{ch}", stream))
            if noise_enabled:
                trace_entries.append(("CHN", noise_events))
                if emit_opcodes:
                    n_fx = _build_fx_events_for_voice(
                        noise_events,
                        program_timelines,
                        default_program,
                        default_inst,
                        program_instruments,
                    )
                    if args.loop_reset_fx:
                        _add_loop_reset_fx(
                            n_fx,
                            loop_start_frame,
                            program_timelines,
                            default_program,
                            default_inst,
                            program_instruments,
                            noise_channel,
                        )
                    n_stream, n_st = _build_noise_stream_with_fx(
                        noise_events, loop_start_frame, n_fx
                    )
                else:
                    n_stream, n_st = _build_noise_stream(noise_events, loop_start_frame)
                n_total = _stream_total_frames(n_stream)
                n_target = _max_end_frame(noise_events)
                parts.append(
                    f"{comment} CHN stream: bytes={n_st['bytes']} kept={len(noise_events)} "
                    f"overlap_dropped={n_st['dropped_overlap']}\n"
                )
                parts.append(
                    f"{comment} CHN duration: {n_total} frames (~{n_total/args.fps:.3f}s) "
                    f"target={n_target} delta={n_total - n_target}\n"
                )
                if loop_start_frame is not None:
                    parts.append(f"{comment} CHN loop_offset: {n_st['loop_offset']}\n")
                    if args.c_array:
                        parts.append(f"const unsigned short BGM_CHN_LOOP = {n_st['loop_offset']};\n")
                    else:
                        parts.append(f"BGM_CHN_LOOP EQU {n_st['loop_offset']}\n")
                if args.c_array:
                    parts.append(_format_c_array("BGM_CHN", n_stream))
                else:
                    parts.append(_format_stream("BGM_CHN", n_stream))
    else:
        mono_events = _build_mono_events(
            [ev for ev in frame_events if ev["channel"] in channels]
        )
        total_events = len([ev for ev in frame_events if ev["channel"] in channels])
        dropped_mono = total_events - len(mono_events)
        if loop_start_frame is None and args.auto_loop_rest is not None:
            total_frames = _max_end_frame(mono_events)
            min_frame = int(total_frames * args.auto_loop_rest)
            rest_frame = _find_common_rest_frame([mono_events], total_frames, min_frame)
            if rest_frame is not None:
                loop_start_frame = rest_frame
                auto_loop_used = True
        trace_entries.append(("MONO", mono_events))
        if emit_opcodes:
            fx_events = _build_fx_events_for_voice(
                mono_events,
                program_timelines,
                default_program,
                default_inst,
                program_instruments,
            )
            if args.loop_reset_fx and mono_events:
                _add_loop_reset_fx(
                    fx_events,
                    loop_start_frame,
                    program_timelines,
                    default_program,
                    default_inst,
                    program_instruments,
                    mono_events[0]["channel"],
                )
            stream, st = _build_stream_with_fx(
                mono_events, args.base_midi, loop_start_frame, fx_events
            )
        else:
            stream, st = _build_stream(mono_events, args.base_midi, loop_start_frame)
        total_frames = _stream_total_frames(stream)
        target_frames = _max_end_frame(mono_events)
        parts.append(
            f"{comment} MONO stream: bytes={st['bytes']} kept={len(mono_events)} dropped={dropped_mono} "
            f"out_of_range={st['out_of_range']} overlap_dropped={st['dropped_overlap']}\n"
        )
        parts.append(
            f"{comment} MONO duration: {total_frames} frames (~{total_frames/args.fps:.3f}s) "
            f"target={target_frames} delta={total_frames - target_frames}\n"
        )
        if loop_start_frame is not None:
            parts.append(f"{comment} MONO loop_offset: {st['loop_offset']}\n")
            if args.c_array:
                parts.append(f"const unsigned short BGM_MONO_LOOP = {st['loop_offset']};\n")
            else:
                parts.append(f"BGM_MONO_LOOP EQU {st['loop_offset']}\n")
        if not args.c_array:
            parts.append(f"BGM_BASE_FPS EQU {args.fps}\n")
            parts.append(f"BGM_TOTAL_FRAMES EQU {total_frames}\n")
        if args.c_array:
            parts.append(f"const unsigned short BGM_BASE_FPS = {args.fps};\n")
            parts.append(f"const unsigned short BGM_TOTAL_FRAMES = {total_frames};\n")
            parts.append(_format_c_array("BGM_MONO", stream))
        else:
            parts.append(_format_stream("BGM_MONO", stream))
        if args.use_velocity:
            attn_stream = _build_attn_stream(
                mono_events, args.attn_min, args.attn_max
            )
            parts.append(
                f"{comment} MONO attn stream: min={args.attn_min} max={args.attn_max}\n"
            )
            if args.c_array:
                parts.append(_format_c_array("BGM_MONO_ATTN", attn_stream))
            else:
                parts.append(_format_stream("BGM_MONO_ATTN", attn_stream))

    if noise_events and not noise_enabled:
        warnings.append("noise events present but noise disabled (need --poly with >=4 voices)")
    if dropped_mono > 0 and not args.poly:
        warnings.append(f"mono drop count {dropped_mono} (dense overlaps)")

    if loop_start_frame is not None:
        parts[0] += f"{comment} Loop start frame: {loop_start_frame}\n"
        if auto_loop_used:
            parts[0] += f"{comment} Loop auto-rest: yes\n"

    if warnings:
        parts.insert(1, f"{comment} Warnings:\n" + "\n".join(f"{comment} - {w}" for w in warnings) + "\n")
        for w in warnings:
            print(f"Warning: {w}")

    output = "\n".join(parts)

    with open(output_asm, "w", encoding="ascii") as f:
        f.write(output)

    if args.trace_output:
        header_lines = [
            f"input={input_mid}",
            f"output={output_asm}",
            f"fps={args.fps}",
            f"grid={args.grid}",
            f"channels={args.channels}",
            f"noise_channel={noise_channel}",
            f"instrument_map={args.instrument_map or ''}",
            f"emit_opcodes={emit_opcodes}",
            f"auto_loop_rest={args.auto_loop_rest}",
            f"loop_reset_fx={args.loop_reset_fx}",
        ]
        _write_trace(
            args.trace_output,
            header_lines,
            trace_entries,
            program_timelines,
            default_program,
            default_inst,
            program_instruments,
            loop_start_frame,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

