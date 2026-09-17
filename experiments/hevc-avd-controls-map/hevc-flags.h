/* SPDX-License-Identifier: GPL-2.0
 * Verbatim selected HEVC packing macros from AsahiLinux/linux avd-hevc.c.
 * Copyright The Asahi Linux Contributors
 * Copyright 2023 Eileen Yoon <eyn@gmx.com>
 * Copyright (c) 2014 Rockchip Electronics Co., Ltd.
 * Copyright (C) 2014 Google, Inc.
 * Source/revision/hash: source-map.json.
 * Extracted definitions only; BIT/GENMASK/FIELD_PREP supplied by the test.
 */
#define HEVC_PCM_EN(v)		FIELD_PREP(BIT(12), !!(v))
#define HEVC_PCM_BD_LUMA(v)	FIELD_PREP(GENMASK(11, 8), v)
#define HEVC_PCM_BD_CHROMA(v)	FIELD_PREP(GENMASK(7, 4), v)
#define HEVC_PCM_CB_MIN_LUMA(v)	FIELD_PREP(GENMASK(3, 2), v)
#define HEVC_PCM_CB_LUMA(v)	FIELD_PREP(GENMASK(1, 0), v)
#define HEVC_UNK_ISM_EN(v)	FIELD_PREP(BIT(9), !!(v))
#define HEVC_UNK_FLAG		FIELD_PREP(BIT(3), 1)
#define HEVC_CTB_SIZE(v)	FIELD_PREP(GENMASK(8, 3), v)
#define HEVC_MERGE_LV(v)	FIELD_PREP(GENMASK(11, 9), v)
#define HEVC_FLAG_ENTROPY_EN(v)	FIELD_PREP(BIT(12), !!(v))
#define HEVC_FLAG_TILES_EN(v)	FIELD_PREP(BIT(13), !!(v))
#define HEVC_FLAG_TQB_EN(v)	FIELD_PREP(BIT(14), !!(v))
#define HEVC_CU_QP_DD(v)	FIELD_PREP(GENMASK(16, 15), v)
#define HEVC_FLAG_CU_QP_EN(v)	FIELD_PREP(BIT(17), !!(v))
#define HEVC_FLAG_TSKIP_EN(v)	FIELD_PREP(BIT(18), !!(v))
#define HEVC_FLAG_CI_PRED(v)	FIELD_PREP(BIT(19), !!(v))
#define HEVC_FLAG_SDH_EN(v)	FIELD_PREP(BIT(20), !!(v))
#define HEVC_FLAG_TMVP_EN(v)	FIELD_PREP(BIT(21), !!(v))
#define HEVC_SCL_DIMS		0x127ffff
