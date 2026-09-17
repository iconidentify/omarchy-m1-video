/* SPDX-License-Identifier: LGPL-2.1-or-later
 * Actual patched decode_nal_units + ff_h2645_packet_split, no device.
 * start/slice hwaccel entry calls admit_*; end_frame is the extracted callback.
 * VA parameter buffers are not filled. Issue/cancel are intercepted. */
#include <stdio.h>
#include <string.h>
#include "config_components.h"
#include "hwaccel_internal.h"
#include "glue.inc"

static int issues, cancels, starts, slices;
int ff_vaapi_decode_issue(AVCodecContext *avctx, VAAPIDecodePicture *pic)
{ (void)avctx; (void)pic; ++issues; return 0; }
int ff_vaapi_decode_cancel(AVCodecContext *avctx, VAAPIDecodePicture *pic)
{ (void)avctx; (void)pic; ++cancels; return 0; }
void ff_h264_draw_horiz_band(const H264Context *h, H264SliceContext *sl, int y, int height)
{ (void)h; (void)sl; (void)y; (void)height; }

static int start_frame(AVCodecContext *avctx, const AVBufferRef *ref,
                       const uint8_t *buf, uint32_t size)
{
    H264Context *h = avctx->priv_data;
    (void)ref; (void)buf; (void)size;
    ++starts;
    return ff_h264_vaapi_admit_start(avctx, h);
}
static int decode_slice(AVCodecContext *avctx, const uint8_t *buf, uint32_t size)
{
    H264Context *h = avctx->priv_data;
    (void)buf; (void)size;
    ++slices;
    return ff_h264_vaapi_admit_slice(avctx, h);
}
#include "end.inc"

static H264Picture *owned_pic;
int ff_h264_queue_decode_slice(H264Context *h, const H2645NAL *nal)
{
    (void)nal;
    if (!h->cur_pic_ptr)
        h->cur_pic_ptr = owned_pic;
    h->current_slice++;
    h->nb_slice_ctx_queued = 1;
    h->slice_ctx[0].slice_type = AV_PICTURE_TYPE_I;
    return 0;
}
int ff_h264_execute_decode_slices(H264Context *h)
{
    if (!h->cur_pic_ptr || !h->has_slice || !FF_HW_HAS_CB(h->avctx, end_frame))
        return 0;
    return FF_HW_SIMPLE_CALL(h->avctx, end_frame);
}
int ff_h264_decode_seq_parameter_set(GetBitContext *gb, AVCodecContext *avctx,
                                     H264ParamSets *ps, int ignore)
{
    static SPS sps;
    (void)gb; (void)avctx; (void)ignore;
    memset(&sps, 0, sizeof(sps));
    sps.frame_mbs_only_flag = 1;
    sps.bit_depth_luma = sps.bit_depth_chroma = 8;
    ps->sps = &sps;
    return 0;
}
int ff_h264_decode_picture_parameter_set(GetBitContext *gb, AVCodecContext *avctx,
                                         H264ParamSets *ps, int bit_length)
{
    static PPS pps;
    (void)gb; (void)avctx; (void)bit_length;
    memset(&pps, 0, sizeof(pps));
    pps.slice_group_count = 1;
    ps->pps = &pps;
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
    .end_frame = vaapi_h264_end_frame,
};
static AVCodecContext avctx;
static AVCodecInternal internal;
static VAAPIDecodeContext ctx;
static H264Context h;
static H264SliceContext sl;
static H264Picture picture;
static VAAPIDecodePicture pic;
static SPS sps;
static PPS pps;

static void reset(void)
{
    memset(&ctx, 0, sizeof(ctx));
    memset(&h, 0, sizeof(h));
    memset(&sl, 0, sizeof(sl));
    memset(&sps, 0, sizeof(sps));
    memset(&pps, 0, sizeof(pps));
    memset(&picture, 0, sizeof(picture));
    internal.hwaccel_priv_data = &ctx;
    avctx.internal = &internal;
    avctx.hwaccel = &va.p;
    avctx.priv_data = &h;
    avctx.codec_id = AV_CODEC_ID_H264;
    avctx.err_recognition = 0;
    avctx.active_thread_type = 0;
    h.avctx = &avctx;
    h.cur_pic_ptr = &picture;
    owned_pic = &picture;
    picture.hwaccel_picture_private = &pic;
    h.ps.sps = &sps;
    h.ps.pps = &pps;
    h.slice_ctx = &sl;
    h.nb_slice_ctx = 1;
    sps.frame_mbs_only_flag = 1;
    pps.slice_group_count = 1;
    h.picture_structure = PICT_FRAME;
    sl.slice_type = AV_PICTURE_TYPE_I;
    issues = cancels = starts = slices = 0;
}

static int annexb(uint8_t *dst, int type, const uint8_t *pay, int n)
{
    dst[0] = dst[1] = dst[2] = 0;
    dst[3] = 1;
    dst[4] = (uint8_t)(0x60 | type);
    if (n)
        memcpy(dst + 5, pay, n);
    return 5 + n;
}

#define CHECK(c) do { if (!(c)) { fprintf(stderr, "failed line %d: %s\n", __LINE__, #c); return 1; } } while (0)

int main(void)
{
    uint8_t buf[128], extra[8] = {0x80, 0x11, 0x22};
    int n, ret;

    reset();
    ret = decode_nal_units(&h, NULL, buf, 0);
    CHECK(issues == 0);
    (void)ret;

    reset();
    n = 0;
    n += annexb(buf + n, 7, extra, 3);
    n += annexb(buf + n, 8, extra, 3);
    extra[0] = 0x80;
    n += annexb(buf + n, 5, extra, 3);
    ret = decode_nal_units(&h, NULL, buf, n);
    CHECK(ret >= 0 && issues == 1 && starts == 1 && slices >= 1 && cancels == 0);

    reset();
    n = 0;
    n += annexb(buf + n, 7, extra, 3);
    n += annexb(buf + n, 8, extra, 3);
    n += annexb(buf + n, 5, extra, 3);
    n += annexb(buf + n, 2, extra, 3); /* DPA suffix after accepted prefix */
    ret = decode_nal_units(&h, NULL, buf, n);
    CHECK(ret < 0 && issues == 0);
    CHECK(ff_h264_vaapi_admit_start(&avctx, &h) < 0); /* sticky */

    reset();
    n = annexb(buf, 19, extra, 3); /* auxiliary NAL alone */
    ret = decode_nal_units(&h, NULL, buf, n);
    CHECK(ret < 0 && issues == 0);

    reset();
    /* AVCC: 4-byte lengths */
    h.nal_length_size = 4;
    h.is_avc = 1;
    buf[0] = buf[1] = buf[2] = 0;
    buf[3] = 4;
    buf[4] = 0x65;
    buf[5] = buf[6] = buf[7] = 0;
    ret = decode_nal_units(&h, NULL, buf, 8);
    CHECK(issues == 1 || (issues == 0 && ret < 0)); /* one AU or rejected empty-config */
    /* configuration still uses avctx profile, not these NALs; remap stays disabled */

    reset();
    avctx.hwaccel = NULL;
    n = annexb(buf, 2, extra, 3);
    ret = decode_nal_units(&h, NULL, buf, n);
    CHECK(issues == 0);

    puts("PASS actual decode_nal_units/packet_split: empty, prefix+slice issue, DPA suffix, aux NAL, AVCC, non-VA");
    return 0;
}
