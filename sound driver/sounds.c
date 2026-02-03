#include "ngpc.h"
#include "library.h"
#include "sounds.h"

/*
 * Minimal Z80 SFX driver (polling, multi-command buffer).
 * Shared RAM (Z80: 0x0003..0x0012, CPU: 0x7003..0x7012):
 *   0x7003 = count (CPU writes N, Z80 clears to 0 when done)
 *   0x7004 = buffer[0] (byte1)
 *   0x7005 = buffer[1] (byte2)
 *   0x7006 = buffer[2] (byte3)
 *   ... up to 5 commands (15 bytes total)
 */

static const u8 s_z80drv[] = {
    0xC3, 0x13, 0x00,           /* jp 0x0013              */
    0x00,                       /* count                  */
    0x00, 0x00, 0x00,           /* buf[0..2]              */
    0x00, 0x00, 0x00,           /* buf[3..5]              */
    0x00, 0x00, 0x00,           /* buf[6..8]              */
    0x00, 0x00, 0x00,           /* buf[9..11]             */
    0x00, 0x00, 0x00,           /* buf[12..14]            */
    /* 0x0013: */
    0xF3,                       /* di                     */
    0x31, 0x00, 0x10,           /* ld sp, 0x1000          */
    /* loop (0x0017): */
    0x3A, 0x03, 0x00,           /* ld a, (0x0003)         */
    0xB7,                       /* or a                   */
    0x28, 0xFA,                 /* jr z, loop (-6)        */
    0x47,                       /* ld b, a                */
    0x21, 0x04, 0x00,           /* ld hl, 0x0004          */
    /* cmd_loop (0x0021): */
    0x7E,                       /* ld a, (hl)             */
    0x32, 0x01, 0x40,           /* ld (0x4001), a         */
    0x32, 0x00, 0x40,           /* ld (0x4000), a         */
    0x23,                       /* inc hl                 */
    0x7E,                       /* ld a, (hl)             */
    0x32, 0x01, 0x40,           /* ld (0x4001), a         */
    0x32, 0x00, 0x40,           /* ld (0x4000), a         */
    0x23,                       /* inc hl                 */
    0x7E,                       /* ld a, (hl)             */
    0x32, 0x01, 0x40,           /* ld (0x4001), a         */
    0x32, 0x00, 0x40,           /* ld (0x4000), a         */
    0x23,                       /* inc hl                 */
    0x10, 0xE6,                 /* djnz cmd_loop (-26)    */
    0xAF,                       /* xor a                  */
    0x32, 0x03, 0x00,           /* ld (0x0003), a         */
    0x18, 0xD6                  /* jr loop (-42)          */
};

/* Shared RAM (main CPU side) */
#define SND_COUNT   (*(volatile u8 *)0x7003)
#define SND_BUF     ((volatile u8 *)0x7004)
#define SND_BUF_MAX 5

/* Duration timers (frames) */
static u8 s_toneTimer;
static u8 s_noiseTimer;
static u8 s_buf_count;

static void WaitBufferFree(void)
{
    u16 timeout = 4000;
    while (SND_COUNT && timeout) {
        timeout--;
    }
}

void Sfx_BufferBegin(void)
{
    s_buf_count = 0;
}

void Sfx_BufferPush(u8 b1, u8 b2, u8 b3)
{
    if (s_buf_count < SND_BUF_MAX) {
        u8 idx = (u8)(s_buf_count * 3);
        SND_BUF[idx + 0] = b1;
        SND_BUF[idx + 1] = b2;
        SND_BUF[idx + 2] = b3;
        s_buf_count++;
    }
}

void Sfx_BufferCommit(void)
{
    WaitBufferFree();
    SND_COUNT = s_buf_count;
    s_buf_count = 0;
}

static void PlayTone(u16 n, u8 attn)
{
    if (n == 0) {
        n = 1;
    }
    Sfx_BufferBegin();
    Sfx_BufferPush((u8)(0x80 | (n & 0x0F)),
                   (u8)((n >> 4) & 0x3F),
                   (u8)(0x90 | (attn & 0x0F)));
    Sfx_BufferCommit();
}

static void PlayNoise(u8 rate, u8 type, u8 attn)
{
    u8 b1 = (u8)(0xE0 | ((type & 0x01) << 2) | (rate & 0x03));
    u8 b2 = 0x9F; /* keep tone1 silent */
    u8 b3 = (u8)(0xF0 | (attn & 0x0F));
    Sfx_BufferBegin();
    Sfx_BufferPush(b1, b2, b3);
    Sfx_BufferCommit();
}

void Sfx_SendBytes(u8 b1, u8 b2, u8 b3)
{
    Sfx_BufferBegin();
    Sfx_BufferPush(b1, b2, b3);
    Sfx_BufferCommit();
}

static void SilenceTone(void)
{
    Sfx_BufferBegin();
    Sfx_BufferPush(0x9F, 0x9F, 0x9F);
    Sfx_BufferCommit();
}

static void SilenceNoise(void)
{
    Sfx_BufferBegin();
    Sfx_BufferPush(0xFF, 0xFF, 0xFF);
    Sfx_BufferCommit();
}

static void SilenceAll(void)
{
    Sfx_BufferBegin();
    Sfx_BufferPush(0x9F, 0x9F, 0x9F);
    Sfx_BufferPush(0xFF, 0xFF, 0xFF);
    Sfx_BufferCommit();
}

void Sounds_Init(void)
{
    u8 *ram;
    u16 i;

    SOUNDCPU_CTRL = 0xAAAA;

    ram = (u8 *)0x7000;
    for (i = 0; i < sizeof(s_z80drv); i++) {
        ram[i] = s_z80drv[i];
    }

    SOUNDCPU_CTRL = 0x5555;
    s_toneTimer = 0;
    s_noiseTimer = 0;
}

void Sfx_Update(void)
{
    if (s_toneTimer > 0) {
        s_toneTimer--;
        if (s_toneTimer == 0) {
            SilenceTone();
        }
    }
    if (s_noiseTimer > 0) {
        s_noiseTimer--;
        if (s_noiseTimer == 0) {
            SilenceNoise();
        }
    }
}

void Sfx_Play(u16 divider, u8 attn, u8 duration)
{
    PlayTone(divider, attn);
    s_toneTimer = duration;
}

void Sfx_SetTone(u16 divider, u8 attn)
{
    PlayTone(divider, attn);
}

void Sfx_PlayNoise(u8 rate, u8 type, u8 attn, u8 duration, u8 burst, u8 burst_dur)
{
    PlayNoise(rate, type, attn);
    s_noiseTimer = burst ? burst_dur : duration;
}

void Sfx_PlayToneNoise(
	u16 divider, u8 attn, u8 duration,
	u8 rate, u8 type, u8 n_attn, u8 n_duration,
	u8 burst, u8 burst_dur)
{
	u8 tone_b1;
	u8 tone_b2;
	u8 tone_b3;
	u8 noise_b1;
	u8 noise_b2;
	u8 noise_b3;

	if (divider == 0) {
		divider = 1;
	}
	tone_b1 = (u8)(0x80 | (divider & 0x0F));
	tone_b2 = (u8)((divider >> 4) & 0x3F);
	tone_b3 = (u8)(0x90 | (attn & 0x0F));

	noise_b1 = (u8)(0xE0 | ((type & 0x01) << 2) | (rate & 0x03));
	noise_b2 = 0x9F;
	noise_b3 = (u8)(0xF0 | (n_attn & 0x0F));

	Sfx_BufferBegin();
	Sfx_BufferPush(tone_b1, tone_b2, tone_b3);
	Sfx_BufferPush(noise_b1, noise_b2, noise_b3);
	Sfx_BufferCommit();

	s_toneTimer = duration;
	s_noiseTimer = burst ? burst_dur : n_duration;
}

void Sfx_SetNoise(u8 rate, u8 type, u8 attn)
{
    PlayNoise(rate, type, attn);
}

void Sfx_Stop(void)
{
    s_toneTimer = 0;
    s_noiseTimer = 0;
    SilenceAll();
}
