# Integration Quickstart (Clean Driver)

Goal: integrate the driver into a new game without touching driver sources.

1) Add driver files
- Add `sounds.c` and `sounds.h` to your project.

2) Provide game-specific SFX mapping
- Add `sounds_game_sfx_template.c` to your project (rename if you want).
- In your build defines or a common header, add:
  `#define SFX_PLAY_EXTERNAL 1`
- Implement `Sfx_Play(u8 id)` in that file.

3) Initialize
- Call `Sounds_Init()` once at startup.

4) Update per frame
- Call `Sfx_Update()` once per frame (VBlank).
- Call `Bgm_Update()` once per frame (VBlank).
- Or just call `Sounds_Update()` once per frame.

5) Play SFX/BGM
- SFX: call `Sfx_PlayToneEx`, `Sfx_PlayNoiseEx`, or your `Sfx_Play` mapping.
- BGM: call `Bgm_Start` / `Bgm_StartLoop` and feed a stream.

6) Provide music data
- Include `NOTE_TABLE` and your BGM stream arrays (from `midi_to_ngpc` output).

Notes
- `Sfx_Play` in the driver remains a no-op unless you define `SFX_PLAY_EXTERNAL`.
- Prefer `Sfx_PlayPresetTable` for data-driven SFX banks.
- Instruments/macros/curves live in `sounds.c` (see `BGM_INST(...)` and tables).
- Optional slim build: set `SOUNDS_ENABLE_MACROS`, `SOUNDS_ENABLE_ENV_CURVES`,
  `SOUNDS_ENABLE_PITCH_CURVES`, or `SOUNDS_ENABLE_EXAMPLE_PRESETS` to 0.
