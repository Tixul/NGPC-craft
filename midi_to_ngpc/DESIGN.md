# DESIGN

## Constraints
- NGPC sound: 3 tone + 1 noise (T6W28)
- Target: minimal ROM and Z80 RAM usage

## Draft event format (compact)
- 1 byte: NNNN DDDD
  - N: note index (0..15)
  - D: duration (1..15 ticks)
- Extended form for larger values:
  - 0xF0 + next byte (note index)
  - 0xF1 + next byte (duration)
  - 0x00 = end

## Note table
- Use precomputed T6W28 table (note -> byte1/byte2)
- Example source: 03_HOMEBREW/Columns/sound.asm

## Assembly output
- NOTE_TABLE: .db pairs
- BGM_xx: event stream terminated by 0x00
- Optional: pattern + sequence in v2

