/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef AVD_CMDTRACE_H
#define AVD_CMDTRACE_H
#include "cmd-core.h"
struct avd_ctx;
struct avd_decoded_buffer;
struct v4l2_ctrl_hevc_sps;
struct v4l2_ctrl_hevc_pps;
struct v4l2_ctrl_hevc_scaling_matrix;
struct v4l2_ctrl_hevc_decode_params;
struct v4l2_ctrl_hevc_slice_params;
void avd_cmdtrace_init(void);
void avd_cmdtrace_exit(void);
void avd_cmdtrace_open(struct avd_ctx *ctx);
void avd_cmdtrace_close(struct avd_ctx *ctx);
void avd_cmdtrace_job(struct avd_ctx *ctx);
void avd_cmdtrace_start(struct avd_ctx *ctx,
			const struct v4l2_ctrl_hevc_sps *sps,
			const struct v4l2_ctrl_hevc_pps *pps,
			const struct v4l2_ctrl_hevc_scaling_matrix *sc,
			const struct v4l2_ctrl_hevc_decode_params *decode,
			const struct v4l2_ctrl_hevc_slice_params *sl,
			unsigned int slices, unsigned int entry_capacity,
			struct avd_decoded_buffer *dst);
void avd_cmdtrace_done(struct avd_ctx *ctx, int success);
void avd_cmdtrace_word(struct avd_ctx *ctx, unsigned int site);
void avd_cmdtrace_inactive(struct avd_ctx *ctx, unsigned int site);
void avd_cmdtrace_slice_meta(struct avd_ctx *ctx, unsigned int size,
			     unsigned int rel, unsigned int flags,
			     unsigned int data_byte_offset);
static inline u32 avd_cmdtrace_last_word(struct avd_ctx *ctx)
{
	struct avd_segment *seg = &ctx->job.segments[ctx->job.num];
	return seg->instructions[seg->num - 1];
}
#endif
