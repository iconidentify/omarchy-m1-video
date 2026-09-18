/* SPDX-License-Identifier: GPL-2.0-only */
/* Executes extracted wait/exporter functions with recorded stubs. No device. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define V4L2R_POLL_TIMEOUT_MS 100
#define POLLIN 1
#define POLLOUT 4
#define EAGAIN 11
#define EINTR 4
#define V4L2R_DIAG_LEVEL_ERROR 1

struct v4l2_format { int type; };
struct v4l2r_context {
	uint64_t queued_capture;
	int video_fd;
	int all_producers_paused;
	unsigned generation;
	struct v4l2_format capture_format;
};
struct v4l2r_capture_buffer {
	unsigned nb_planes;
	int dmabuf_fd[4];
};
struct dma_buf { int unused; };
enum dma_data_direction { DMA_FROM_DEVICE = 2 };

static int poll_until_calls;
static int poll_one_fds[8];
static int poll_one_count;
static int begin_calls;
static unsigned generation_before;

static uint64_t v4l2r_now_ns(void) { return 0; }
static int dequeue_completed_buffers(struct v4l2r_context *ctx, int type)
{
	(void)ctx;
	(void)type;
	return 0;
}
static int dequeue_buffer(struct v4l2r_context *ctx, int type)
{
	(void)type;
	ctx->queued_capture = 0;
	return 0;
}
static int v4l2r_poll_until(int fd, int events, uint64_t deadline)
{
	(void)deadline;
	poll_until_calls++;
	if (fd < 0 || events != POLLIN)
		return -1;
	return 0;
}
static int v4l2r_poll_one(int fd, int events, int timeout)
{
	(void)timeout;
	if (events != POLLOUT)
		return -1;
	if (poll_one_count < 8)
		poll_one_fds[poll_one_count++] = fd;
	return 0;
}
static int v4l2r_diag_errno_category(int ret)
{
	(void)ret;
	return 0;
}
static void v4l2r_diag(struct v4l2r_context *ctx, int level, int cat,
		       const char *name, int ret, const char *fmt, ...)
{
	(void)ctx;
	(void)level;
	(void)cat;
	(void)name;
	(void)ret;
	(void)fmt;
}

#include "extracted-barrier.h"

int main(void)
{
	struct v4l2r_context ctx = {
		.queued_capture = UINT64_C(1) << 3,
		.video_fd = 7,
		.all_producers_paused = 0,
		.generation = 9,
		.capture_format.type = 1,
	};
	struct v4l2r_capture_buffer cap = {.nb_planes = 2, .dmabuf_fd = {11, 12, -1, -1}};
	struct dma_buf dummy = {0};
	int wait_ret, read_ret, begin_ret, end_ret;

	generation_before = ctx.generation;
	wait_ret = wait_on_capture_locked(&ctx, 3);
	read_ret = capture_wait_readers(&ctx, &cap, 3);
	begin_ret = vb2_dc_dmabuf_ops_begin_cpu_access(&dummy, DMA_FROM_DEVICE);
	end_ret = vb2_dc_dmabuf_ops_end_cpu_access(&dummy, DMA_FROM_DEVICE);
	begin_calls = 1;

	printf("wait=%d readers=%d begin=%d end=%d poll_until=%d poll_one=%d gen=%u paused=%d\n",
	       wait_ret, read_ret, begin_ret, end_ret, poll_until_calls, poll_one_count,
	       ctx.generation, ctx.all_producers_paused);
	if (wait_ret != 0 || read_ret != 0 || begin_ret != 0 || end_ret != 0)
		return 10;
	if (ctx.all_producers_paused)
		return 11;
	if (ctx.generation != generation_before)
		return 12;
	if (poll_until_calls != 1)
		return 13;
	if (poll_one_count != 2 || poll_one_fds[0] != 11 || poll_one_fds[1] != 12)
		return 14;
	puts("PASS: executed wait/reader/exporter; no pause token, no generation, no-op CPU access");
	return 0;
}
