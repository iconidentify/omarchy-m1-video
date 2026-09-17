/* SPDX-License-Identifier: GPL-2.0 */
/*
 * Extracted from AsahiLinux/linux avd-drv.c / avd-hevc.c
 * 94fb23346d522edf53722357c426a3e58030beea
 * Copyright The Asahi Linux Contributors
 * See source-map.json. Userspace harness only; no module.
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#ifndef TILE_Y
#define TILE_Y 32
#endif

#define DIV_ROUND_UP(n, d) (((n) + (d) - 1) / (d))
#define ALIGN(x, a) (((x) + ((a) - 1)) & ~((a) - 1))

static uint32_t roundup_pow_of_two(uint32_t n)
{
	if (n <= 1)
		return 1;
	n--;
	n |= n >> 1;
	n |= n >> 2;
	n |= n >> 4;
	n |= n >> 8;
	n |= n >> 16;
	return n + 1;
}

static void calc_tile_meta(uint32_t w, uint32_t h, uint32_t bpb, uint32_t tile_dim,
			   uint32_t meta_hdr_bytes, uint32_t *tile, uint32_t *meta)
{
	uint32_t tiles_width, tiles_height, meta_tile_w, meta_tile_h, tile_bytes;

	tiles_width = DIV_ROUND_UP(w, tile_dim);
	tiles_height = DIV_ROUND_UP(h, tile_dim);
	tile_bytes = tile_dim * tile_dim * DIV_ROUND_UP(bpb, 8);
	*tile = ALIGN(tiles_width * tiles_height * tile_bytes, 16);
	meta_tile_w = roundup_pow_of_two(tiles_width);
	meta_tile_h = roundup_pow_of_two(tiles_height);
	*meta = ALIGN(meta_tile_w * meta_tile_h * meta_hdr_bytes, 16);
}

static void fill_comp(uint32_t width, uint32_t height, uint32_t bit_depth,
		      uint32_t *size, uint32_t off[4])
{
	uint32_t y_meta, y, uv_meta, uv;

	calc_tile_meta(width, height, bit_depth, TILE_Y, 32, &y, &y_meta);
	calc_tile_meta(width / 2, height / 2, bit_depth * 2, 16, 8, &uv, &uv_meta);
	off[0] = y;
	off[1] = 0;
	off[2] = y + y_meta + uv;
	off[3] = y + y_meta;
	*size = y_meta + y + uv_meta + uv;
}

static uint32_t mv_color_size(uint32_t w, uint32_t h)
{
	return DIV_ROUND_UP(w, 64) * DIV_ROUND_UP(h, 64) * 256;
}

static uint32_t nv12_sizeimage(uint32_t w, uint32_t h)
{
	return w * h + w * h / 2;
}

int main(void)
{
	uint32_t off[4], comp, start, mv, packed, va_len, gst_len;

	fill_comp(448, 240, 8, &comp, off);
	start = nv12_sizeimage(448, 240);
	mv = mv_color_size(448, 240);
	packed = start + comp + mv;
	gst_len = packed;
	va_len = 368128;
	printf("start %u\n", start);
	printf("comp %u\n", comp);
	printf("off0 %u\n", off[0]);
	printf("off1 %u\n", off[1]);
	printf("off2 %u\n", off[2]);
	printf("off3 %u\n", off[3]);
	printf("mv %u\n", mv);
	printf("gst_len %u\n", gst_len);
	printf("gst_mv %u\n", gst_len - mv);
	printf("va_len %u\n", va_len);
	printf("va_mv %u\n", va_len - mv);
	printf("gap %u\n", (va_len - mv) - (start + comp));
	printf("driver_mv_from_start_comp %u\n", start + comp);
	return 0;
}
