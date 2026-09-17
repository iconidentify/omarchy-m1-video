/* SPDX-License-Identifier: LGPL-2.1-or-later
 * Synthetic states using real pinned FFmpeg types and actual patched functions.
 * No parser, VA display, decoder or media. Issue/cancel are intercepted below. */
#include <stdio.h>
#include <string.h>
#include "glue.inc"
static int issues, cancels;
int ff_vaapi_decode_issue(AVCodecContext *avctx, VAAPIDecodePicture *pic)
{ (void)avctx; (void)pic; ++issues; return 0; }
int ff_vaapi_decode_cancel(AVCodecContext *avctx, VAAPIDecodePicture *pic)
{ (void)avctx; (void)pic; ++cancels; return 0; }
void ff_h264_draw_horiz_band(const H264Context *h, H264SliceContext *sl, int y, int height)
{ (void)h; (void)sl; (void)y; (void)height; }
#include "end.inc"
static const AVHWAccel va = { .pix_fmt = AV_PIX_FMT_VAAPI };
static const AVHWAccel other = { .pix_fmt = AV_PIX_FMT_CUDA };
static AVCodecContext avctx;
static AVCodecInternal internal;
static VAAPIDecodeContext ctx;
static H264Context h;
static H264SliceContext sl;
static H264Picture picture;
static VAAPIDecodePicture pic;
static SPS sps;
static PPS pps;
static void reset(void) {
    memset(&ctx,0,sizeof(ctx)); memset(&h,0,sizeof(h)); memset(&sl,0,sizeof(sl));
    memset(&sps,0,sizeof(sps)); memset(&pps,0,sizeof(pps));
    internal.hwaccel_priv_data=&ctx;
    avctx.internal=&internal; avctx.hwaccel=&va; avctx.priv_data=&h;
    h.avctx=&avctx; h.cur_pic_ptr=&picture; picture.hwaccel_picture_private=&pic;
    h.ps.sps=&sps; h.ps.pps=&pps; h.slice_ctx=&sl;
    sps.frame_mbs_only_flag=1; pps.slice_group_count=1;
    h.picture_structure=PICT_FRAME; h.nal_unit_type=H264_NAL_IDR_SLICE;
    sl.slice_type=AV_PICTURE_TYPE_I; issues=cancels=0;
}
#define CHECK(c) do { if (!(c)) { fprintf(stderr,"failed line %d: %s\n",__LINE__,#c); return 1; } } while(0)
int main(void) {
    reset(); CHECK(vaapi_h264_end_frame(&avctx)<0 && issues==0 && cancels==1);
    reset(); CHECK(ff_h264_vaapi_admit_start(&avctx,&h)==0);
    CHECK(vaapi_h264_end_frame(&avctx)<0 && issues==0 && cancels==1);
    reset(); CHECK(ff_h264_vaapi_admit_start(&avctx,&h)==0);
    CHECK(ff_h264_vaapi_admit_start(&avctx,&h)<0);
    CHECK(vaapi_h264_end_frame(&avctx)<0 && issues==0);
    for(int type=AV_PICTURE_TYPE_I;type<=AV_PICTURE_TYPE_B;type++) {
        reset(); sl.slice_type=type;
        CHECK(ff_h264_vaapi_admit_start(&avctx,&h)==0);
        CHECK(ff_h264_vaapi_admit_slice(&avctx,&h)==0);
        CHECK(vaapi_h264_end_frame(&avctx)==0 && issues==1);
        CHECK(vaapi_h264_end_frame(&avctx)<0 && issues==1);
    }
    int invalid[]={0,2,3,4,13,14,15,16,17,18,19,20,21,22,31};
    for(unsigned i=0;i<sizeof(invalid)/sizeof(invalid[0]);i++) {
        reset(); CHECK(ff_h264_vaapi_admit_start(&avctx,&h)==0);
        CHECK(ff_h264_vaapi_admit_slice(&avctx,&h)==0);
        CHECK(ff_h264_vaapi_admit_nal(&avctx,invalid[i])<0);
        CHECK(vaapi_h264_end_frame(&avctx)<0 && issues==0);
        CHECK(ff_h264_vaapi_admit_start(&avctx,&h)<0); /* sticky */
    }
    int allowed[]={1,5,6,7,8,9,10,11,12};
    reset(); for(unsigned i=0;i<sizeof(allowed)/sizeof(allowed[0]);i++)
        CHECK(ff_h264_vaapi_admit_nal(&avctx,allowed[i])==0);
    for(int mode=0;mode<9;mode++) {
        reset(); CHECK(ff_h264_vaapi_admit_start(&avctx,&h)==0);
        CHECK(ff_h264_vaapi_admit_slice(&avctx,&h)==0);
        switch(mode) {
        case 0: pps.slice_group_count=2; break;
        case 1: pps.slice_group_count=0; break;
        case 2: sps.frame_mbs_only_flag=0; break;
        case 3: sps.mb_aff=1; break;
        case 4: h.picture_structure=PICT_TOP_FIELD; break;
        case 5: sl.slice_type=AV_PICTURE_TYPE_SP; break;
        case 6: sl.slice_type=AV_PICTURE_TYPE_SI; break;
        case 7: pps.redundant_pic_cnt_present=1; break;
        case 8: ctx.h264_admit_slices=INT_MAX; break;
        }
        CHECK(ff_h264_vaapi_admit_slice(&avctx,&h)<0);
        CHECK(vaapi_h264_end_frame(&avctx)<0 && issues==0);
    }
    reset(); CHECK(ff_h264_vaapi_admit_start(&avctx,NULL)<0);
    reset(); CHECK(ff_h264_vaapi_admit_slice(&avctx,&h)<0);
    /* VA config/advertisement is deliberately untouched; this is not profile admission. */
    for(int profile=0;profile<3;profile++) {
        reset(); sps.profile_idc=profile==0?77:profile==1?100:110;
        sps.bit_depth_luma=sps.bit_depth_chroma=profile==2?10:8;
        CHECK(ff_h264_vaapi_admit_start(&avctx,&h)==0);
        CHECK(ff_h264_vaapi_admit_slice(&avctx,&h)==0);
        CHECK(vaapi_h264_end_frame(&avctx)==0 && issues==1);
    }
    reset(); unsigned char canary[sizeof(VAAPIDecodeContext)], before[sizeof(canary)];
    memset(canary,0xa5,sizeof(canary)); memcpy(before,canary,sizeof(canary));
    internal.hwaccel_priv_data=canary; avctx.hwaccel=&other;
    CHECK(!ff_h264_vaapi_admit_is_active(&avctx));
    CHECK(ff_h264_vaapi_admit_nal(&avctx,2)==0);
    CHECK(ff_h264_vaapi_admit_reject(&avctx)<0);
    CHECK(ff_h264_vaapi_admit_start(&avctx,&h)<0);
    CHECK(ff_h264_vaapi_admit_slice(&avctx,&h)<0);
    CHECK(ff_h264_vaapi_admit_end(&avctx)<0);
    CHECK(!memcmp(canary,before,sizeof(canary)));
    avctx.hwaccel=NULL; CHECK(ff_h264_vaapi_admit_nal(&avctx,2)==0);
    CHECK(ff_h264_vaapi_admit_end(NULL)<0);
    puts("PASS actual helper/FFmpeg types/end callback: issue counts, cancellation, lifecycle, NALs, non-VA canary");
    return 0;
}
