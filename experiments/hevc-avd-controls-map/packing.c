/* SPDX-License-Identifier: GPL-2.0-only */
/* Independent C evaluation of pinned HEVC non-reference packing macros. */
#include <stdint.h>
#include <stdio.h>
#define BIT(n) (UINT64_C(1) << (n))
#define GENMASK(h, l) ((UINT64_MAX >> (63 - (h))) & (UINT64_MAX << (l)))
#define FIELD_PREP(mask, value) (((uint64_t)(value) << __builtin_ctzll(mask)) & (mask))
#include "avd-control-bits.h"
#include "hevc-flags.h"

static unsigned pack_qp(int qp, int cb, int cr)
{
	return (unsigned)(AVD_OP_QP | AVD_OP_QP_VAL((unsigned)qp) |
			  AVD_OP_QP_CB_OFF((unsigned)cb) |
			  AVD_OP_QP_CR_OFF((unsigned)cr));
}

int main(void)
{
	int qp;
	int off;
	int w;

	printf("SCL %08x\n", (unsigned)HEVC_SCL_DIMS);
	printf("QPZERO %08x\n", pack_qp(26, 0, 0));
	for (qp = 0; qp <= 51; ++qp)
		printf("QP %d %08x\n", qp, pack_qp(qp, 0, 0));
	for (off = -16; off <= 16; ++off)
		printf("QPOFF %d %08x\n", off, pack_qp(26, off, -off));
	for (off = -8; off <= 8; ++off)
		printf("DBLK %d %08x\n", off,
		       (unsigned)(AVD_OP_DBLK | AVD_OP_DBLK_OFF0((unsigned)off) |
				  AVD_OP_DBLK_OFF1((unsigned)off) |
				  AVD_OP_DBLK_FLAG_EN(1)));
	printf("DBLK_OVERLAP_MASK %08x\n",
	       (unsigned)(AVD_OP_DBLK_OFF1(0x1f) & AVD_OP_DBLK_FLAG_EN(1)));
	for (w = -64; w <= 64; w += 16)
		printf("WT %d %08x\n", w,
		       (unsigned)(AVD_OP_WEIGHTS | AVD_OP_WEIGHTS_IDENT(1) |
				  AVD_OP_WEIGHTS_WEIGHT((unsigned)(w + 64))));
	for (off = -128; off <= 127; off += 16)
		printf("OFF %d %08x\n", off,
		       (unsigned)(AVD_OP_OFFSETS |
				  AVD_OP_OFFSETS_OFFSET((unsigned)off)));
	printf("HDRQP %08x\n",
	       (unsigned)(AVD_HDR_H26X_QP_OFFSET_CB((unsigned)-12) |
			  AVD_HDR_H26X_QP_OFFSET_CR((unsigned)12)));
	printf("PCM %08x\n",
	       (unsigned)(HEVC_PCM_EN(1) | HEVC_PCM_BD_LUMA(7) |
			  HEVC_PCM_BD_CHROMA(7)));
	printf("TMVP %08x\n", (unsigned)(HEVC_UNK_FLAG | HEVC_FLAG_TMVP_EN(1)));
	return 0;
}
