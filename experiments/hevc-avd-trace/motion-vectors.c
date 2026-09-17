/* SPDX-License-Identifier: GPL-2.0-only */
/* Evaluate the separately attributed MIT upstream instruction macros. */
#include <stdint.h>
#include <stdio.h>
#define BIT(n) (UINT64_C(1) << (n))
#define GENMASK(h, l) ((UINT64_MAX >> (63 - (h))) & (UINT64_MAX << (l)))
#define FIELD_PREP(mask, value) (((uint64_t)(value) << __builtin_ctzll(mask)) & (mask))
#include "../hevc-avd-map/avd-bits.h"
int main(void)
{
	const unsigned count[] = {0, 1, 15};
	for (unsigned type=0;type<2;type++)
	for (unsigned bits=0;bits<32;bits++)
	for (unsigned merge=0;merge<5;merge++)
	for (unsigned a=0;a<3;a++)
	for (unsigned b=0;b<3;b++)
	for (unsigned valid=0;valid<2;valid++) {
		unsigned tmvp=bits&1, mvd=bits&2, cabac=bits&4;
		unsigned col=bits&8, dep=bits&16;
		unsigned flags=!!tmvp*4|!!mvd*8|!!cabac*16|!!col*32|!!dep*512;
		unsigned word=AVD_OP_SL_REF | AVD_OP_SL_REF_MAX_MERGE(5-merge) |
			AVD_OP_SL_REF_FLAG_CABAC(cabac) | AVD_OP_SL_REF_FLAG0(tmvp && !col) |
			AVD_OP_SL_REF_FLAG1(!mvd) | AVD_OP_SL_REF_FLAG2(tmvp || dep) |
			AVD_OP_SL_REF_NUM_L0(count[a]) | AVD_OP_SL_REF_NUM_L1(count[b]) |
			AVD_OP_SL_REF_SLICE_P(type==1) | AVD_OP_SL_REF_SLICE_B(valid);
		printf("%u %u %u %u %u %u %u\n", type,flags,merge,count[a],count[b],valid,word);
	}
	return 0;
}
