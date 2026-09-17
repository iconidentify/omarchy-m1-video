/* SPDX-License-Identifier: LGPL-2.1-or-later
 * Experimental local FFmpeg n9.0.1 H.264 VAAPI stop guards. No profile remap.
 * Original proposal: z23; bounded maintainer correction. Not installed/upstream. */
#include <limits.h>
#include "h264dec.h"
#include "h264_ps.h"
#include "internal.h"
#include "vaapi_decode.h"
#include "h264_vaapi_admit.h"

int ff_h264_vaapi_admit_is_active(const AVCodecContext *avctx)
{
    return avctx && avctx->hwaccel && avctx->hwaccel->pix_fmt == AV_PIX_FMT_VAAPI;
}

static VAAPIDecodeContext *admit_context(AVCodecContext *avctx)
{
    if (!ff_h264_vaapi_admit_is_active(avctx) || !avctx->internal)
        return NULL;
    return avctx->internal->hwaccel_priv_data;
}

int ff_h264_vaapi_admit_reject(AVCodecContext *avctx)
{
    VAAPIDecodeContext *ctx = admit_context(avctx);
    if (ctx) {
        ctx->h264_admit_sticky = 1;
        ctx->h264_admit_in_picture = 0;
        ctx->h264_admit_slices = 0;
    }
    return AVERROR(EINVAL);
}

int ff_h264_vaapi_admit_nal(AVCodecContext *avctx, int type)
{
    VAAPIDecodeContext *ctx;
    if (!ff_h264_vaapi_admit_is_active(avctx))
        return 0;
    ctx = admit_context(avctx);
    if (!ctx || ctx->h264_admit_sticky)
        return AVERROR(EINVAL);
    switch (type) {
    case H264_NAL_SLICE:
    case H264_NAL_IDR_SLICE:
    case H264_NAL_SEI:
    case H264_NAL_SPS:
    case H264_NAL_PPS:
    case H264_NAL_AUD:
    case H264_NAL_END_SEQUENCE:
    case H264_NAL_END_STREAM:
    case H264_NAL_FILLER_DATA:
        return 0;
    default: /* includes partitions, auxiliary/extension and unknown NALs */
        return ff_h264_vaapi_admit_reject(avctx);
    }
}

static int admit_picture(AVCodecContext *avctx, const H264Context *h)
{
    if (!h || !h->ps.sps || !h->ps.pps || !h->slice_ctx ||
        h->ps.pps->slice_group_count != 1 || h->ps.pps->redundant_pic_cnt_present ||
        !h->ps.sps->frame_mbs_only_flag || h->ps.sps->mb_aff ||
        h->picture_structure != PICT_FRAME)
        return ff_h264_vaapi_admit_reject(avctx);
    return 0;
}

int ff_h264_vaapi_admit_start(AVCodecContext *avctx, const H264Context *h)
{
    VAAPIDecodeContext *ctx = admit_context(avctx);
    if (!ctx)
        return AVERROR(EINVAL);
    if (ctx->h264_admit_sticky || ctx->h264_admit_in_picture || admit_picture(avctx, h) < 0)
        return ff_h264_vaapi_admit_reject(avctx);
    ctx->h264_admit_slices = 0;
    ctx->h264_admit_in_picture = 1;
    return 0;
}

int ff_h264_vaapi_admit_slice(AVCodecContext *avctx, const H264Context *h)
{
    VAAPIDecodeContext *ctx = admit_context(avctx);
    if (!ctx)
        return AVERROR(EINVAL);
    if (ctx->h264_admit_sticky || !ctx->h264_admit_in_picture ||
        ctx->h264_admit_slices == INT_MAX || admit_picture(avctx, h) < 0)
        return ff_h264_vaapi_admit_reject(avctx);
    if (h->nal_unit_type != H264_NAL_SLICE && h->nal_unit_type != H264_NAL_IDR_SLICE)
        return ff_h264_vaapi_admit_reject(avctx);
    if (h->slice_ctx[0].slice_type != AV_PICTURE_TYPE_I &&
        h->slice_ctx[0].slice_type != AV_PICTURE_TYPE_P &&
        h->slice_ctx[0].slice_type != AV_PICTURE_TYPE_B)
        return ff_h264_vaapi_admit_reject(avctx);
    ctx->h264_admit_slices++;
    return 0;
}

int ff_h264_vaapi_admit_end(AVCodecContext *avctx)
{
    VAAPIDecodeContext *ctx = admit_context(avctx);
    if (!ctx)
        return AVERROR(EINVAL);
    if (ctx->h264_admit_sticky || !ctx->h264_admit_in_picture || ctx->h264_admit_slices <= 0)
        return ff_h264_vaapi_admit_reject(avctx);
    ctx->h264_admit_in_picture = 0;
    ctx->h264_admit_slices = 0;
    return 0;
}
