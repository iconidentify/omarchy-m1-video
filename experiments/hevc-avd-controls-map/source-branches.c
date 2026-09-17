/* SPDX-License-Identifier: GPL-2.0-only */
/* Test the exact selected upstream function bodies, generated privately by
 * verify-source.py. This is source consistency, not a firmware oracle. */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include "v4l2-controls.h"
typedef uint8_t u8;
typedef int8_t s8;
#define BIT(n) (UINT64_C(1) << (n))
#define GENMASK(h,l) ((UINT64_MAX >> (63-(h))) & (UINT64_MAX << (l)))
#define FIELD_PREP(m,v) (((uint64_t)(v) << __builtin_ctzll(m)) & (m))
#include "selected-macros.h"
struct avd_ctx { int unused; };
struct avd_hevc_run {
 const struct v4l2_ctrl_hevc_sps *sps;
 const struct v4l2_ctrl_hevc_pps *pps;
};
static uint32_t words[256];
static unsigned count;
static void record(uint32_t word) { assert(count<256); words[count++]=word; }
#define push(value,label) record((uint32_t)(value))
#include "selected-functions.h"
int main(void)
{
 struct avd_ctx ctx={0};
 struct v4l2_ctrl_hevc_sps sps={0};
 struct v4l2_ctrl_hevc_pps pps={0};
 struct v4l2_ctrl_hevc_slice_params sl={0};
 struct avd_hevc_run run={.sps=&sps,.pps=&pps};
 sl.slice_type=V4L2_HEVC_SLICE_TYPE_I;
 stream_slice_dqtblk(&ctx,&run,&sl);
 assert(count==2 && words[0]==0x2d906800 && words[1]==0x2da40000);
 /* Weighted flags cannot enable weights for an I picture. */
 pps.flags=V4L2_HEVC_PPS_FLAG_WEIGHTED_PRED|V4L2_HEVC_PPS_FLAG_WEIGHTED_BIPRED;
 count=0;stream_slice_dqtblk(&ctx,&run,&sl);assert(count==2);
 sl.slice_type=V4L2_HEVC_SLICE_TYPE_P;pps.flags=0;
 count=0;stream_slice_dqtblk(&ctx,&run,&sl);
 assert(count==4 && words[3]==0x2dd00000);
 pps.flags=V4L2_HEVC_PPS_FLAG_WEIGHTED_PRED;
 sl.pred_weight_table.luma_log2_weight_denom=1;
 count=0;stream_slice_dqtblk(&ctx,&run,&sl);
 assert(count==4 && words[3]==0x2dd00049); /* defaults omit per-ref words */
 sl.pred_weight_table.delta_luma_weight_l0[0]=-1;
 sl.pred_weight_table.luma_offset_l0[0]=-128;
 count=0;stream_slice_dqtblk(&ctx,&run,&sl);
 assert(count==6 && words[4]==0x2de04001 && words[5]==0x2df0ff80);
 /* B L1 uses the list bit and its own signed payload. */
 sl.slice_type=V4L2_HEVC_SLICE_TYPE_B;
 pps.flags=V4L2_HEVC_PPS_FLAG_WEIGHTED_BIPRED;
 sl.pred_weight_table.delta_luma_weight_l1[0]=1;
 sl.pred_weight_table.luma_offset_l1[0]=127;
 count=0;stream_slice_dqtblk(&ctx,&run,&sl);
 assert(count==9 && words[7]==0x2de06003 && words[8]==0x2df0007f);
 /* Full QP range and signed CB/CR offsets against independent bit arithmetic. */
 sl.slice_type=V4L2_HEVC_SLICE_TYPE_I;
 for(int qp=0;qp<=51;qp++) for(int off=-12;off<=12;off++) {
  pps.init_qp_minus26=qp-26; sl.slice_qp_delta=0;
  pps.pps_cb_qp_offset=off;pps.pps_cr_qp_offset=-off;
  count=0;stream_slice_dqtblk(&ctx,&run,&sl);
  assert(words[0]==(0x2d900000u|((unsigned)qp<<10)|(((unsigned)off&31)<<5)|((unsigned)-off&31)));
 }
 pps.flags=0;sps.flags=V4L2_HEVC_SPS_FLAG_STRONG_INTRA_SMOOTHING_ENABLED;
 count=0;stream_slice_dqtblk(&ctx,&run,&sl);assert(words[1]==0x2da50000);
 sl.flags=V4L2_HEVC_SLICE_PARAMS_FLAG_SLICE_DEBLOCKING_FILTER_DISABLED;
 count=0;stream_slice_dqtblk(&ctx,&run,&sl);assert(words[1]==0x2da40000);
 sl.slice_beta_offset_div2=-6;sl.slice_tc_offset_div2=-6;
 count=0;stream_slice_dqtblk(&ctx,&run,&sl);
 assert(words[1]==(0x2da40000u|((unsigned)-6&15)<<8|((unsigned)-6&31)<<12));
 puts("PASS: exact C inactive/default/P/B weights, signed QP/offsets and deblock branches");
}
