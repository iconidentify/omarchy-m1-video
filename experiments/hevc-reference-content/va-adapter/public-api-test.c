/* SPDX-License-Identifier: GPL-3.0-or-later
 * Full-driver public API regression. Context/capture state is synthetic;
 * every ioctl/poll is intercepted and no decoder is opened. */
#include <assert.h>
#include <errno.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "v4l2_request.h"

int __wrap_ioctl(int fd, unsigned long req, ...)
{ (void)fd; (void)req; errno = ENOTTY; return -1; }
int __wrap_poll(struct pollfd *p, nfds_t n, int ms)
{ (void)p; (void)n; (void)ms; errno = ENODEV; return -1; }

int main(void)
{
    struct v4l2r_driver drv = {0};
    struct VADriverContext va = { .pDriverData = &drv };
    struct VADriverVTable table = {0};
    struct v4l2r_observer_receipt receipt;
    pthread_mutex_init(&drv.mutex, NULL);
    pthread_mutex_init(&drv.api_mutex, NULL);
    assert(!v4l2r_handles_init(&drv.contexts, V4L2R_ID_OFFSET_CONTEXT));
    assert(!v4l2r_handles_init(&drv.surfaces, V4L2R_ID_OFFSET_SURFACE));
    assert(!v4l2r_handles_init(&drv.buffers, V4L2R_ID_OFFSET_BUFFER));
    v4l2r_lock_surface_api(&table);
    VAContextID cid = v4l2r_handles_alloc(&drv.contexts, sizeof(struct v4l2r_context));
    VASurfaceID sid = v4l2r_handles_alloc(&drv.surfaces, sizeof(struct v4l2r_surface));
    assert(cid != VA_INVALID_ID && sid != VA_INVALID_ID);
    struct v4l2r_context *ctx = V4L2R_CONTEXT_GET(&drv, cid);
    struct v4l2r_surface *surface = V4L2R_SURFACE_GET(&drv, sid);
    ctx->drv = &drv;
    ctx->id = cid;
    ctx->video_fd = ctx->media_fd = -1;
    pthread_mutex_init(&ctx->mutex, NULL);
    for (unsigned i = 0; i < V4L2R_OUTPUT_BUFFERS; i++)
        ctx->output[i].request_fd = -1;
    for (unsigned i = 0; i < V4L2R_MAX_CAPTURE_BUFFERS; i++)
        for (unsigned j = 0; j < VIDEO_MAX_PLANES; j++)
            ctx->captures[i].dmabuf_fd[j] = -1;
    surface->id = sid;
    surface->ctx = ctx;
    surface->capture_index = 0;
    surface->status = VASurfaceReady;
    ctx->nb_captures = 1;
    ctx->captures[0].surface = surface;
    ctx->capture_memory = V4L2_MEMORY_MMAP;
    ctx->pic.target = surface;
    assert(v4l2r_observer_enable_id(&va, cid) == VA_STATUS_SUCCESS);
    assert(v4l2r_observer_begin_id(&va, cid, 0, &receipt) == VA_STATUS_SUCCESS);
    assert(table.vaDestroySurfaces(&va, &sid, 1) == VA_STATUS_ERROR_SURFACE_BUSY);
    assert(V4L2R_SURFACE_GET(&drv, sid) == surface);
    assert(table.vaDestroyContext(&va, cid) == VA_STATUS_ERROR_OPERATION_FAILED);
    assert(table.vaBeginPicture(&va, cid, sid) == VA_STATUS_ERROR_OPERATION_FAILED);
    assert(!ctx->in_picture && ctx->pic.target == surface);
    assert(v4l2r_observer_end_id(&va, cid) == VA_STATUS_SUCCESS);
    /* No capture allocation was actually made; detach the fixture before cleanup. */
    ctx->pic.target = NULL;
    ctx->captures[0].surface = NULL;
    ctx->nb_captures = 0;
    surface->capture_index = -1;
    assert(table.vaDestroySurfaces(&va, &sid, 1) == VA_STATUS_SUCCESS);
    assert(table.vaDestroyContext(&va, cid) == VA_STATUS_SUCCESS);
    assert(v4l2r_observer_begin_id(&va, cid, 0, &receipt) == VA_STATUS_ERROR_INVALID_CONTEXT);
    v4l2r_handles_destroy(&drv.contexts);
    v4l2r_handles_destroy(&drv.surfaces);
    v4l2r_handles_destroy(&drv.buffers);
    pthread_mutex_destroy(&drv.api_mutex);
    pthread_mutex_destroy(&drv.mutex);
    puts("PASS: full-driver public surface/context/producer retention guards");
    return 0;
}
