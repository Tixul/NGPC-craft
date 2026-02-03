# Custom NGPC SFX Driver (clean copy)

Source: `04_MY_PROJECTS/ngpc_sfx_tool`

Files:
- `sounds.c`
- `sounds.h`

Notes:
- Z80 driver is embedded as `s_z80drv[]` in `sounds.c`.
- Multi-command buffer (Tone + Noise same frame).
- API: `Sounds_Init`, `Sfx_Update`, `Sfx_Play`, `Sfx_PlayNoise`, `Sfx_PlayToneNoise`, `Sfx_Stop`, etc.

Inspiration / crédits:
- `vgmlib-ngpc` — by `winteriscomingpinball` — repo: `https://github.com/winteriscomingpinball/vgmlib-ngpc`
