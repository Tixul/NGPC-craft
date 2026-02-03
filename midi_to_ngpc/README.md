# midi_to_ngpc

Minimal MIDI → NGPC (T6W28) converter with a small, practical runtime format.  
Targets custom polling Z80 drivers and very light CPU-side playback.

## Highlights

- MIDI Type 0/1 parsing (`mido`)
- Quantization and tempo-aware frame timing (`--fps`, default 60)
- Mono stream export or poly export (up to 3 tone + optional noise)
- Optional noise stream (MIDI channel 9 by default)
- Optional attenuation stream from velocity
- Optional FX opcodes (envelopes/sweep/vibrato) via instrument map
- ASM or C array output
- Simple Tkinter GUI

## NGPC Audio Constraints (Context)

- T6W28: **3 tone + 1 noise**
- 4 KB shared RAM window (`0x7000..0x7FFF` on TLCS-900 side)
- Mono output

## Quick Start (CLI)

```bash
python midi_to_ngpc.py input.mid output.asm
```

Poly + FX (instrument map):
```bash
python midi_to_ngpc.py input.mid output.asm --poly --channels 3 --instrument-map instrument_map.json --opcodes
```

Windows helper:
```bat
convert.bat input.mid output.asm
```

## Input Expectations

Supported:
- Standard MIDI File type 0/1
- `note_on` / `note_off`
- `set_tempo` (tempo → frame timing)
- Pitch bend (optional, splits notes at bend changes)
- Program Change (when `--instrument-map` + `--opcodes` are enabled)

Ignored (by default):
- Most CCs, aftertouch, SysEx (unless enabled options)

Recommended:
- Clean, quantized MIDI
- Limit to 3 tone tracks + 1 drums/noise track

## Output (Mono)

- `NOTE_TABLE`: 51 entries (A2..B6), 2 bytes each
- `BGM_MONO`: `(note_idx, duration_frames)` pairs
  - `note_idx = 1..51` → `NOTE_TABLE`
  - `note_idx = 0xFF` → rest
  - `note_idx = 0x00` → end
- Optional `BGM_MONO_LOOP` (byte offset)
- Metadata: `BGM_BASE_FPS`, `BGM_TOTAL_FRAMES`

See `FORMAT.md` for details.

## Output (Poly + Noise)

- `BGM_CH0` → Tone1
- `BGM_CH1` → Tone2
- `BGM_CH2` → Tone3
- `BGM_CHN` → Noise control stream
- Optional `BGM_CHx_LOOP` per stream

## FX Opcodes (Optional)

Enable with `--instrument-map` + `--opcodes`.  
FX opcodes are injected before notes so the runtime can apply envelopes/sweep/vibrato.
See `FORMAT.md`.

## Instrument Maps

Built-in preset maps:
- `instrument_maps/instrument_map_arcade.json`
- `instrument_maps/instrument_map_action.json`
- `instrument_maps/instrument_map_adventure.json`
- `instrument_maps/instrument_map_rpg.json`
- `instrument_maps/instrument_map_punk.json`
- `instrument_maps/instrument_map_clean.json`
- `instrument_maps/instrument_map_chip.json`
- `instrument_maps/instrument_map_chiptune.json`
- `instrument_maps/instrument_map_pop.json`
- `instrument_maps/instrument_map_rock.json`
- `instrument_maps/instrument_map_hiphop.json`
- `instrument_maps/instrument_map_edm.json`
- `instrument_maps/instrument_map_dnb.json`
- `instrument_maps/instrument_map_lofi.json`

Typical Program Change mapping (0-based):
- `80` lead
- `33` bass
- `1` harmony/arp
- `9` drums (noise env)

## CLI Options (Core)

- `--grid <ticks>` quantize grid (default `48`)
- `--fps <n>` target playback FPS (default `60`)
- `--base-midi <note>` base note index (default `45`, A2)
- `--poly` export per-channel streams
- `--channels <n>` number of tone channels (1..3)
- `--split-voices` / `--no-split-voices`
- `--preempt` / `--no-preempt`
- `--use-velocity` export attenuation stream
- `--noise-channel <n>` MIDI channel used as noise (default `9`)
- `--drum-mode <off|snk>`
- `--instrument-map <file>`
- `--opcodes` / `--no-opcodes`
- `--density-mode <auto|off|soft|hard>`
- `--density-bias <n>`
- `--density-bass <n>`
- `--loop-start-frame <n>`
- `--loop-start-tick <n>`
- `--auto-loop-rest <ratio>`
- `--loop-reset-fx`
- `--trace-output <file>`
- `--pitchbend-range <n>` (default `2`)
- `--no-pitchbend`
- `--use-cc-volume`
- `--no-sustain`
- `--force-noise-stream`
- `--force-tone-streams`
- `--c-array`
- `--profile fidelity`

## GUI

Run:
```bash
python gui.py
```

Includes:
- input/output browse
- grid, fps
- poly + channels
- split voices + preempt
- pitch bend toggle + range
- CC7/CC11 volume toggle
- sustain toggle
- drum mode
- density controls
- noise channel
- C array toggle
- velocity/attenuation toggle
- instrument map + FX opcodes
- preset picker
- loop helpers + trace output
- dark mode + tooltip language (EN/FR)
- profile: Fidelity

## Integration (Minimal Runtime)

1. Load/start Z80 driver  
2. Parse `BGM_*` stream  
3. For each note: lookup `NOTE_TABLE`, send `(b1,b2,b3)` to shared buffer

Tone1 note write:
```c
u8 idx = note_idx - 1; // 0x00 is end marker
b1 = 0x80 | NOTE_TABLE[idx * 2 + 0];
b2 = NOTE_TABLE[idx * 2 + 1];
b3 = 0x90 | (attn & 0x0F);
```

## Files

- `midi_to_ngpc.py` converter
- `gui.py` Tkinter UI
- `convert.bat` Windows helper
- `FORMAT.md` stream format
- `runtime_example.c` CPU playback stub
- `DESIGN.md` design notes
- `instrument_maps/` preset maps
- `requirements.txt` (`mido`)

## Troubleshooting

- **C output build errors**  
  Use `--c-array` to avoid ASM-style comments.

- **Missing channel streams**  
  Use `--force-tone-streams` / `--force-noise-stream` or `--profile fidelity`.

- **Noise rhythm differs**  
  Noise is monophonic. Simplify overlapping hits.

- **Tempo feels wrong in-game**  
  Runtime must tick on VBlank cadence (frame-accurate).

