(function () {
  var ns = $.namespace('pskl.controller.settings.exportimage');

  ns.MiscExportController = function (piskelController) {
    this.piskelController = piskelController;
  };

  pskl.utils.inherit(ns.MiscExportController, pskl.controller.settings.AbstractSettingController);

  ns.MiscExportController.prototype.init = function () {
    var cDownloadButton = document.querySelector('.c-download-button');
    this.addEventListener(cDownloadButton, 'click', this.onDownloadCFileClick_);

    var profileEl = document.querySelector('.ngpc-profile');
    var maxLayersEl = document.querySelector('.ngpc-max-layers');
    var maxPalsEl = document.querySelector('.ngpc-max-palettes');
    if (profileEl && maxLayersEl && maxPalsEl) {
      this.addEventListener(profileEl, 'change', function () {
        if (profileEl.value === 'bg') {
          maxLayersEl.value = 6;
          maxPalsEl.value = 32;
        } else {
          maxLayersEl.value = 3;
          maxPalsEl.value = 16;
        }
      });
    }
  };

  // =========================
  // NGPC EXPORT (KxGE style)
  // - 8x8 tiles (characters)
  // - 2bpp (4 color codes: 0..3), index 0 = transparent/clear
  // - palette entries RGB444 packed in uint16_t: 0x0BGR (upper bits unused)
  // - Automatic per-tile multi-layer split:
  //    each tile is split into up to MAX_LAYERS layers, each layer using <= 3 opaque colors + transparent.
  //    Reassembling layers (draw layer0 then layer1 then layer2 at same positions) gives identical final image.
  // =========================
  ns.MiscExportController.prototype.onDownloadCFileClick_ = function (evt) {
    var nameRaw = this.getPiskelName_();
    var cName = nameRaw.replace(/\s+/g, '_');
    var fileName = nameRaw + '_ngpc_layers.c';

    var width = this.piskelController.getWidth();
    var height = this.piskelController.getHeight();
    var frameCount = this.piskelController.getFrameCount();

    var MAX_LAYERS = 3;      // 2 -> up to 6 colors, 3 -> up to 9 colors, etc.
    var MAX_PALS_PER_LAYER = 16; // practical for sprites (16 palettes)

    var profileEl = document.querySelector('.ngpc-profile');
    var maxLayersEl = document.querySelector('.ngpc-max-layers');
    var maxPalsEl = document.querySelector('.ngpc-max-palettes');

    if (profileEl && profileEl.value === 'bg') {
      MAX_LAYERS = 6;
      MAX_PALS_PER_LAYER = 32;
    }
    if (maxLayersEl) {
      var v = parseInt(maxLayersEl.value, 10);
      if (!isNaN(v)) {
        if (v < 1) v = 1;
        if (v > 8) v = 8;
        MAX_LAYERS = v;
      }
    }
    if (maxPalsEl) {
      var p = parseInt(maxPalsEl.value, 10);
      if (!isNaN(p)) {
        if (p < 1) p = 1;
        if (p > 64) p = 64;
        MAX_PALS_PER_LAYER = p;
      }
    }

    if ((width % 8) !== 0 || (height % 8) !== 0) {
      window.alert(
        'NGPC export requires WIDTH and HEIGHT to be multiples of 8.\n' +
        'Current: ' + width + 'x' + height
      );
      return;
    }

    var tilesX = width / 8;
    var tilesY = height / 8;
    var tilesPerFrame = tilesX * tilesY;
    var bytesPerTile = 16;

    // Pass 1: analyze ALL frames & tiles -> decide how many layers are needed per tile (<= MAX_LAYERS)
    // and precompute per-layer palette assignment per tile per frame.
    var plan = this.buildLayeredPlan_(width, height, frameCount, tilesX, tilesY, MAX_LAYERS);
    if (!plan.ok) {
      window.alert(plan.error);
      return;
    }

    // Global needed layer count is max across all tiles/frames (<= MAX_LAYERS).
    var layerCount = plan.layerCount;

    // Pass 2: build per-layer palette banks (<= 16) and encode tiles.
    // Output shapes:
    // palettes_rgb444[layer][palCount][4]
    // tile_pal_id[layer][frame][tile] -> 0..palCount-1
    // tiles[layer][frame][tile][16]
    //
    // Tile order is fixed: tileId = ty*tilesX + tx (left->right, top->bottom).
    //
    // IMPORTANT: For sprites, you can map each tile to one hardware sprite (8x8) at (tx*8, ty*8).
    // For 16x16 sprite: 4 sprites. For multi-layer: draw all layer sprites with same positions.
    var perLayerPalettes = [];
    var perLayerPalIdMap = [];  // [layer][frame][tile] = palId
    var perLayerTiles = [];     // [layer][frame][tile] = [16 bytes]

    for (var l = 0; l < layerCount; l++) {
      perLayerPalettes[l] = [];            // array of palettes, each palette is [4 uint16 rgb444]
      perLayerPalIdMap[l] = new Array(frameCount);
      perLayerTiles[l] = new Array(frameCount);

      for (var fi = 0; fi < frameCount; fi++) {
        perLayerPalIdMap[l][fi] = new Array(tilesPerFrame);
        perLayerTiles[l][fi] = new Array(tilesPerFrame);

        var render = this.piskelController.renderFrameAt(fi, true);
        var ctx = render.getContext('2d');
        var imgd = ctx.getImageData(0, 0, width, height);
        var pix = imgd.data;

        for (var ty = 0; ty < tilesY; ty++) {
          for (var tx = 0; tx < tilesX; tx++) {
            var tileId = ty * tilesX + tx;

            // Get this tile's color-group for this layer (set of up to 3 opaque RGBA keys)
            var group = plan.groups[l][fi][tileId]; // array of RGBA keys (opaque), length 0..3

            // Build palette for this layer/tile: [transparent, c1, c2, c3] => RGB444
            // If group shorter than 3, remaining entries are 0.
            var palRgb444 = this.buildTilePaletteRgb444_(group);

            // Find or add palette in this layer bank (dedupe)
            var palId = this.findOrAddPalette_(perLayerPalettes[l], palRgb444, MAX_PALS_PER_LAYER);
            if (palId < 0) {
              window.alert(
                'Too many distinct palettes in layer ' + l + ' (>' + MAX_PALS_PER_LAYER + ').\n' +
                'Tip: reuse colors/palettes more, or export smaller assets.'
              );
              return;
            }

            perLayerPalIdMap[l][fi][tileId] = palId;

            // Encode tile 2bpp:
            // pixels not in this layer's group become transparent (index 0),
            // pixels in group map to indices 1..3 based on their position in group[].
            var tileBytes = this.encodeNgpcTile2bppLayered_(pix, width, tx * 8, ty * 8, group);
            perLayerTiles[l][fi][tileId] = tileBytes;
          }
        }
      }
    }

    // C output
    var out = '';
    out += '#include <stdint.h>\n\n';
    out += '/* NGPC layered 2bpp export from Piskel: "' + nameRaw + '" */\n';
    out += '/*\n';
    out += '  - Image is split per 8x8 tile into up to ' + MAX_LAYERS + ' layers.\n';
    out += '  - Each layer uses 2bpp (4 codes): 0=transparent, 1..3=opaque colors.\n';
    out += '  - Reassemble by drawing all layers in order (0..LAYER_COUNT-1) at same tile positions.\n';
    out += '  - Palettes are RGB444 packed in uint16_t: 0x0BGR.\n';
    out += '*/\n\n';

    out += '#define ' + cName.toUpperCase() + '_FRAME_COUNT ' + frameCount + '\n';
    out += '#define ' + cName.toUpperCase() + '_WIDTH ' + width + '\n';
    out += '#define ' + cName.toUpperCase() + '_HEIGHT ' + height + '\n';
    out += '#define ' + cName.toUpperCase() + '_TILES_X ' + tilesX + '\n';
    out += '#define ' + cName.toUpperCase() + '_TILES_Y ' + tilesY + '\n';
    out += '#define ' + cName.toUpperCase() + '_TILES_PER_FRAME ' + tilesPerFrame + '\n';
    out += '#define ' + cName.toUpperCase() + '_BYTES_PER_TILE ' + bytesPerTile + '\n';
    out += '#define ' + cName.toUpperCase() + '_LAYER_COUNT ' + layerCount + '\n\n';

    // Palette counts per layer
    out += 'static const uint8_t ' + cName.toLowerCase() + '_pal_count[' + layerCount + '] = {\n  ';
    for (var l2 = 0; l2 < layerCount; l2++) {
      out += (perLayerPalettes[l2].length & 0xFF);
      out += (l2 !== layerCount - 1) ? ', ' : '\n';
    }
    out += '};\n\n';

    // Palettes per layer: [layer][palCount][4]
    out += 'static const uint16_t ' + cName.toLowerCase() + '_pal_rgb444[' + layerCount + '][' + MAX_PALS_PER_LAYER + '][4] = {\n';
    for (var l3 = 0; l3 < layerCount; l3++) {
      out += '  {\n';
      for (var p = 0; p < MAX_PALS_PER_LAYER; p++) {
        var pal = (p < perLayerPalettes[l3].length) ? perLayerPalettes[l3][p] : [0,0,0,0];
        out += '    { ' + this.hex16_(pal[0]) + ', ' + this.hex16_(pal[1]) + ', ' + this.hex16_(pal[2]) + ', ' + this.hex16_(pal[3]) + ' }';
        out += (p !== MAX_PALS_PER_LAYER - 1) ? ',' : '';
        out += '\n';
      }
      out += (l3 !== layerCount - 1) ? '  },\n' : '  }\n';
    }
    out += '};\n\n';

    // Palette id map: [layer][frame][tile]
    out += 'static const uint8_t ' + cName.toLowerCase() + '_tile_pal[' + layerCount + '][' + frameCount + '][' + tilesPerFrame + '] = {\n';
    for (var l4 = 0; l4 < layerCount; l4++) {
      out += '  {\n';
      for (var fi2 = 0; fi2 < frameCount; fi2++) {
        out += '    { ';
        for (var t = 0; t < tilesPerFrame; t++) {
          out += (perLayerPalIdMap[l4][fi2][t] & 0xFF);
          out += (t !== tilesPerFrame - 1) ? ', ' : ' ';
        }
        out += '}';
        out += (fi2 !== frameCount - 1) ? ',\n' : '\n';
      }
      out += (l4 !== layerCount - 1) ? '  },\n' : '  }\n';
    }
    out += '};\n\n';

    // Tiles bytes: [layer][frame][tile][16]
    out += 'static const uint8_t ' + cName.toLowerCase() + '_tiles[' + layerCount + '][' + frameCount + '][' + tilesPerFrame + '][' + bytesPerTile + '] = {\n';
    for (var l5 = 0; l5 < layerCount; l5++) {
      out += '  {\n';
      for (var fi3 = 0; fi3 < frameCount; fi3++) {
        out += '    {\n';
        for (var t2 = 0; t2 < tilesPerFrame; t2++) {
          var tb = perLayerTiles[l5][fi3][t2];
          out += '      { ';
          for (var b = 0; b < bytesPerTile; b++) {
            out += this.hex8_(tb[b]);
            out += (b !== bytesPerTile - 1) ? ', ' : ' ';
          }
          out += '}';
          out += (t2 !== tilesPerFrame - 1) ? ',\n' : '\n';
        }
        out += (fi3 !== frameCount - 1) ? '    },\n' : '    }\n';
      }
      out += (l5 !== layerCount - 1) ? '  },\n' : '  }\n';
    }
    out += '};\n\n';

    // Optional: tile positions in 8px units (useful to spawn sprites quickly)
    out += 'static const int8_t ' + cName.toLowerCase() + '_tile_pos[' + tilesPerFrame + '][2] = {\n';
    for (var ty2 = 0; ty2 < tilesY; ty2++) {
      for (var tx2 = 0; tx2 < tilesX; tx2++) {
        var id = ty2 * tilesX + tx2;
        out += '  { ' + (tx2 * 8) + ', ' + (ty2 * 8) + ' }';
        out += (id !== tilesPerFrame - 1) ? ',\n' : '\n';
      }
    }
    out += '};\n';

    pskl.utils.BlobUtils.stringToBlob(out, function (blob) {
      pskl.utils.FileUtils.downloadAsFile(blob, fileName);
    }.bind(this), 'application/text');
  };

  ns.MiscExportController.prototype.getPiskelName_ = function () {
    return this.piskelController.getPiskel().getDescriptor().name;
  };

  // ---------- Deterministic grouping plan (per tile, per frame, per layer) ----------
  // groups[layer][frame][tileId] = array of RGBA keys (opaque), max 3 keys.
  // Any pixel whose RGBA key is not in the group becomes transparent in that layer.
  ns.MiscExportController.prototype.buildLayeredPlan_ = function (width, height, frameCount, tilesX, tilesY, maxLayers) {
    var tilesPerFrame = tilesX * tilesY;

    // Initialize groups structure up to maxLayers, we'll shrink later.
    var groups = new Array(maxLayers);
    for (var l = 0; l < maxLayers; l++) {
      groups[l] = new Array(frameCount);
      for (var fi = 0; fi < frameCount; fi++) {
        groups[l][fi] = new Array(tilesPerFrame);
        for (var t = 0; t < tilesPerFrame; t++) {
          groups[l][fi][t] = []; // will fill with up to 3 keys
        }
      }
    }

    var neededLayers = 1;

    for (var fi2 = 0; fi2 < frameCount; fi2++) {
      var render = this.piskelController.renderFrameAt(fi2, true);
      var ctx = render.getContext('2d');
      var imgd = ctx.getImageData(0, 0, width, height);
      var pix = imgd.data;

      for (var ty = 0; ty < tilesY; ty++) {
        for (var tx = 0; tx < tilesX; tx++) {
          var tileId = ty * tilesX + tx;

          // Collect opaque unique colors in this tile
          var set = {};
          var list = [];
          for (var y = 0; y < 8; y++) {
            for (var x = 0; x < 8; x++) {
              var ix = ((ty * 8 + y) * width + (tx * 8 + x)) * 4;
              var a = pix[ix + 3];
              if (a === 0) continue;
              var key = this.rgbaKey_(pix[ix], pix[ix + 1], pix[ix + 2], a);
              if (!set[key]) { set[key] = true; list.push(key); }
            }
          }

          // Deterministic order: sort keys by numeric RGBA
          list.sort(this.rgbaKeySort_);

          // Split into chunks of 3
          var chunks = Math.ceil(list.length / 3);
          if (chunks > maxLayers) {
            return {
              ok: false,
              error:
                'Tile at (tx=' + tx + ', ty=' + ty + ') in frame ' + fi2 + ' uses ' + list.length +
                ' opaque colors.\n' +
                'With maxLayers=' + maxLayers + ', max opaque colors per tile is ' + (maxLayers * 3) + '.\n' +
                'Reduce colors or increase MAX_LAYERS in exporter.'
            };
          }

          if (chunks > neededLayers) neededLayers = chunks;

          // Fill groups for each layer for this tile/frame
          for (var l = 0; l < maxLayers; l++) {
            groups[l][fi2][tileId] = [];
          }
          for (var c = 0; c < chunks; c++) {
            var start = c * 3;
            groups[c][fi2][tileId] = list.slice(start, start + 3); // 0..3 keys
          }
          // remaining layers stay empty => fully transparent tile for that layer
        }
      }
    }

    // Shrink groups to neededLayers
    groups.length = neededLayers;

    return {
      ok: true,
      layerCount: neededLayers,
      groups: groups
    };
  };

  // ---------- Tile palette / palette bank ----------
  // Build palette [4] RGB444: [transparent=0, group[0], group[1], group[2]] (missing -> 0)
  ns.MiscExportController.prototype.buildTilePaletteRgb444_ = function (groupKeys) {
    var pal = [0x0000, 0x0000, 0x0000, 0x0000];
    for (var i = 0; i < 3; i++) {
      if (i < groupKeys.length) {
        var parts = groupKeys[i].split(',');
        var r = parseInt(parts[0], 10);
        var g = parseInt(parts[1], 10);
        var b = parseInt(parts[2], 10);
        pal[i + 1] = this.rgbToRgb444_(r, g, b);
      }
    }
    return pal;
  };

  // Deduplicate palettes in a bank; returns palette id or -1 if over limit
  ns.MiscExportController.prototype.findOrAddPalette_ = function (bank, pal4, maxCount) {
    // linear search (banks are small: <=16)
    for (var i = 0; i < bank.length; i++) {
      var p = bank[i];
      if (p[0] === pal4[0] && p[1] === pal4[1] && p[2] === pal4[2] && p[3] === pal4[3]) {
        return i;
      }
    }
    if (bank.length >= maxCount) return -1;
    bank.push(pal4);
    return bank.length - 1;
  };

  // ---------- Encode tile 2bpp with layer masking ----------
  // groupKeys defines which opaque colors are kept in this layer.
  // Mapping:
  //  - transparent (a==0) => index 0
  //  - if pixel opaque and its key is groupKeys[k] => index k+1
  //  - else => index 0 (masked out for other layers)
  //
  // Bit packing (per NGPC tile docs):
  //  - each row = 2 bytes
  //  - each byte packs 4 pixels, right->left, with 2 bits per pixel:
  //      pixel0 (rightmost of the group) -> bits 0..1
  //      next -> bits 2..3, then 4..5, then 6..7
  ns.MiscExportController.prototype.encodeNgpcTile2bppLayered_ = function (pix, imgW, x0, y0, groupKeys) {
    var out = new Array(16);
    var outPos = 0;

    // Build small map key->index(1..3)
    var map = {};
    for (var i = 0; i < groupKeys.length; i++) {
      map[groupKeys[i]] = (i + 1) & 3;
    }

    for (var y = 0; y < 8; y++) {
      for (var block = 0; block < 2; block++) {
        var byteVal = 0;
        var startX = (block === 0) ? 7 : 3;

        for (var k = 0; k < 4; k++) {
          var x = x0 + (startX - k);
          var idx = ((y0 + y) * imgW + x) * 4;
          var r = pix[idx], g = pix[idx + 1], b = pix[idx + 2], a = pix[idx + 3];

          var ci = 0;
          if (a !== 0) {
            var key = this.rgbaKey_(r, g, b, a);
            ci = map[key] ? map[key] : 0; // masked if not in this layer
          }

          byteVal |= ((ci & 3) << (k * 2));
        }

        out[outPos++] = byteVal & 0xFF;
      }
    }

    return out;
  };

  // ---------- Color / formatting helpers ----------
  ns.MiscExportController.prototype.rgbaKey_ = function (r, g, b, a) {
    return r + ',' + g + ',' + b + ',' + a;
  };

  // Deterministic sort: compare numeric RGBA components
  ns.MiscExportController.prototype.rgbaKeySort_ = function (ka, kb) {
    // keys are "r,g,b,a"
    var pa = ka.split(','), pb = kb.split(',');
    for (var i = 0; i < 4; i++) {
      var da = parseInt(pa[i], 10) - parseInt(pb[i], 10);
      if (da !== 0) return da;
    }
    return 0;
  };

  // RGB444: 0x0BGR, using top 4 bits of each 8-bit channel
  ns.MiscExportController.prototype.rgbToRgb444_ = function (r, g, b) {
    var r4 = (r >> 4) & 0x0F;
    var g4 = (g >> 4) & 0x0F;
    var b4 = (b >> 4) & 0x0F;
    return (b4 << 8) | (g4 << 4) | r4;
  };

  ns.MiscExportController.prototype.hex8_ = function (v) {
    var s = (v & 0xFF).toString(16);
    return '0x' + ('00' + s).slice(-2);
  };

  ns.MiscExportController.prototype.hex16_ = function (v) {
    var s = (v & 0xFFFF).toString(16);
    return '0x' + ('0000' + s).slice(-4);
  };

})();
