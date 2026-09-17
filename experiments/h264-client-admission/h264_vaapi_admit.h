/*
 * SPDX-License-Identifier: LGPL-2.1-or-later
 * Local FFmpeg n9.0.1 H.264 VAAPI admission. Not installed, not upstream.
 */
#ifndef AVCODEC_H264_VAAPI_ADMIT_H
#define AVCODEC_H264_VAAPI_ADMIT_H

struct AVCodecContext;
struct H264Context;

int ff_h264_vaapi_admit_is_active(const struct AVCodecContext *avctx);
int ff_h264_vaapi_admit_nal(struct AVCodecContext *avctx, int type);
int ff_h264_vaapi_admit_start(struct AVCodecContext *avctx, const struct H264Context *h);
int ff_h264_vaapi_admit_slice(struct AVCodecContext *avctx, const struct H264Context *h);
int ff_h264_vaapi_admit_end(struct AVCodecContext *avctx);
int ff_h264_vaapi_admit_reject(struct AVCodecContext *avctx);

#endif
