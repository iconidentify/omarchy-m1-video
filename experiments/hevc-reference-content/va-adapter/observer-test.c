/* SPDX-License-Identifier: GPL-3.0-or-later
 * Fake V4L2 backend + cases against actual patched decode.c observer API.
 * Identified fake: wrapped ioctl/poll below. No device fd. */
#include <errno.h>
#include <poll.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <linux/videodev2.h>
#include "v4l2_request.h"

static int fake_queued;
static int fake_dq_index;
static int ioctl_calls;

int __wrap_ioctl(int fd, unsigned long request, ...)
{
	(void)fd;
	++ioctl_calls;
	if (request == VIDIOC_DQBUF) {
		va_list ap;
		struct v4l2_buffer *buffer;

		if (!fake_queued)
			return errno = EAGAIN, -1;
		va_start(ap, request);
		buffer = va_arg(ap, struct v4l2_buffer *);
		va_end(ap);
		buffer->index = (unsigned int)fake_dq_index;
		fake_queued = 0;
		return 0;
	}
	if (request == VIDIOC_QBUF)
		return 0;
	errno = ENOTTY;
	return -1;
}

int __wrap_poll(struct pollfd *fds, nfds_t n, int timeout)
{
	(void)fds; (void)n; (void)timeout;
	return fake_queued ? 1 : 0;
}

void v4l2r_diag(const struct v4l2r_context *ctx, enum v4l2r_diag_level level,
		enum v4l2r_diag_category category, const char *op, int err,
		const char *fmt, ...)
{ (void)ctx; (void)level; (void)category; (void)op; (void)err; (void)fmt; }
enum v4l2r_diag_category v4l2r_diag_errno_category(int err)
{ (void)err; return V4L2R_DIAG_KERNEL; }
void v4l2r_trace(const char *fmt, ...) { (void)fmt; }
VAStatus v4l2r_context_bind_surface(struct v4l2r_context *ctx, struct v4l2r_surface *surface)
{ (void)ctx; (void)surface; return VA_STATUS_SUCCESS; }
void v4l2r_convert_kick(struct v4l2r_context *ctx, int capture_index)
{ (void)ctx; (void)capture_index; }
int v4l2r_output_buffer_grow(struct v4l2r_context *ctx, struct v4l2r_output_buffer *output, size_t min_size)
{ (void)ctx; (void)output; (void)min_size; return -ENOSYS; }
void *v4l2r_handles_lookup(struct v4l2r_handles *h, uint32_t id)
{ (void)h; (void)id; return NULL; }

#define CHECK(c) do { if (!(c)) { fprintf(stderr, "failed line %d: %s\n", __LINE__, #c); return 1; } } while (0)

int main(void)
{
	struct v4l2r_context ctx;
	struct v4l2r_observer_receipt rec;
	struct v4l2_ext_control controls[1];
	struct v4l2r_output_buffer output;
	struct v4l2r_surface surface;

	memset(&ctx, 0, sizeof(ctx));
	memset(&rec, 0, sizeof(rec));
	memset(&output, 0, sizeof(output));
	memset(&surface, 0, sizeof(surface));
	memset(controls, 0, sizeof(controls));
	pthread_mutex_init(&ctx.mutex, NULL);
	ctx.video_fd = 3;
	ctx.streaming = 1;
	ctx.capture_format.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
	ctx.capture_memory = V4L2_MEMORY_MMAP;
	ctx.nb_captures = 1;
	ctx.captures[0].last_ref_seq = 7;
	ctx.captures[0].surface = &surface;
	ctx.observer_run_generation = 11;
	output.index = 0;
	output.request_fd = 4;
	ctx.pic.output = &output;
	ctx.pic.target = &surface;
	surface.capture_index = 0;
	surface.decode_status = VA_STATUS_SUCCESS;

	CHECK(v4l2r_observer_begin(&ctx, 0, &rec) == VA_STATUS_ERROR_UNIMPLEMENTED);
	ctx.observer_enabled = 1;
	ctx.submitted = 0;
	ctx.completed = 0;
	CHECK(v4l2r_observer_begin(&ctx, 0, &rec) == VA_STATUS_SUCCESS);
	CHECK(rec.submitted == 0 && rec.completed == 0 && rec.run_generation == 11);
	CHECK(rec.context_generation == 1 && rec.last_ref_seq == 7);
	CHECK(ctx.observer_paused && ctx.observer_retain);
	CHECK(v4l2r_observer_begin(&ctx, 0, &rec) == VA_STATUS_ERROR_OPERATION_FAILED);
	ctx.queued_output = 0;
	CHECK(v4l2r_decode(&ctx, controls, 0, true, true) == VA_STATUS_ERROR_OPERATION_FAILED);
	CHECK(v4l2r_observer_end(&ctx) == VA_STATUS_SUCCESS);
	CHECK(!ctx.observer_paused && !ctx.observer_retain);
	CHECK(v4l2r_observer_end(&ctx) == VA_STATUS_ERROR_OPERATION_FAILED);

	ctx.submitted = 1;
	ctx.completed = 0;
	ctx.queued_capture = UINT64_C(1);
	fake_queued = 1;
	fake_dq_index = 0;
	ioctl_calls = 0;
	CHECK(v4l2r_observer_begin(&ctx, 0, &rec) == VA_STATUS_SUCCESS);
	CHECK(rec.submitted == 1 && rec.completed == 1 && rec.queued_capture == 0);
	CHECK(ioctl_calls > 0);
	CHECK(v4l2r_observer_end(&ctx) == VA_STATUS_SUCCESS);

	puts("PASS actual decode.c observer: default-off, pause rejects queue_decode, drain uses wait_completed_locked, fake V4L2 ioctl identified");
	return 0;
}
