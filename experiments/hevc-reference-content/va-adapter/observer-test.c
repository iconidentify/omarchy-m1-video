/* SPDX-License-Identifier: GPL-3.0-or-later
 * Fake V4L2 backend + cases against actual patched decode.c and context.c.
 * Identified fake: wrapped ioctl/poll. No device fd. */
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
	if (request == VIDIOC_QBUF || request == VIDIOC_G_FMT)
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
uint32_t v4l2r_diag_context_serial(void) { return 0; }
void v4l2r_trace(const char *fmt, ...) { (void)fmt; }
VAStatus v4l2r_convert_setup(struct v4l2r_context *ctx)
{ (void)ctx; return VA_STATUS_SUCCESS; }
void v4l2r_convert_destroy(struct v4l2r_context *ctx) { (void)ctx; }
void v4l2r_convert_kick(struct v4l2r_context *ctx, int capture_index)
{ (void)ctx; (void)capture_index; }
VAStatus v4l2r_convert_drain_index(struct v4l2r_context *ctx, int capture_index)
{ (void)ctx; (void)capture_index; return VA_STATUS_SUCCESS; }
VAStatus v4l2r_convert_wait(struct v4l2r_surface *surface)
{ (void)surface; return VA_STATUS_SUCCESS; }
void *v4l2r_handles_lookup(struct v4l2r_handles *h, uint32_t id)
{ (void)h; (void)id; return NULL; }
uint32_t v4l2r_handles_alloc(struct v4l2r_handles *h, size_t object_size)
{ (void)h; (void)object_size; return 0; }
void v4l2r_handles_free(struct v4l2r_handles *h, uint32_t id)
{ (void)h; (void)id; }
void *v4l2r_handles_next(struct v4l2r_handles *h, unsigned int *iter, uint32_t *id)
{ (void)h; (void)iter; (void)id; return NULL; }
unsigned int v4l2r_profile_bit_depth(VAProfile profile)
{ (void)profile; return 8; }
int v4l2r_export_capture_dmabufs(struct v4l2r_context *ctx,
				 struct v4l2r_capture_buffer *capture, int capture_index)
{ (void)ctx; (void)capture; (void)capture_index; return 0; }
const struct v4l2r_format_info *v4l2r_format_by_pixelformat(uint32_t pixelformat)
{ (void)pixelformat; return NULL; }
VAStatus v4l2r_surface_alloc_backing(struct v4l2r_driver *drv, struct v4l2r_surface *surface)
{ (void)drv; (void)surface; return VA_STATUS_ERROR_OPERATION_FAILED; }
void v4l2r_surface_free_backing(struct v4l2r_surface *surface) { (void)surface; }
VAStatus v4l2r_vpp_create(struct v4l2r_context *ctx)
{ (void)ctx; return VA_STATUS_ERROR_OPERATION_FAILED; }
void v4l2r_vpp_destroy(struct v4l2r_context *ctx) { (void)ctx; }
VAStatus v4l2r_vpp_begin_picture(struct v4l2r_context *ctx, struct v4l2r_surface *target)
{ (void)ctx; (void)target; return VA_STATUS_ERROR_OPERATION_FAILED; }
VAStatus v4l2r_vpp_render_buffer(struct v4l2r_context *ctx, struct v4l2r_buffer *buf)
{ (void)ctx; (void)buf; return VA_STATUS_ERROR_OPERATION_FAILED; }
VAStatus v4l2r_vpp_end_picture(struct v4l2r_context *ctx)
{ (void)ctx; return VA_STATUS_ERROR_OPERATION_FAILED; }

#define CHECK(c) do { if (!(c)) { fprintf(stderr, "failed line %d: %s\n", __LINE__, #c); return 1; } } while (0)

static void init_capture(struct v4l2r_context *ctx)
{
	unsigned int i, p;

	for (i = 0; i < V4L2R_MAX_CAPTURE_BUFFERS; i++)
		for (p = 0; p < VIDEO_MAX_PLANES; p++)
			ctx->captures[i].dmabuf_fd[p] = -1;
}

int main(void)
{
	struct v4l2r_context ctx;
	struct v4l2r_observer_receipt rec;
	struct v4l2_ext_control controls[1];
	struct v4l2r_output_buffer output;
	struct v4l2r_surface surface;
	unsigned int binds;

	memset(&ctx, 0, sizeof(ctx));
	memset(&rec, 0, sizeof(rec));
	memset(&output, 0, sizeof(output));
	memset(&surface, 0, sizeof(surface));
	memset(controls, 0, sizeof(controls));
	pthread_mutex_init(&ctx.mutex, NULL);
	init_capture(&ctx);
	ctx.video_fd = 3;
	ctx.streaming = 1;
	ctx.capture_format.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
	ctx.capture_memory = V4L2_MEMORY_MMAP;
	ctx.nb_captures = 2;
	ctx.captures[0].last_ref_seq = 3;
	ctx.captures[1].last_ref_seq = 9;
	ctx.captures[1].surface = &surface;
	output.index = 0;
	output.request_fd = 4;
	ctx.pic.output = &output;
	ctx.pic.target = &surface;
	surface.capture_index = 1;
	surface.ctx = &ctx;
	surface.decode_status = VA_STATUS_SUCCESS;

	CHECK(v4l2r_observer_begin(&ctx, 0, &rec) == VA_STATUS_ERROR_UNIMPLEMENTED);
	CHECK(v4l2r_observer_enable(&ctx) == VA_STATUS_SUCCESS);
	CHECK(ctx.observer_run_generation != 0 && ctx.observer_context_id != 0);
	CHECK(v4l2r_observer_begin(&ctx, 0, &rec) == VA_STATUS_SUCCESS);
	CHECK(rec.run_generation == ctx.observer_run_generation);
	CHECK(rec.context_generation == ctx.observer_context_id);
	CHECK(rec.capture_index == 1 && rec.last_ref_seq == 9);
	CHECK(ctx.observer_paused && ctx.observer_retain);
	CHECK(v4l2r_observer_begin(&ctx, 0, &rec) == VA_STATUS_ERROR_OPERATION_FAILED);

	binds = ctx.observer_bind_count;
	CHECK(v4l2r_decode(&ctx, controls, 0, true, true) == VA_STATUS_ERROR_OPERATION_FAILED);
	CHECK(ctx.observer_bind_count == binds);

	CHECK(v4l2r_observer_end(&ctx) == VA_STATUS_SUCCESS);
	CHECK(!ctx.observer_paused && !ctx.observer_retain);
	CHECK(v4l2r_observer_end(&ctx) == VA_STATUS_ERROR_OPERATION_FAILED);

	ctx.failed = 0;
	ctx.captures[1].last_ref_seq = 0;
	binds = ctx.observer_bind_count;
	CHECK(v4l2r_context_bind_surface(&ctx, &surface) != VA_STATUS_ERROR_UNIMPLEMENTED);
	CHECK(ctx.observer_bind_count == binds + 1);
	ctx.captures[1].last_ref_seq = 9;

	CHECK(v4l2r_observer_begin(&ctx, 1, &rec) == VA_STATUS_ERROR_OPERATION_FAILED);
	ctx.streaming = 0;
	ctx.submitted = 1;
	ctx.completed = 0;
	CHECK(v4l2r_observer_begin(&ctx, 0, &rec) == VA_STATUS_ERROR_OPERATION_FAILED);
	ctx.streaming = 1;
	ctx.submitted = 0;
	ctx.completed = 0;

	CHECK(v4l2r_observer_begin(&ctx, 0, &rec) == VA_STATUS_SUCCESS);
	CHECK(v4l2r_context_bind_surface(&ctx, &surface) == VA_STATUS_ERROR_OPERATION_FAILED);
	CHECK(v4l2r_observer_teardown(&ctx) == VA_STATUS_ERROR_OPERATION_FAILED);
	CHECK(v4l2r_observer_end(&ctx) == VA_STATUS_SUCCESS);
	CHECK(v4l2r_observer_teardown(&ctx) == VA_STATUS_SUCCESS);

	CHECK(v4l2r_observer_enable(&ctx) == VA_STATUS_SUCCESS);
	ctx.submitted = 1;
	ctx.completed = 0;
	ctx.queued_capture = UINT64_C(1) << 1;
	fake_queued = 1;
	fake_dq_index = 1;
	ioctl_calls = 0;
	CHECK(v4l2r_observer_begin(&ctx, 0, &rec) == VA_STATUS_SUCCESS);
	CHECK(rec.submitted == 1 && rec.completed == 1 && rec.queued_capture == 0);
	CHECK(ioctl_calls > 0);
	CHECK(v4l2r_observer_end(&ctx) == VA_STATUS_SUCCESS);

	puts("PASS actual decode.c/context.c observer: pause-before-bind, deadline, retain/teardown, selected last_ref_seq; fake V4L2 ioctl identified");
	return 0;
}
