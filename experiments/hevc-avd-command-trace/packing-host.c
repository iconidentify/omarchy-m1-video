/* SPDX-License-Identifier: GPL-2.0-only */
/* AI-assisted maintainer harness. Extracted functions retain upstream notices.
 * Only command packing/hook ordering are exercised: no kernel lifetime model. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "v4l2-controls.h"
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
typedef int8_t s8;
typedef uint64_t dma_addr_t;
typedef int32_t s32;
#define BIT(n) (UINT64_C(1) << (n))
#define GENMASK(h,l) ((UINT64_MAX >> (63-(h))) & (UINT64_MAX << (l)))
#define FIELD_PREP(m,v) (((uint64_t)(v) << __builtin_ctzll(m)) & (m))
#include "macros.h"
#include "cmd-core.h"
struct avd_variant { unsigned quirks, revision; };
struct avd_dev { struct avd_variant *variant; void *dev; };
struct avd_buf { u64 addr; };
struct avd_hevc_ctx {
 struct { struct avd_buf pipe_state, ip_above, lf_above, lf_above_info,
 lf_left, lf_left_info, az_above, sw_left; } bufs;
 int submit_num;
};
struct avd_ctx {
 struct avd_dev *dev; struct avd_hevc_ctx *priv; bool decomp;
 struct { unsigned num; } job;
 struct { u32 offsets[4]; } comp;
 struct { struct { struct { struct { u32 bytesperline; } plane_fmt[1]; } pix_mp; } fmt; } decoded_fmt;
};
struct avd_hevc_tile_info { u32 col_bd[23], row_bd[23], *tile_ids, *ctb_addr_rs_to_ts; };
struct avd_hevc_run {
 const struct v4l2_ctrl_hevc_sps *sps;
 const struct v4l2_ctrl_hevc_pps *pps;
 const struct v4l2_ctrl_hevc_scaling_matrix *scaling_matrix;
 const struct v4l2_ctrl_hevc_decode_params *decode;
 const struct v4l2_ctrl_hevc_slice_params *sl;
 struct { u64 comp_out, y_out, uv_out, coded_in; } base;
 int num_slices, num_entry_point_offsets;
 const u32 *entry_point_offsets;
 struct avd_hevc_tile_info tile_info;
};
static unsigned count;
static u32 last;
static void record(u32 word, const char *label) {
 assert(count++ < 2048); last=word; printf("P %08x %s\n",word,label);
}
#define push(value,label) record((u32)(value),label)
/* Address/reference helpers are outside this selected non-reference test.
 * They are explicit no-ops in both runs; this does not prove their behavior. */
#define pusha(value,label,index) ((void)(value))
#define push_comp(ctx,address,offsets) ((void)(address))
#define stream_refs(ctx,run) ((void)(ctx))
#define stream_slice_mv(ctx,run,sl,first) ((void)(ctx))
#define avd_trace_list(ctx,list,index,ref,word) ((void)(word))
#define avd_trace_last_word(ctx) last
static inline void avd_cmdtrace_word(struct avd_ctx *ctx,unsigned site) {
 (void)ctx; assert(count); printf("T %08x %u\n",last,site);
}
static inline void avd_cmdtrace_inactive(struct avd_ctx *ctx,unsigned site) {
 (void)ctx; printf("I %u\n",site);
}
static inline void avd_cmdtrace_slice_meta(struct avd_ctx *ctx,unsigned size,unsigned offset,unsigned flags,unsigned data_byte_offset) {
 (void)ctx;printf("M %u %u %u %u\n",size,offset,flags,offset+data_byte_offset);
}
#define dev_err(dev,...) abort()
struct sl_ctx { u32 ctx_col, ctx_row; s32 q1_col, q1_row; };
#include "functions.h"
#include "serializer.h"
static uint64_t get_le(const unsigned char *in, unsigned *n, unsigned count) {
 uint64_t v=0;assert(*n+count<=CMD_PACKED);
 for(unsigned i=0;i<count;i++)v|=(uint64_t)in[(*n)++]<<(i*8);
 return v;
}
static void unpack(const unsigned char *in,struct v4l2_ctrl_hevc_sps *sps,
 struct v4l2_ctrl_hevc_pps *pps, struct v4l2_ctrl_hevc_scaling_matrix *sc,
 struct v4l2_ctrl_hevc_slice_params *sl, struct v4l2_ctrl_hevc_decode_params *dec) {
 struct v4l2_hevc_pred_weight_table *w=&sl->pred_weight_table;
 uint64_t flags=0;unsigned n=0;
#define R_U8(v,count) (v)=get_le(in,&n,1)
#define R_S8(v,count) (v)=(int8_t)get_le(in,&n,1)
#define R_U16(v,count) (v)=get_le(in,&n,2)
#define R_U32(v,count) (v)=get_le(in,&n,4)
#define R_S32(v,count) (v)=(int32_t)get_le(in,&n,4)
#define R_U64(v,count) (v)=get_le(in,&n,8)
#define R_BYTES(v,count) do {assert(n+(count)<=CMD_PACKED);memcpy((v),in+n,(count));n+=(count);}while(0)
#define FIELD(kind,name,member,count) R_##kind(member,count);
#include "control-layout.inc"
#undef FIELD
 assert(n==CMD_PACKED);dec->flags=flags;
}
int main(int argc,char **argv) {
 if(argc!=5)return 2;
 assert(sizeof(struct cmd_window)==7596 && sizeof(struct cmd_capture)==90824);
 struct avd_variant variant={.revision=strtoul(argv[2],NULL,10),.quirks=strtoul(argv[3],NULL,10)};
 struct avd_dev dev={.variant=&variant};struct avd_hevc_ctx hc={0};
 struct avd_ctx ctx={.dev=&dev,.priv=&hc,.decomp=strtoul(argv[1],NULL,10)};
 ctx.decoded_fmt.fmt.pix_mp.plane_fmt[0].bytesperline=strtoul(argv[4],NULL,10);
 struct v4l2_ctrl_hevc_sps sps={0};struct v4l2_ctrl_hevc_pps pps={0};
 struct v4l2_ctrl_hevc_scaling_matrix sc={0};struct v4l2_ctrl_hevc_decode_params dec={0};
 struct v4l2_ctrl_hevc_slice_params sl={0};
 unsigned char in[CMD_PACKED],out[CMD_PACKED];
 if(fread(in,1,sizeof in,stdin)!=sizeof in || getchar()!=EOF)return 3;
 /* Poison native reserved bytes: named packing must never copy them. */
 memset(&sps,0xa5,sizeof sps);memset(&pps,0xa5,sizeof pps);memset(&sl,0xa5,sizeof sl);
 unpack(in,&sps,&pps,&sc,&sl,&dec);
 /* Check the actual kernel serializer against the entire wire payload. */
 assert(pack_controls(out,&sps,&pps,&sc,&sl,dec.flags)==CMD_PACKED);
 assert(!memcmp(in,out,sizeof in));
 unsigned log2=sps.log2_min_luma_coding_block_size_minus3+3+sps.log2_diff_max_min_luma_coding_block_size;
 assert(log2<=6 && log2>=3);
 unsigned ctb=1u<<log2,width=(sps.pic_width_in_luma_samples+ctb-1)/ctb;
 unsigned height=(sps.pic_height_in_luma_samples+ctb-1)/ctb;
 assert(width && height && width*height<=4194304 && sl.slice_segment_addr<width*height);
 u32 *map=calloc(width*height,sizeof(*map)),*tiles=calloc(width*height,sizeof(*tiles));assert(map&&tiles);
 for(unsigned i=0;i<width*height;i++)map[i]=i;
 struct avd_hevc_run run={.sps=&sps,.pps=&pps,.scaling_matrix=&sc,.decode=&dec,.sl=&sl,
 .num_slices=1,.num_entry_point_offsets=1,
 .tile_info={.col_bd={0,width},.row_bd={0,height},.tile_ids=tiles,.ctb_addr_rs_to_ts=map}};
 set_header(&ctx,&run);assert(stream_slices(&ctx,&run)==0);
 free(map);free(tiles);return 0;
}
