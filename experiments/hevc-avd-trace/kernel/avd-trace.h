/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef AVD_TRACE_H
#define AVD_TRACE_H
#include "avd-trace-core.h"
struct avd_ctx;
struct avd_decoded_buffer;
void avd_trace_init(void);
void avd_trace_exit(void);
void avd_trace_open(struct avd_ctx *ctx);
void avd_trace_close(struct avd_ctx *ctx);
void avd_trace_job(struct avd_ctx *ctx);
int avd_trace_buf_init(struct vb2_buffer *vb);
void avd_trace_buf_cleanup(struct vb2_buffer *vb);
void avd_trace_start(struct avd_ctx *ctx, struct avd_decoded_buffer *dst,
	const struct v4l2_ctrl_hevc_decode_params *decode,
	const struct v4l2_ctrl_hevc_slice_params *sl, u32 slices, u32 entry_capacity);
void avd_trace_done(struct avd_ctx *ctx, enum vb2_buffer_state result);
void avd_trace_table(struct avd_ctx *ctx, unsigned int slot,
	const struct v4l2_hevc_dpb_entry *dpb, struct avd_decoded_buffer *ref,
	bool matched, u32 word);
void avd_trace_list(struct avd_ctx *ctx, u32 list, u32 position, u32 slot,
	u32 word);
void avd_trace_motion(struct avd_ctx *ctx,
	const struct v4l2_ctrl_hevc_slice_params *sl, bool first,
	struct avd_decoded_buffer *ref, bool matched, u32 slot, u64 timestamp,
	bool valid, u32 word, bool emitted);
/* Called after an unchanged push(); never reconstruct the measured word. */
static inline u32 avd_trace_last_word(struct avd_ctx *ctx)
{
	struct avd_segment *seg = &ctx->job.segments[ctx->job.num];
	return seg->instructions[seg->num - 1];
}
#endif
