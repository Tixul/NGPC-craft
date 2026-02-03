#ifndef SOUNDS_H
#define SOUNDS_H

#include "ngpc.h"

void Sounds_Init(void);
void Sfx_Update(void);
void Sfx_Play(u16 divider, u8 attn, u8 duration);
void Sfx_SetTone(u16 divider, u8 attn);
void Sfx_PlayNoise(u8 rate, u8 type, u8 attn, u8 duration, u8 burst, u8 burst_dur);
void Sfx_SetNoise(u8 rate, u8 type, u8 attn);
void Sfx_PlayToneNoise(
	u16 divider, u8 attn, u8 duration,
	u8 rate, u8 type, u8 n_attn, u8 n_duration,
	u8 burst, u8 burst_dur);
void Sfx_SendBytes(u8 b1, u8 b2, u8 b3);
void Sfx_BufferBegin(void);
void Sfx_BufferPush(u8 b1, u8 b2, u8 b3);
void Sfx_BufferCommit(void);
void Sfx_Stop(void);

#endif
