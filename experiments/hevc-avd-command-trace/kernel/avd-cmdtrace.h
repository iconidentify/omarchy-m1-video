/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef AVD_CMDTRACE_H
#define AVD_CMDTRACE_H
#include "cmd-core.h"
struct avd_ctx;
struct avd_hevc_run;
void avd_cmdtrace_init(void);
void avd_cmdtrace_exit(void);
void avd_cmdtrace_open(struct avd_ctx *ctx);
void avd_cmdtrace_close(struct avd_ctx *ctx);
void avd_cmdtrace_job(struct avd_ctx *ctx);
void avd_cmdtrace_start(struct avd_ctx *ctx, struct avd_hevc_run *run);
void avd_cmdtrace_done(struct avd_ctx *ctx, int success);
void avd_cmdtrace_word(struct avd_ctx *ctx, unsigned int site);
void avd_cmdtrace_inactive(struct avd_ctx *ctx, unsigned int site);
void avd_cmdtrace_slice_meta(struct avd_ctx *ctx, unsigned int size,
			     unsigned int rel, unsigned int flags);
static inline u32 avd_cmdtrace_last_word(struct avd_ctx *ctx)
{
	struct avd_segment *seg = &ctx->job.segments[ctx->job.num];
	return seg->instructions[seg->num - 1];
}
#endif
