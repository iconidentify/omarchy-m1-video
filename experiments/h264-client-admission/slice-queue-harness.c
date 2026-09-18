/* SPDX-License-Identifier: LGPL-2.1-or-later
 * Actual patched NAL dispatch plus real slice-header/queue, execute, field-end
 * and VA end_frame. Picture allocation and software MB decode are substituted.
 * Config/thread are not claimed. */
#include <stdio.h>
#include <string.h>
#include "config_components.h"
#include "hwaccel_internal.h"
#include "libavutil/refstruct.h"
#include "libavutil/emms.h"
#include "golomb.h"
#include "h264data.h"
#include "h274.h"
#include "mpegutils.h"
#include "glue.inc"

static int starts, slices, executes, issues, cancels, field_starts, slice_inits;
static H264Picture *owned_pic;
static VAAPIDecodePicture va_pic;
static AVFrame owned_frame;

int ff_vaapi_decode_issue(AVCodecContext *avctx, VAAPIDecodePicture *pic)
{ (void)avctx; (void)pic; ++issues; return 0; }
int ff_vaapi_decode_cancel(AVCodecContext *avctx, VAAPIDecodePicture *pic)
{ (void)avctx; (void)pic; ++cancels; return 0; }
void ff_h264_draw_horiz_band(const H264Context *h, H264SliceContext *sl, int y, int height)
{ (void)h; (void)sl; (void)y; (void)height; }
int ff_h264_sei_decode(H264SEIContext *sei, GetBitContext *gb, const H264ParamSets *ps, void *logctx)
{ (void)sei; (void)gb; (void)ps; (void)logctx; return 0; }
void ff_h264_sei_uninit(H264SEIContext *sei) { (void)sei; }
static void idr(H264Context *h)
{
    h->poc.prev_frame_num = 0;
    h->poc.prev_frame_num_offset = 0;
    h->poc.prev_poc_msb = 1 << 16;
    h->poc.prev_poc_lsb = -1;
}
static int get_last_needed_nal(H264Context *h) { (void)h; return 0; }
void ff_thread_finish_setup(AVCodecContext *avctx) { (void)avctx; }
void ff_thread_report_progress(ThreadFrame *f, int n, int field) { (void)f; (void)n; (void)field; }
void debug_green_metadata(const H264SEIGreenMetaData *m, void *logctx) { (void)m; (void)logctx; }
void ff_h264_set_erpic(ERPicture *dst, const H264Picture *src) { (void)dst; (void)src; }
void ff_er_add_slice(ERContext *s, int startx, int starty, int endx, int endy, int type)
{ (void)s; (void)startx; (void)starty; (void)endx; (void)endy; (void)type; }
void ff_er_frame_end(ERContext *s, int *decode_error_flags)
{ (void)s; (void)decode_error_flags; }
int ff_h264_execute_ref_pic_marking(H264Context *h) { (void)h; return 0; }
void ff_h264_unref_picture(H264Picture *pic) { (void)pic; }
int ff_h274_apply_film_grain(AVFrame *out, const AVFrame *in, const AVFilmGrainParams *params)
{ (void)out; (void)in; (void)params; return 0; }
static int decode_slice(AVCodecContext *avctx, void *arg)
{ (void)avctx; (void)arg; return AVERROR(ENOSYS); }
static void loop_filter(const H264Context *h, H264SliceContext *sl, int start_x, int end_x)
{ (void)h; (void)sl; (void)start_x; (void)end_x; }

static int h264_field_start(H264Context *h, const H264SliceContext *sl,
                            const H2645NAL *nal, int first_slice)
{
    ++field_starts;
    if (first_slice)
        av_refstruct_replace(&h->ps.pps, h->ps.pps_list[sl->pps_id]);
    if (!h->ps.pps || !h->ps.pps->sps)
        return AVERROR_INVALIDDATA;
    h->ps.sps = h->ps.pps->sps;
    h->droppable = nal->ref_idc == 0;
    h->picture_structure = sl->picture_structure;
    h->poc.frame_num = sl->frame_num;
    h->poc.poc_lsb = sl->poc_lsb;
    h->poc.delta_poc_bottom = sl->delta_poc_bottom;
    h->poc.delta_poc[0] = sl->delta_poc[0];
    h->poc.delta_poc[1] = sl->delta_poc[1];
    h->mb_width = h->ps.sps->mb_width;
    h->mb_height = h->ps.sps->mb_height;
    h->mb_num = h->mb_width * h->mb_height;
    h->picture_idr = nal->type == H264_NAL_IDR_SLICE;
    owned_pic->f = &owned_frame;
    owned_pic->hwaccel_picture_private = &va_pic;
    h->cur_pic_ptr = owned_pic;
    return 0;
}
static int h264_slice_init(H264Context *h, H264SliceContext *sl, const H2645NAL *nal)
{
    ++slice_inits;
    if (h->picture_idr && nal->type != H264_NAL_IDR_SLICE)
        return AVERROR_INVALIDDATA;
    if (!h->mb_width || sl->first_mb_addr >= h->mb_num)
        return AVERROR_INVALIDDATA;
    sl->mb_x = sl->first_mb_addr % h->mb_width;
    sl->mb_y = (sl->first_mb_addr / h->mb_width);
    sl->slice_num = ++h->current_slice;
    return 0;
}

#include "ref_helpers.inc"
#include "header_parse.inc"
#include "execute.inc"
#include "field_end.inc"
#include "queue.inc"
#include "end_frame.inc"
#include "flush.inc"

static int start_frame(AVCodecContext *avctx, const AVBufferRef *ref,
                       const uint8_t *buf, uint32_t size)
{
    (void)ref; (void)buf; (void)size;
    ++starts;
    return ff_h264_vaapi_admit_start(avctx, avctx->priv_data);
}
static int decode_slice_cb(AVCodecContext *avctx, const uint8_t *buf, uint32_t size)
{
    (void)buf; (void)size;
    ++slices;
    return ff_h264_vaapi_admit_slice(avctx, avctx->priv_data);
}

#include "decode_nal.inc"

static const FFHWAccel va = {
    .p = { .pix_fmt = AV_PIX_FMT_VAAPI },
    .start_frame = start_frame,
    .decode_slice = decode_slice_cb,
    .end_frame = vaapi_h264_end_frame,
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
static void reset(int avcc, int explode, int chunks)
{
    cleanup();
    memset(&ctx, 0, sizeof(ctx)); memset(&h, 0, sizeof(h));
    memset(&sl, 0, sizeof(sl)); memset(&picture, 0, sizeof(picture));
    memset(&avctx, 0, sizeof(avctx)); memset(&internal, 0, sizeof(internal));
    memset(&va_pic, 0, sizeof(va_pic)); memset(&owned_frame, 0, sizeof(owned_frame));
    internal.hwaccel_priv_data = &ctx;
    avctx.internal = &internal; avctx.hwaccel = &va.p; avctx.priv_data = &h;
    avctx.codec_id = AV_CODEC_ID_H264;
    avctx.err_recognition = explode ? AV_EF_EXPLODE : 0;
    if (chunks)
        avctx.flags2 |= AV_CODEC_FLAG2_CHUNKS;
    h.avctx = &avctx; h.slice_ctx = &sl; h.nb_slice_ctx = 1;
    h.picture_structure = PICT_FRAME;
    h.is_avc = avcc; h.nal_length_size = avcc ? 4 : 0;
    owned_pic = &picture;
    picture.f = &owned_frame;
    picture.hwaccel_picture_private = &va_pic;
    starts = slices = executes = issues = cancels = field_starts = slice_inits = 0;
}
static int nal(uint8_t *dst, int avcc, const uint8_t *data, int size)
{
    memset(dst, 0, 4);
    dst[3] = avcc ? size : 1;
    memcpy(dst + 4, data, size);
    return 4 + size;
}
/* Actual h264_decode_frame AU completion (n9.0.1), after decode_nal_units. */
static int finish_frame(void)
{
    if (!(avctx.flags2 & AV_CODEC_FLAG2_CHUNKS) && (!h.cur_pic_ptr || !h.has_slice))
        return AVERROR_INVALIDDATA;
    if (!(avctx.flags2 & AV_CODEC_FLAG2_CHUNKS) ||
        (h.mb_y >= h.mb_height && h.mb_height))
        return ff_h264_field_end(&h, &h.slice_ctx[0], 0);
    return 0;
}

#include "slice-fixtures.inc"
#define CHECK(c) do { if (!(c)) { fprintf(stderr, "failed line %d: %s\n", __LINE__, #c); failed = 1; goto done; } } while (0)

static int cases(int avcc, int explode)
{
    uint8_t buf[512] = {0};
    int failed = 0, n, ret, fin;
    reset(avcc, explode, 0);
    ret = decode_nal_units(&h, NULL, buf, 0);
    fin = finish_frame();
    CHECK(ret >= 0 && fin < 0 && issues == 0 && cancels == 0 && field_starts == 0);

    reset(avcc, explode, 0); memset(buf, 0, sizeof(buf)); n = 0;
    n += nal(buf + n, avcc, sps_nal, sizeof(sps_nal));
    n += nal(buf + n, avcc, pps_nal, sizeof(pps_nal));
    n += nal(buf + n, avcc, idr_nal, sizeof(idr_nal));
    ret = decode_nal_units(&h, NULL, buf, n);
    fin = finish_frame();
    CHECK(ret == n && fin == 0);
    CHECK(starts == 1 && slices == 1 && field_starts == 1 && slice_inits == 1);
    CHECK(h.slice_ctx[0].slice_type == AV_PICTURE_TYPE_I);
    CHECK(h.slice_ctx[0].first_mb_addr == 0);
    CHECK(h.ps.sps && h.ps.sps->mb_width == 4 && h.ps.sps->mb_height == 3);
    CHECK(h.picture_structure == PICT_FRAME);
    CHECK(issues == 1 && cancels == 0);
    CHECK(ctx.h264_admit_in_picture == 0 && ctx.h264_admit_slices == 0);

    reset(avcc, explode, 1); memset(buf, 0, sizeof(buf)); n = 0;
    n += nal(buf + n, avcc, sps_nal, sizeof(sps_nal));
    n += nal(buf + n, avcc, pps_nal, sizeof(pps_nal));
    n += nal(buf + n, avcc, idr_nal, sizeof(idr_nal));
    ret = decode_nal_units(&h, NULL, buf, n);
    fin = finish_frame();
    CHECK(ret == n && fin == 0 && issues == 0 && cancels == 0 && starts == 1);
    fin = ff_h264_field_end(&h, &h.slice_ctx[0], 0);
    CHECK(fin == 0 && issues == 1 && cancels == 0);

    reset(avcc, explode, 0); memset(buf, 0, sizeof(buf)); n = 0;
    n += nal(buf + n, avcc, sps_nal, sizeof(sps_nal));
    n += nal(buf + n, avcc, pps_nal, sizeof(pps_nal));
    n += nal(buf + n, avcc, idr_nal, sizeof(idr_nal));
    n += nal(buf + n, avcc, dpa_nal, sizeof(dpa_nal));
    ret = decode_nal_units(&h, NULL, buf, n);
    CHECK(ret < 0 && starts == 1 && slices == 1 && issues == 0 && cancels == 1);
    CHECK(ctx.h264_admit_sticky == 1 && ff_h264_vaapi_admit_start(&avctx, &h) < 0);
    ff_h264_flush_change(&h);
    CHECK(ctx.h264_admit_sticky == 1);
    CHECK(ff_h264_vaapi_admit_start(&avctx, &h) < 0);

    reset(avcc, explode, 0); memset(buf, 0, sizeof(buf)); n = 0;
    n += nal(buf + n, avcc, sps_nal, sizeof(sps_nal));
    n += nal(buf + n, avcc, pps_nal, sizeof(pps_nal));
    n += nal(buf + n, avcc, bad_slice_nal, sizeof(bad_slice_nal));
    ret = decode_nal_units(&h, NULL, buf, n);
    CHECK(ret < 0 && starts == 0 && slices == 0 && issues == 0 && cancels == 0);
    CHECK(ctx.h264_admit_sticky == 1);

    reset(avcc, explode, 0); memset(buf, 0, sizeof(buf)); n = 0;
    n += nal(buf + n, avcc, sps_nal, sizeof(sps_nal));
    n += nal(buf + n, avcc, pps_nal, sizeof(pps_nal));
    n += nal(buf + n, avcc, idr_nal, sizeof(idr_nal));
    n += nal(buf + n, avcc, idr2_nal, sizeof(idr2_nal));
    ret = decode_nal_units(&h, NULL, buf, n);
    fin = finish_frame();
    CHECK(ret == n && fin == 0 && starts == 2 && slices == 2);
    CHECK(issues == 2 && cancels == 0);

    reset(avcc, explode, 0); memset(buf, 0, sizeof(buf)); n = 0;
    n += nal(buf + n, avcc, field_sps_nal, sizeof(field_sps_nal));
    n += nal(buf + n, avcc, field_pps_nal, sizeof(field_pps_nal));
    n += nal(buf + n, avcc, field_idr_nal, sizeof(field_idr_nal));
    ret = decode_nal_units(&h, NULL, buf, n);
    CHECK(h.ps.sps && h.ps.sps->frame_mbs_only_flag == 0);
    CHECK(ret < 0 && issues == 0 && cancels == 1 && ctx.h264_admit_sticky == 1);

    reset(avcc, explode, 0); memset(buf, 0, sizeof(buf)); n = nal(buf, avcc, aux_nal, sizeof(aux_nal));
    ret = decode_nal_units(&h, NULL, buf, n);
    CHECK(ret < 0 && starts == 0 && issues == 0 && cancels == 0);

    reset(avcc, explode, 0); memset(buf, 0, sizeof(buf)); avctx.hwaccel = NULL;
    n = 0;
    n += nal(buf + n, avcc, sps_nal, sizeof(sps_nal));
    n += nal(buf + n, avcc, pps_nal, sizeof(pps_nal));
    n += nal(buf + n, avcc, dpa_nal, sizeof(dpa_nal));
    ret = decode_nal_units(&h, NULL, buf, n);
    CHECK(ret == n && ctx.h264_admit_sticky == 0 && issues == 0);
done:
    cleanup();
    return failed;
}
int main(void)
{
    for (int avcc = 0; avcc < 2; avcc++)
        for (int explode = 0; explode < 2; explode++)
            if (cases(avcc, explode))
                return 1;
    puts("PASS actual slice-header/queue/field-end/AU/flush: issue once per admitted picture, cancel on reject, sticky survives decoder flush; no config/thread/remap claim");
    return 0;
}
