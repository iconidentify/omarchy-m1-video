/* SPDX-License-Identifier: LGPL-2.1-or-later
 * Actual patched NAL dispatch, packet splitter and SPS/PPS parsers.
 * Slice queuing/header parse, picture ownership and hw callbacks are substituted.
 * No end_frame callback or VA issue occurs: this is not submission-timing proof. */
#include <stdio.h>
#include <string.h>
#include "config_components.h"
#include "hwaccel_internal.h"
#include "libavutil/refstruct.h"
#include "glue.inc"

static int starts, slices, executes;
static H264Picture *owned_pic;
static int start_frame(AVCodecContext *avctx, const AVBufferRef *ref,
                       const uint8_t *buf, uint32_t size)
{
    (void)ref; (void)buf; (void)size;
    ++starts;
    return ff_h264_vaapi_admit_start(avctx, avctx->priv_data);
}
static int decode_slice(AVCodecContext *avctx, const uint8_t *buf, uint32_t size)
{
    (void)buf; (void)size;
    ++slices;
    return ff_h264_vaapi_admit_slice(avctx, avctx->priv_data);
}
int ff_h264_queue_decode_slice(H264Context *h, const H2645NAL *nal)
{
    (void)nal; /* Deliberately does not parse a slice header. */
    if (!h->ps.pps_list[0]) return AVERROR_INVALIDDATA;
    if (!h->ps.pps) h->ps.pps = av_refstruct_ref_c(h->ps.pps_list[0]);
    h->ps.sps = h->ps.pps->sps;
    h->cur_pic_ptr = owned_pic;
    h->current_slice++;
    h->nb_slice_ctx_queued = 1;
    h->slice_ctx[0].slice_type = AV_PICTURE_TYPE_I;
    return 0;
}
int ff_h264_execute_decode_slices(H264Context *h)
{
    (void)h;
    ++executes;
    /* The real function returns 0 immediately for hwaccel. Never invent end_frame. */
    return 0;
}
int ff_h264_sei_decode(H264SEIContext *sei, GetBitContext *gb, const H264ParamSets *ps,
                       void *logctx)
{ (void)sei; (void)gb; (void)ps; (void)logctx; return 0; }
void ff_h264_sei_uninit(H264SEIContext *sei) { (void)sei; }
static void idr(H264Context *h) { (void)h; }
static int get_last_needed_nal(H264Context *h) { (void)h; return 0; }
void ff_thread_finish_setup(AVCodecContext *avctx) { (void)avctx; }
void ff_thread_report_progress(ThreadFrame *f, int n, int field) { (void)f; (void)n; (void)field; }
void debug_green_metadata(const H264SEIGreenMetaData *m, void *logctx) { (void)m; (void)logctx; }
void ff_h264_set_erpic(ERPicture *dst, const H264Picture *src) { (void)dst; (void)src; }
void ff_er_add_slice(ERContext *s, int startx, int starty, int endx, int endy, int type)
{ (void)s; (void)startx; (void)starty; (void)endx; (void)endy; (void)type; }
void ff_er_frame_end(ERContext *s, int *decode_error_flags)
{ (void)s; (void)decode_error_flags; }


#include "decode_nal.inc"
static const FFHWAccel va = {
    .p = { .pix_fmt = AV_PIX_FMT_VAAPI },
    .start_frame = start_frame,
    .decode_slice = decode_slice,
};
static AVCodecContext avctx;
static AVCodecInternal internal;
static VAAPIDecodeContext ctx;
static H264Context h;
static H264SliceContext sl;
static H264Picture picture;

static void cleanup(void)
{
    ff_h2645_packet_uninit(&h.pkt);
    ff_h264_ps_uninit(&h.ps);
}
static void reset(int avcc, int explode)
{
    cleanup();
    memset(&ctx,0,sizeof(ctx)); memset(&h,0,sizeof(h));
    memset(&sl,0,sizeof(sl)); memset(&picture,0,sizeof(picture));
    memset(&avctx,0,sizeof(avctx)); memset(&internal,0,sizeof(internal));
    internal.hwaccel_priv_data=&ctx;
    avctx.internal=&internal; avctx.hwaccel=&va.p; avctx.priv_data=&h;
    avctx.codec_id=AV_CODEC_ID_H264;
    avctx.err_recognition=explode ? AV_EF_EXPLODE : 0;
    h.avctx=&avctx; h.slice_ctx=&sl; h.nb_slice_ctx=1;
    h.picture_structure=PICT_FRAME;
    h.is_avc=avcc; h.nal_length_size=avcc ? 4 : 0;
    owned_pic=&picture;
    starts=slices=executes=0;
}
static int nal(uint8_t *dst, int avcc, const uint8_t *data, int size)
{
    memset(dst,0,4);
    dst[3]=avcc ? size : 1;
    memcpy(dst+4,data,size);
    return 4+size;
}
/* Hand-encoded baseline SPS: 64x48, 8-bit progressive, one reference.
 * PPS0 refers to SPS0 with one slice group. IDR bytes are a dispatch token only;
 * the substituted slice queue does not validate its header/picture semantics. */
#include "parameter-fixtures.inc"
#define CHECK(c) do { if (!(c)) { fprintf(stderr,"failed line %d: %s\n",__LINE__,#c); failed=1; goto done; } } while(0)
static int cases(int avcc,int explode)
{
    uint8_t buf[512]={0};
    const uint8_t idr[]={0x65,0x80,0x11,0x22};
    const uint8_t dpa[]={0x62,0x80,0x11,0x22};
    const uint8_t aux[]={0x73,0x80,0x11,0x22};
    const uint8_t bad_sps[]={0x67,0x80};
    const uint8_t bad_pps[]={0x68,0x00};
    int failed=0,n,ret;
    reset(avcc,explode);
    ret=decode_nal_units(&h,NULL,buf,0);
    CHECK(starts==0 && slices==0); (void)ret;

    reset(avcc,explode); memset(buf,0,sizeof(buf)); n=0;
    n+=nal(buf+n,avcc,sps_nal,sizeof(sps_nal));
    n+=nal(buf+n,avcc,pps_nal,sizeof(pps_nal));
    n+=nal(buf+n,avcc,idr,sizeof(idr));
    ret=decode_nal_units(&h,NULL,buf,n);
    CHECK(ret==n && starts==1 && slices==1 && executes==1);
    CHECK(h.ps.sps && h.ps.sps->mb_width==4 && h.ps.sps->mb_height==3);
    CHECK(h.ps.pps && h.ps.pps->slice_group_count==1);
    CHECK(ctx.h264_admit_in_picture==1 && ctx.h264_admit_slices==1);

    /* Accepted syntax prefix, then rejected suffix; actual dispatcher must stop.
     * It has already called our start/slice mocks. No claim about real VA issue. */
    for(int which=0;which<4;which++) {
        reset(avcc,explode); memset(buf,0,sizeof(buf)); n=0;
        n+=nal(buf+n,avcc,sps_nal,sizeof(sps_nal));
        n+=nal(buf+n,avcc,pps_nal,sizeof(pps_nal));
        n+=nal(buf+n,avcc,idr,sizeof(idr));
        const uint8_t *suffix=which==0?dpa:which==1?aux:which==2?bad_sps:bad_pps;
        int size=which<2?4:2;
        n+=nal(buf+n,avcc,suffix,size);
        ret=decode_nal_units(&h,NULL,buf,n);
        CHECK(ret<0 && starts==1 && slices==1 && executes==0);
        CHECK(ctx.h264_admit_sticky==1 && ff_h264_vaapi_admit_start(&avctx,&h)<0);
    }
    reset(avcc,explode); memset(buf,0,sizeof(buf));
    n=nal(buf,avcc,aux,sizeof(aux));
    ret=decode_nal_units(&h,NULL,buf,n);
    CHECK(ret<0 && starts==0 && slices==0 && executes==0);

    if(avcc) {
        reset(avcc,explode); memset(buf,0,sizeof(buf));
        buf[3]=10;buf[4]=0x65; /* Declared NAL exceeds actual packet. */
        ret=decode_nal_units(&h,NULL,buf,5);
        CHECK(ret<0 && starts==0 && slices==0 && ctx.h264_admit_sticky);
    }
    reset(avcc,explode); memset(buf,0,sizeof(buf)); avctx.hwaccel=NULL;
    n=nal(buf,avcc,dpa,sizeof(dpa));
    ret=decode_nal_units(&h,NULL,buf,n);
    CHECK(ret==n && starts==0 && slices==0 && ctx.h264_admit_sticky==0);
done:
    cleanup();
    return failed;
}
int main(void)
{
    for(int avcc=0;avcc<2;avcc++)
        for(int explode=0;explode<2;explode++)
            if(cases(avcc,explode)) return 1;
    puts("PASS actual NAL dispatch/splitter/SPS/PPS: Annex-B/AVCC, both error modes; slice queue and hardware callbacks mocked; no issue-timing proof");
    return 0;
}
