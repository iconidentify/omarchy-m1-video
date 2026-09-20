/* SPDX-License-Identifier: LGPL-2.1-or-later
 * Actual patched NAL dispatch plus real slice-header/queue, execute, field-end,
 * VA end_frame and the real get_last_needed_nal frame-thread gating computation.
 * Picture allocation and software MB decode are substituted. ff_thread_finish_setup's
 * real pthread synchronization body remains stubbed (call-site gating only).
 * VA config/device advertisement is not claimed. */
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

static int starts, slices, executes, issues, cancels, field_starts, slice_inits, thread_setups;
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
#include "last_nal.inc"
void ff_thread_finish_setup(AVCodecContext *avctx) { (void)avctx; ++thread_setups; }
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

/* Output-frame construction is outside this submission-boundary fixture. */
static int finalize_frame(H264Context *h, AVFrame *dst, H264Picture *out, int *got_frame)
{ (void)h; (void)dst; (void)out; (void)got_frame; return AVERROR(ENOSYS); }
#include "frame_helpers.inc"
#include "decode_frame.inc"

static const FFHWAccel va = {
    .p = { .pix_fmt = AV_PIX_FMT_VAAPI },
    .start_frame = start_frame,
    .decode_slice = decode_slice_cb,
    .end_frame = vaapi_h264_end_frame,
};
static int other_starts, other_slices, other_ends;
static int other_start_frame(AVCodecContext *avctx, const AVBufferRef *ref,
                             const uint8_t *buf, uint32_t size)
{
    (void)avctx; (void)ref; (void)buf; (void)size;
    ++other_starts;
    return 0;
}
static int other_decode_slice(AVCodecContext *avctx, const uint8_t *buf, uint32_t size)
{
    (void)avctx; (void)buf; (void)size;
    ++other_slices;
    return 0;
}
static int other_end_frame(AVCodecContext *avctx)
{
    (void)avctx;
    ++other_ends;
    return 0;
}
static const FFHWAccel other = {
    .p = { .pix_fmt = AV_PIX_FMT_CUDA },
    .start_frame = other_start_frame,
    .decode_slice = other_decode_slice,
    .end_frame = other_end_frame,
};
static AVCodecContext avctx;
static AVCodecInternal internal;
static VAAPIDecodeContext ctx;
static H264Context h;
static H264SliceContext sl;
static H264Picture picture;
static unsigned char canary[sizeof(VAAPIDecodeContext)];
static unsigned char canary_before[sizeof(canary)];
static void arm_other(void)
{
    memset(canary, 0xa5, sizeof(canary));
    memcpy(canary_before, canary, sizeof(canary));
    internal.hwaccel_priv_data = canary;
    avctx.hwaccel = &other.p;
}
static int canary_intact(void)
{
    return memcmp(canary, canary_before, sizeof(canary)) == 0;
}

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
    starts = slices = executes = issues = cancels = field_starts = slice_inits = thread_setups = 0;
    other_starts = other_slices = other_ends = 0;
}
static int nal(uint8_t *dst, int avcc, const uint8_t *data, int size)
{
    memset(dst, 0, 4);
    dst[3] = avcc ? size : 1;
    memcpy(dst + 4, data, size);
    return 4 + size;
}
static int decode_frame(uint8_t *data, int size)
{
    AVPacket packet = { .data = data, .size = size };
    AVFrame output = {0};
    int got_frame = 0;
    return h264_decode_frame(&avctx, &output, &got_frame, &packet);
}

#include "slice-fixtures.inc"
#define CHECK(c) do { if (!(c)) { fprintf(stderr, "failed line %d: %s\n", __LINE__, #c); failed = 1; goto done; } } while (0)

static int cases(int avcc, int explode)
{
    uint8_t buf[512] = {0};
    int failed = 0, n, ret, fin;
    reset(avcc, explode, 0);
    ret = decode_frame(buf, 0);
    CHECK(ret == 0 && issues == 0 && cancels == 0 && field_starts == 0);

    reset(avcc, explode, 0); memset(buf, 0, sizeof(buf)); n = 0;
    n += nal(buf + n, avcc, sps_nal, sizeof(sps_nal));
    n += nal(buf + n, avcc, pps_nal, sizeof(pps_nal));
    n += nal(buf + n, avcc, idr_nal, sizeof(idr_nal));
    ret = decode_frame(buf, n);
    CHECK(ret == n);
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
    ret = decode_frame(buf, n);
    CHECK(ret == n && issues == 0 && cancels == 0 && starts == 1);
    fin = ff_h264_field_end(&h, &h.slice_ctx[0], 0);
    CHECK(fin == 0 && issues == 1 && cancels == 0);

    reset(avcc, explode, 0); memset(buf, 0, sizeof(buf)); n = 0;
    n += nal(buf + n, avcc, sps_nal, sizeof(sps_nal));
    n += nal(buf + n, avcc, pps_nal, sizeof(pps_nal));
    n += nal(buf + n, avcc, idr_nal, sizeof(idr_nal));
    n += nal(buf + n, avcc, dpa_nal, sizeof(dpa_nal));
    ret = decode_frame(buf, n);
    CHECK(ret < 0 && starts == 1 && slices == 1 && issues == 0 && cancels == 1);
    CHECK(ctx.h264_admit_sticky == 1 && ff_h264_vaapi_admit_start(&avctx, &h) < 0);
    ff_h264_flush_change(&h);
    CHECK(ctx.h264_admit_sticky == 1);
    CHECK(ff_h264_vaapi_admit_start(&avctx, &h) < 0);

    reset(avcc, explode, 0); memset(buf, 0, sizeof(buf)); n = 0;
    n += nal(buf + n, avcc, sps_nal, sizeof(sps_nal));
    n += nal(buf + n, avcc, pps_nal, sizeof(pps_nal));
    n += nal(buf + n, avcc, bad_slice_nal, sizeof(bad_slice_nal));
    ret = decode_frame(buf, n);
    CHECK(ret < 0 && starts == 0 && slices == 0 && issues == 0 && cancels == 0);
    CHECK(ctx.h264_admit_sticky == 1);

    reset(avcc, explode, 0); memset(buf, 0, sizeof(buf)); n = 0;
    n += nal(buf + n, avcc, sps_nal, sizeof(sps_nal));
    n += nal(buf + n, avcc, pps_nal, sizeof(pps_nal));
    n += nal(buf + n, avcc, idr_nal, sizeof(idr_nal));
    n += nal(buf + n, avcc, idr2_nal, sizeof(idr2_nal));
    ret = decode_frame(buf, n);
    CHECK(ret == n && starts == 2 && slices == 2);
    CHECK(issues == 2 && cancels == 0);

    /* The next IDR completes the previous picture inside the real queue.
     * A later rejected suffix cannot undo that earlier submission. */
    reset(avcc, explode, 0); memset(buf, 0, sizeof(buf)); n = 0;
    n += nal(buf + n, avcc, sps_nal, sizeof(sps_nal));
    n += nal(buf + n, avcc, pps_nal, sizeof(pps_nal));
    n += nal(buf + n, avcc, idr_nal, sizeof(idr_nal));
    n += nal(buf + n, avcc, idr2_nal, sizeof(idr2_nal));
    n += nal(buf + n, avcc, dpa_nal, sizeof(dpa_nal));
    CHECK(decode_frame(buf, n) < 0 && starts == 2 && issues == 1 && cancels == 1);

    reset(avcc, explode, 0); memset(buf, 0, sizeof(buf)); n = 0;
    n += nal(buf + n, avcc, field_sps_nal, sizeof(field_sps_nal));
    n += nal(buf + n, avcc, field_pps_nal, sizeof(field_pps_nal));
    n += nal(buf + n, avcc, field_idr_nal, sizeof(field_idr_nal));
    ret = decode_frame(buf, n);
    CHECK(h.ps.sps && h.ps.sps->frame_mbs_only_flag == 0);
    CHECK(ret < 0 && issues == 0 && cancels == 1 && ctx.h264_admit_sticky == 1);

    reset(avcc, explode, 0); memset(buf, 0, sizeof(buf)); n = nal(buf, avcc, aux_nal, sizeof(aux_nal));
    ret = decode_frame(buf, n);
    CHECK(ret < 0 && starts == 0 && issues == 0 && cancels == 0);

    reset(avcc, explode, 0); memset(buf, 0, sizeof(buf)); avctx.hwaccel = NULL;
    n = 0;
    n += nal(buf + n, avcc, sps_nal, sizeof(sps_nal));
    n += nal(buf + n, avcc, pps_nal, sizeof(pps_nal));
    n += nal(buf + n, avcc, dpa_nal, sizeof(dpa_nal));
    ret = decode_nal_units(&h, NULL, buf, n);
    CHECK(ret == n && ctx.h264_admit_sticky == 0 && issues == 0);

    /* Actual dispatch with a fake non-VA hwaccel. Foreign priv_data is a
     * canary; DPA/aux/extension must not write VA sticky or cancel. */
    reset(avcc, explode, 0); memset(buf, 0, sizeof(buf)); arm_other();
    n = nal(buf, avcc, dpa_nal, sizeof(dpa_nal));
    ret = decode_nal_units(&h, NULL, buf, n);
    CHECK(canary_intact());
    CHECK(ret == n && issues == 0 && cancels == 0 && other_ends == 0);

    reset(avcc, explode, 0); memset(buf, 0, sizeof(buf)); arm_other();
    n = nal(buf, avcc, aux_nal, sizeof(aux_nal));
    ret = decode_nal_units(&h, NULL, buf, n);
    CHECK(canary_intact());
    CHECK(ret == n && issues == 0 && cancels == 0 && other_ends == 0);

    reset(avcc, explode, 0); memset(buf, 0, sizeof(buf)); arm_other();
    n = nal(buf, avcc, ext_nal, sizeof(ext_nal));
    ret = decode_nal_units(&h, NULL, buf, n);
    CHECK(canary_intact());
    CHECK(ret == n && issues == 0 && cancels == 0 && other_ends == 0);

    reset(avcc, explode, 0); memset(buf, 0, sizeof(buf)); arm_other(); n = 0;
    n += nal(buf + n, avcc, sps_nal, sizeof(sps_nal));
    n += nal(buf + n, avcc, pps_nal, sizeof(pps_nal));
    n += nal(buf + n, avcc, idr_nal, sizeof(idr_nal));
    n += nal(buf + n, avcc, dpa_nal, sizeof(dpa_nal));
    ret = decode_nal_units(&h, NULL, buf, n);
    CHECK(canary_intact());
    CHECK(ret == n && issues == 0 && cancels == 0);
    CHECK(other_starts == 1 && other_slices == 1 && other_ends == 0 && starts == 0);

    /* The public frame entry point has its own no-picture policy after NAL
     * dispatch. A skipped standalone NAL is consumed by decode_nal_units,
     * but a non-CHUNKS frame call must still report that no picture exists.
     * Exercise both software and fake CUDA in this VA-enabled build. */
    for (int backend = 0; backend < 2; backend++) {
        for (int which = 0; which < 3; which++) {
            const uint8_t *token = which == 0 ? dpa_nal : which == 1 ? aux_nal : ext_nal;
            int size = which == 0 ? sizeof(dpa_nal) : which == 1 ? sizeof(aux_nal) : sizeof(ext_nal);
            reset(avcc, explode, 0); memset(buf, 0, sizeof(buf));
            if (backend)
                arm_other();
            else
                avctx.hwaccel = NULL;
            n = nal(buf, avcc, token, size);
            ret = decode_frame(buf, n);
            CHECK(!backend || canary_intact());
            CHECK(ret == AVERROR_INVALIDDATA);
            CHECK(ctx.h264_admit_sticky == 0 && issues == 0 && cancels == 0);
            CHECK(starts == 0 && slices == 0 && other_starts == 0 && other_slices == 0 && other_ends == 0);
        }
    }

    /* An accepted prefix gives the non-VA backend a complete picture. Its
     * ignored suffix must preserve success and invoke that backend's real
     * field-end dispatch exactly once, without issuing or cancelling VA. */
    for (int which = 0; which < 3; which++) {
        const uint8_t *suffix = which == 0 ? dpa_nal : which == 1 ? aux_nal : ext_nal;
        int size = which == 0 ? sizeof(dpa_nal) : which == 1 ? sizeof(aux_nal) : sizeof(ext_nal);
        reset(avcc, explode, 0); memset(buf, 0, sizeof(buf)); arm_other(); n = 0;
        n += nal(buf + n, avcc, sps_nal, sizeof(sps_nal));
        n += nal(buf + n, avcc, pps_nal, sizeof(pps_nal));
        n += nal(buf + n, avcc, idr_nal, sizeof(idr_nal));
        n += nal(buf + n, avcc, suffix, size);
        ret = decode_frame(buf, n);
        CHECK(canary_intact());
        CHECK(ret == n && issues == 0 && cancels == 0);
        CHECK(other_starts == 1 && other_slices == 1 && other_ends == 1);
        CHECK(starts == 0 && slices == 0 && h.current_slice == 0);
    }

    /* A real frame call leaves CHUNKS pending. A subsequent split failure
     * must cancel it before returning, in either packet format/error mode. */
    reset(avcc, explode, 1); memset(buf, 0, sizeof(buf)); n = 0;
    n += nal(buf + n, avcc, sps_nal, sizeof(sps_nal));
    n += nal(buf + n, avcc, pps_nal, sizeof(pps_nal));
    n += nal(buf + n, avcc, idr_nal, sizeof(idr_nal));
    CHECK(decode_frame(buf, n) == n && starts == 1 && issues == 0 && cancels == 0);
    memset(buf, 0, sizeof(buf));
    buf[3] = 10; buf[4] = 0x65; /* No Annex-B start code / oversized AVCC NAL. */
    ret = decode_frame(buf, 5);
    CHECK(ret < 0 && issues == 0 && cancels == 1);
    CHECK(ctx.h264_admit_sticky && h.current_slice == 0);
    CHECK(decode_frame(buf, 5) < 0 && cancels == 1 && issues == 0);

    /* A rejected next chunk, a seek flush, and EOF must all release the
     * pending picture once. None may submit it or clear sticky rejection. */
    for (int ending = 0; ending < 4; ending++) {
        reset(avcc, explode, 1); memset(buf, 0, sizeof(buf)); n = 0;
        n += nal(buf + n, avcc, sps_nal, sizeof(sps_nal));
        n += nal(buf + n, avcc, pps_nal, sizeof(pps_nal));
        n += nal(buf + n, avcc, idr_nal, sizeof(idr_nal));
        CHECK(decode_frame(buf, n) == n && starts == 1 && issues == 0 && cancels == 0);
        if (ending < 2) {
            memset(buf, 0, sizeof(buf));
            n = nal(buf, avcc, ending ? bad_slice_nal : dpa_nal,
                    ending ? sizeof(bad_slice_nal) : sizeof(dpa_nal));
            CHECK(decode_frame(buf, n) < 0 && cancels == 1 && issues == 0);
            CHECK(decode_frame(buf, n) < 0 && cancels == 1 && issues == 0);
        } else if (ending == 2) {
            ff_h264_flush_change(&h);
            CHECK(cancels == 1 && issues == 0 && h.current_slice == 0);
            ff_h264_flush_change(&h);
            CHECK(cancels == 1 && issues == 0);
        } else {
            CHECK(decode_frame(buf, 0) == 0 && cancels == 1 && issues == 0);
            CHECK(decode_frame(buf, 0) == 0 && cancels == 1 && issues == 0);
        }
        CHECK(ctx.h264_admit_sticky && h.current_slice == 0);
    }

    /* Real get_last_needed_nal/ff_thread_finish_setup gating. Frame threading
     * off: never called. Simple picture: fires once at the slice. Two IDRs
     * in one packet: current_slice resets via the real field_end, but the
     * real setup_finished latch still allows only one call per decode_frame.
     * Trailing duplicate SPS/PPS after the slice: the real function must
     * withhold the signal because more parameter NALs still follow. */
    reset(avcc, explode, 0); memset(buf, 0, sizeof(buf)); n = 0;
    n += nal(buf + n, avcc, sps_nal, sizeof(sps_nal));
    n += nal(buf + n, avcc, pps_nal, sizeof(pps_nal));
    n += nal(buf + n, avcc, idr_nal, sizeof(idr_nal));
    ret = decode_frame(buf, n);
    CHECK(ret == n && thread_setups == 0);

    reset(avcc, explode, 0); avctx.active_thread_type = FF_THREAD_FRAME;
    memset(buf, 0, sizeof(buf)); n = 0;
    n += nal(buf + n, avcc, sps_nal, sizeof(sps_nal));
    n += nal(buf + n, avcc, pps_nal, sizeof(pps_nal));
    n += nal(buf + n, avcc, idr_nal, sizeof(idr_nal));
    ret = decode_frame(buf, n);
    CHECK(ret == n && thread_setups == 1 && h.setup_finished == 1);

    reset(avcc, explode, 0); avctx.active_thread_type = FF_THREAD_FRAME;
    memset(buf, 0, sizeof(buf)); n = 0;
    n += nal(buf + n, avcc, sps_nal, sizeof(sps_nal));
    n += nal(buf + n, avcc, pps_nal, sizeof(pps_nal));
    n += nal(buf + n, avcc, idr_nal, sizeof(idr_nal));
    n += nal(buf + n, avcc, idr2_nal, sizeof(idr2_nal));
    ret = decode_frame(buf, n);
    CHECK(ret == n && starts == 2 && issues == 2 && thread_setups == 1);

    reset(avcc, explode, 0); avctx.active_thread_type = FF_THREAD_FRAME;
    memset(buf, 0, sizeof(buf)); n = 0;
    n += nal(buf + n, avcc, sps_nal, sizeof(sps_nal));
    n += nal(buf + n, avcc, pps_nal, sizeof(pps_nal));
    n += nal(buf + n, avcc, idr_nal, sizeof(idr_nal));
    n += nal(buf + n, avcc, sps_nal, sizeof(sps_nal));
    n += nal(buf + n, avcc, pps_nal, sizeof(pps_nal));
    ret = decode_frame(buf, n);
    CHECK(ret == n && thread_setups == 0);
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
    puts("PASS actual slice-header/queue/frame/field-end/flush/frame-thread-gate: complete picture issues once; pending chunk rejects, flush and EOF cancel once; real get_last_needed_nal withholds thread setup while trailing param NALs remain; non-VA canary intact through actual dispatch; no config/remap claim");
    return 0;
}
