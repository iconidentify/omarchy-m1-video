/* SPDX-License-Identifier: GPL-2.0-only */
/* Independent C evaluation of the verbatim upstream instruction macros. */
#include <stdint.h>
#include <stdio.h>
#define BIT(n) (UINT64_C(1) << (n))
#define GENMASK(h, l) ((UINT64_MAX >> (63 - (h))) & (UINT64_MAX << (l)))
#define FIELD_PREP(mask, value) (((uint64_t)(value) << __builtin_ctzll(mask)) & (mask))
#include "avd-bits.h"
int main(void)
{
    const int deltas[] = {-131073, -65536, -4, -1, 0, 1, 65535, 131071, 131072};
    for (int count = 1; count <= 16; ++count)
        for (int lt = 0; lt <= 1; ++lt)
            for (unsigned d = 0; d < sizeof(deltas) / sizeof(deltas[0]); ++d)
                printf("H %d %d %d %08x\n", count, lt, deltas[d], (unsigned)(
                    AVD_REF_NUM(count - 1) | AVD_REF_FLAG_CONST |
                    AVD_REF_FLAG_LONG(lt) | AVD_REF_DELTA_POC(deltas[d])));
    for (int list = 0; list <= 1; ++list)
        for (int pos = 0; pos < 16; ++pos)
            for (int slot = 0; slot < 16; ++slot)
                printf("L %d %d %d %08x\n", list, pos, slot, (unsigned)(
                    AVD_OP_REF | AVD_OP_REF_LIST_IDX(list) |
                    AVD_OP_REF_LOOP_IDX(pos) | AVD_OP_REF_DBP_IDX(slot)));
    printf("I %08x\n", (unsigned)(AVD_OP_SL_REF | AVD_OP_SL_REF_SLICE_I(1)));
    /* B-slice L0/L1 lengths two, TMVP on, L1 collocated intra reference. */
    for (int merge = 0; merge <= 4; ++merge)
        for (int cabac = 0; cabac <= 1; ++cabac)
            for (int mvd_zero = 0; mvd_zero <= 1; ++mvd_zero)
                printf("M %08x\n", (unsigned)(AVD_OP_SL_REF |
                    AVD_OP_SL_REF_MAX_MERGE(5 - merge) | AVD_OP_SL_REF_FLAG_CABAC(cabac) |
                    AVD_OP_SL_REF_FLAG0(1) | AVD_OP_SL_REF_FLAG1(!mvd_zero) |
                    AVD_OP_SL_REF_FLAG2(1) | AVD_OP_SL_REF_NUM_L0(1) |
                    AVD_OP_SL_REF_NUM_L1(1) | AVD_OP_SL_REF_SLICE_P(0) |
                    AVD_OP_SL_REF_SLICE_B(0)));
    return 0;
}
