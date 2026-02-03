# FORMAT

## Data layout (CPU-side, mono)

- NOTE_TABLE: 51 entries (A2..B6), each 2 bytes (byte1, byte2)
- BGM_MONO stream: pairs of bytes (note_idx, duration), terminated by 0x00
- BGM_MONO_ATTN stream (optional): pairs of bytes (attn, duration), terminated by 0xFF

Encoding:
- note_idx: 1..51, index into NOTE_TABLE (0x00 reserved as end marker)
- duration: number of ticks (grid units), 1..255
- 0xFF note_idx means REST for duration ticks
- 0x00 terminator ends the stream

Optional loop point:
- Export may include `BGM_*_LOOP` as a byte offset into the stream.
- Runtime can jump to `stream + LOOP_OFFSET` when `0x00` is reached.
- attn: 0..15 (0 = loudest)
- attn stream terminator = 0xFF (since 0 is valid)

## Runtime expectations

The runtime (main CPU) should:
- Load NOTE_TABLE into ROM (ASM include)
- For each event:
  - If note_idx == 0xFF: wait duration ticks
  - Else: look up NOTE_TABLE[note_idx] => (b1, b2)
          send (b1, b2, attn) to Z80 driver buffer
          wait duration ticks
- Attenuation is a constant for now (e.g., 0x02)
- Z80 driver expects 3 bytes per command (b1,b2,b3)

## Data layout (poly + noise, optional)

- `BGM_CH0` -> Tone1
- `BGM_CH1` -> Tone2
- `BGM_CH2` -> Tone3
- `BGM_CHN` -> Noise control stream
  - note_idx 1..8 mapped to noise control register (0xE0 | (note_idx-1))
  - duration is in frames, same as tone streams

## FX opcodes (optional, BGM streams)

These opcodes allow lightweight envelopes/vibrato/sweep in the BGM driver.
They do not advance time (no duration).

- `0xF0 <attn>`: SET_ATTN (0..15)
- `0xF1 <step> <speed>`: SET_ENV (step 0..4, speed 1..10; step 0 disables)
- `0xF2 <depth> <speed> <delay>`: SET_VIB (depth 0..63, speed 1..30, delay 0..255; depth 0 disables)
- `0xF3 <end_lo> <end_hi> <step> <speed>`: SET_SWEEP
  - end: divider 1..1023 (little endian)
  - step: signed (-127..127); step 0 disables
  - speed: 1..30 (frames per step)
- `0xF4 <id>`: SET_INST (reserved/no-op for now)

Notes:
- OpCodes are inserted before notes (typically at note boundaries).
- Rest (`0xFF`) and End (`0x00`) remain unchanged.

