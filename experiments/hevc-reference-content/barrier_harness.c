/* SPDX-License-Identifier: GPL-2.0-only */
/* Isolated stubbed execution of four extracted helpers. Not a client adapter. */
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
#define EXPECTED_DEADLINE ((uint64_t)V4L2R_POLL_TIMEOUT_MS * 1000000)

struct v4l2_format { int type; };
struct v4l2r_context {
	uint64_t queued_capture;
	int video_fd;
	struct v4l2_format capture_format;
};
struct v4l2r_capture_buffer {
	unsigned nb_planes;
	int dmabuf_fd[4];
};
struct dma_buf { int unused; };
enum dma_data_direction { DMA_FROM_DEVICE = 2 };

static int poll_until_calls;
static int poll_until_fd;
static int poll_until_events;
static uint64_t poll_until_deadline;
static int poll_one_fds[8];
static int poll_one_timeouts[8];
static int poll_one_count;
static int fail_poll_until;
static int fail_poll_one;
static int fail_dequeue;
static uint32_t complete_index = 3;

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
	if (fail_dequeue)
		return -5;
	/* Complete only the waited index; leave any other queued capture. */
	ctx->queued_capture &= ~(UINT64_C(1) << complete_index);
	return 0;
}
static int v4l2r_poll_until(int fd, int events, uint64_t deadline)
{
	poll_until_calls++;
	poll_until_fd = fd;
	poll_until_events = events;
	poll_until_deadline = deadline;
	if (fail_poll_until)
		return -5;
	if (fd != 7 || events != POLLIN || deadline != EXPECTED_DEADLINE)
		return -1;
	return 0;
}
static int v4l2r_poll_one(int fd, int events, int timeout)
{
	if (events != POLLOUT)
		return -1;
	if (poll_one_count < 8) {
		poll_one_fds[poll_one_count] = fd;
		poll_one_timeouts[poll_one_count] = timeout;
		poll_one_count++;
	}
	if (fail_poll_one)
		return -5;
	if (timeout != V4L2R_POLL_TIMEOUT_MS)
		return -1;
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

int main(int argc, char **argv)
{
	const char *mode = argc > 1 ? argv[1] : "success";
	struct v4l2r_context ctx = {
		.queued_capture = (UINT64_C(1) << 3) | (UINT64_C(1) << 1),
		.video_fd = 7,
		.capture_format.type = 1,
	};
	struct v4l2r_capture_buffer cap = {.nb_planes = 2, .dmabuf_fd = {11, 12, -1, -1}};
	struct dma_buf dummy = {0};
	int wait_ret, read_ret, begin_ret, end_ret;

	if (!strcmp(mode, "readers-fail"))
		fail_poll_one = 1;
	else if (!strcmp(mode, "dequeue-fail"))
		fail_dequeue = 1;
	else if (!strcmp(mode, "poll-fail"))
		fail_poll_until = 1;
	else if (strcmp(mode, "success"))
		return 2;

	wait_ret = wait_on_capture_locked(&ctx, 3);
	read_ret = capture_wait_readers(&ctx, &cap, 3);
	begin_ret = vb2_dc_dmabuf_ops_begin_cpu_access(&dummy, DMA_FROM_DEVICE);
	end_ret = vb2_dc_dmabuf_ops_end_cpu_access(&dummy, DMA_FROM_DEVICE);

	printf("mode=%s wait=%d readers=%d begin=%d end=%d poll_until=%d poll_one=%d leftover=0x%llx\n",
	       mode, wait_ret, read_ret, begin_ret, end_ret, poll_until_calls, poll_one_count,
	       (unsigned long long)ctx.queued_capture);

	if (!strcmp(mode, "success")) {
		if (wait_ret != 0 || read_ret != 0 || begin_ret != 0 || end_ret != 0)
			return 10;
		if (ctx.queued_capture != (UINT64_C(1) << 1))
			return 12;
		if (poll_until_calls != 1 || poll_until_fd != 7 ||
		    poll_until_events != POLLIN || poll_until_deadline != EXPECTED_DEADLINE)
			return 13;
		if (poll_one_count != 2 || poll_one_fds[0] != 11 || poll_one_fds[1] != 12 ||
		    poll_one_timeouts[0] != V4L2R_POLL_TIMEOUT_MS)
			return 14;
		puts("PASS: stubbed helper execution; selected-index wait; leftover capture; no-op CPU access");
		return 0;
	}
	if (!strcmp(mode, "readers-fail")) {
		if (read_ret != -5)
			return 21;
		puts("PASS: capture_wait_readers returns poll_one error");
		return 0;
	}
	if (!strcmp(mode, "dequeue-fail")) {
		if (wait_ret != -5)
			return 22;
		if (ctx.queued_capture != ((UINT64_C(1) << 3) | (UINT64_C(1) << 1)))
			return 23;
		puts("PASS: wait_on_capture_locked returns dequeue error");
		return 0;
	}
	if (wait_ret != -5)
		return 24;
	puts("PASS: wait_on_capture_locked returns poll error");
	return 0;
}
