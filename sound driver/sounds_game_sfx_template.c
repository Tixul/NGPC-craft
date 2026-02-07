#include "sounds.h"

/*
 * Game-specific SFX mapping template.
 * Keep the driver clean; implement your own mapping here.
 *
 * How to use:
 * - Compile this file in your game project.
 * - Add `#define SFX_PLAY_EXTERNAL 1` in a global config or compiler defines.
 * - Replace the example logic with your own.
 */

/* Example data-driven table (replace with your own presets). */
/*
static const SfxPreset kSfxTable[] = {
    { SFX_PRESET_TONE,  { .tone  = {0, 240, 2, 6, 280, 2, 1, 0, 1, 1, 2} } },
    { SFX_PRESET_NOISE, { .noise = {1, 1, 6, 8, 0, 1, 0, 1, 2} } },
};
*/

void Sfx_Play(u8 id)
{
    /* Example: table-driven */
    /* Sfx_PlayPresetTable(kSfxTable, (u8)(sizeof(kSfxTable) / sizeof(kSfxTable[0])), id); */

    /* Example: manual mapping */
    /*
    switch (id) {
    case 0:
        Sfx_PlayToneEx(0, 240, 2, 6, 280, 2, 1, 0, 1, 1, 2, 2);
        break;
    case 1:
        Sfx_PlayNoiseEx(1, 1, 6, 8, 0, 1, 0, 1, 2);
        break;
    default:
        break;
    }
    */
    (void)id;
}
