/*
 * SPDX-License-Identifier: LGPL-2.1-or-later
 * Local FFmpeg n9.0.1 H.264 VAAPI admission. Not installed, not upstream.
 *
 * Remapping Baseline/Extended is intentionally disabled: config still happens
 * from avctx->profile before later PPS/slice NALs are visible. This file only
 * implements an explicit stop (no issue after reject/empty picture).
 */
#include "h264dec.h"
#include "h264_ps.h"
#include "internal.h"
#include "vaapi_decode.h"
#include "h264_vaapi_admit.h"

int ff_h264_vaapi_admit_reject(AVCodecContext *avctx)
{
    VAAPIDecodeContext *ctx;

    if (!avctx || !avctx->internal || !avctx->internal->hwaccel_priv_data)
        return AVERROR(EINVAL);
    ctx = avctx->internal->hwaccel_priv_data;
    ctx->h264_admit_sticky = 1;
    return AVERROR(EINVAL);
}

int ff_h264_vaapi_admit_start(AVCodecContext *avctx, const H264Context *h)
{
    VAAPIDecodeContext *ctx;
    const SPS *sps;
    const PPS *pps;

    if (!avctx || !h || !avctx->internal || !avctx->internal->hwaccel_priv_data)
        return AVERROR(EINVAL);
    ctx = avctx->internal->hwaccel_priv_data;
    if (ctx->h264_admit_sticky)
        return AVERROR(EINVAL);
    sps = h->ps.sps;
    pps = h->ps.pps;
    if (!sps || !pps)
        return ff_h264_vaapi_admit_reject(avctx);
    if (pps->slice_group_count > 1 ||
        !sps->frame_mbs_only_flag || sps->mb_aff ||
        h->picture_structure != PICT_FRAME)
        return ff_h264_vaapi_admit_reject(avctx);
    ctx->h264_admit_in_picture = 1;
    return 0;
}

int ff_h264_vaapi_admit_slice(AVCodecContext *avctx, const H264Context *h)
{
    VAAPIDecodeContext *ctx;
    const PPS *pps;
    const H264SliceContext *sl;

    if (!avctx || !h || !avctx->internal || !avctx->internal->hwaccel_priv_data)
        return AVERROR(EINVAL);
    ctx = avctx->internal->hwaccel_priv_data;
    if (ctx->h264_admit_sticky)
        return AVERROR(EINVAL);
    if (!ctx->h264_admit_in_picture)
        return ff_h264_vaapi_admit_reject(avctx);
    pps = h->ps.pps;
    sl = &h->slice_ctx[0];
    if (!pps)
        return ff_h264_vaapi_admit_reject(avctx);
    if (pps->slice_group_count > 1)
        return ff_h264_vaapi_admit_reject(avctx);
    if (sl->slice_type == AV_PICTURE_TYPE_SP || sl->slice_type == AV_PICTURE_TYPE_SI)
        return ff_h264_vaapi_admit_reject(avctx);
    return 0;
}

int ff_h264_vaapi_admit_end(AVCodecContext *avctx)
{
    VAAPIDecodeContext *ctx;

    if (!avctx || !avctx->internal || !avctx->internal->hwaccel_priv_data)
        return AVERROR(EINVAL);
    ctx = avctx->internal->hwaccel_priv_data;
    if (ctx->h264_admit_sticky || !ctx->h264_admit_in_picture)
        return AVERROR(EINVAL);
    ctx->h264_admit_in_picture = 0;
    return 0;
}
