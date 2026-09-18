/* SPDX-License-Identifier: GPL-2.0-only */
/* Isolated pinned helper bodies; poll/dequeue/kernel types are stubs. No device,
 * producer barrier, retained allocation, cache visibility or writer generation. */
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define V4L2R_POLL_TIMEOUT_MS 100
#define POLLIN 1
#define POLLOUT 4
#define V4L2R_DIAG_LEVEL_ERROR 1
#define TARGET (UINT64_C(1) << 3)
#define OTHER (UINT64_C(1) << 5)
#define NOW UINT64_C(1234567)
#define DEADLINE (NOW + UINT64_C(100000000))
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"case %s line %d: %s\n",label,__LINE__,#x);return 1;} } while (0)

struct v4l2_format { int type; };
struct v4l2r_context { uint64_t queued_capture; int video_fd; struct v4l2_format capture_format; };
struct v4l2r_capture_buffer { unsigned nb_planes; int dmabuf_fd[4]; };
struct dma_buf { int unused; };
enum dma_data_direction { DMA_FROM_DEVICE = 2 };

static struct {
    int completed_calls, completed_ret, dequeue_calls, poll_calls, reader_calls, now_calls;
    int dequeue_ret[8], poll_ret[8], reader_ret[8];
    uint64_t completed_clear, dequeue_clear[8];
    int fds[8], events[8], timeouts[8];
    uint64_t deadlines[8];
    int bad_args, diag_calls, diag_ret;
} state;
static void bound(int index) { if (index>=8) exit(91); }
static uint64_t v4l2r_now_ns(void) { state.now_calls++;return NOW; }
static int dequeue_completed_buffers(struct v4l2r_context *ctx,int type)
{
    state.completed_calls++;
    if (type!=1) state.bad_args=1;
    ctx->queued_capture &= ~state.completed_clear;
    return state.completed_ret;
}
static int dequeue_buffer(struct v4l2r_context *ctx,int type)
{
    int i=state.dequeue_calls++;bound(i);
    if (type!=1) state.bad_args=1;
    ctx->queued_capture &= ~state.dequeue_clear[i];
    return state.dequeue_ret[i];
}
static int v4l2r_poll_until(int fd,int events,uint64_t deadline)
{
    int i=state.poll_calls++;bound(i);
    state.fds[i]=fd;state.events[i]=events;state.deadlines[i]=deadline;
    return state.poll_ret[i];
}
static int v4l2r_poll_one(int fd,int events,int timeout)
{
    int i=state.reader_calls++;bound(i);
    state.fds[i]=fd;state.events[i]=events;state.timeouts[i]=timeout;
    return state.reader_ret[i];
}
static int v4l2r_diag_errno_category(int ret) { return ret; }
static void v4l2r_diag(struct v4l2r_context *ctx,int level,int category,
                     const char *name,int ret,const char *fmt,...)
{
    (void)ctx;(void)fmt;
    if (level!=V4L2R_DIAG_LEVEL_ERROR || category!=ret || strcmp(name,"reader-wait")) state.bad_args=1;
    state.diag_calls++;state.diag_ret=ret;
}
#include "extracted-barrier.h"

static int wait_case(const char *label,int variant)
{
    memset(&state,0,sizeof(state));
    struct v4l2r_context ctx={.queued_capture=TARGET|OTHER,.video_fd=7,.capture_format.type=1};
    int expected=0,polls=1,dequeues=1,completed=1;
    uint64_t remaining=OTHER;
    state.dequeue_clear[0]=TARGET;
    switch (variant) {
    case 0:break; /* target completes; unrelated capture remains queued */
    case 1:ctx.queued_capture=OTHER;polls=dequeues=0;break;
    case 2:state.completed_clear=TARGET;polls=dequeues=0;break;
    case 3:ctx.queued_capture=0;remaining=0;polls=dequeues=completed=0;break;
    case 4:state.completed_ret=expected=-EIO;polls=dequeues=0;remaining=TARGET|OTHER;break;
    case 5:state.poll_ret[0]=expected=-ETIMEDOUT;dequeues=0;remaining=TARGET|OTHER;break;
    case 6:state.poll_ret[0]=expected=-EIO;dequeues=0;remaining=TARGET|OTHER;break;
    case 7:state.dequeue_ret[0]=expected=-EIO;state.dequeue_clear[0]=0;remaining=TARGET|OTHER;break;
    case 8:
        state.dequeue_ret[0]=-EAGAIN;state.dequeue_ret[1]=-EINTR;
        state.dequeue_clear[0]=0;state.dequeue_clear[2]=TARGET;polls=dequeues=3;break;
    case 9:
        state.dequeue_ret[0]=-EAGAIN;state.dequeue_clear[0]=0;
        state.poll_ret[1]=expected=-ETIMEDOUT;polls=2;remaining=TARGET|OTHER;break;
    }
    int ret=wait_on_capture_locked(&ctx,3);
    CHECK(ret==expected);CHECK(ctx.queued_capture==remaining);
    CHECK(state.completed_calls==completed);CHECK(state.poll_calls==polls);
    CHECK(state.dequeue_calls==dequeues);CHECK(state.now_calls==1);CHECK(!state.bad_args);
    for (int i=0;i<polls;i++) {
        CHECK(state.fds[i]==7);CHECK(state.events[i]==POLLIN);CHECK(state.deadlines[i]==DEADLINE);
    }
    return 0;
}
static int reader_case(const char *label,int variant)
{
    memset(&state,0,sizeof(state));
    struct v4l2r_context ctx={0};
    struct v4l2r_capture_buffer cap={.nb_planes=4,.dmabuf_fd={11,-1,12,-1}};
    int expected=0,polls=2,diagnostics=0;
    if (variant==0) {cap.nb_planes=0;polls=0;}
    if (variant==2) {state.reader_ret[0]=expected=-EIO;polls=1;diagnostics=1;}
    if (variant==3) {state.reader_ret[1]=expected=-ETIMEDOUT;diagnostics=1;}
    CHECK(capture_wait_readers(&ctx,&cap,3)==expected);
    CHECK(state.reader_calls==polls);CHECK(state.diag_calls==diagnostics);CHECK(!state.bad_args);
    if (diagnostics) CHECK(state.diag_ret==expected);
    for(int i=0;i<polls;i++) {
        CHECK(state.fds[i]==(i==0?11:12));CHECK(state.events[i]==POLLOUT);
        CHECK(state.timeouts[i]==V4L2R_POLL_TIMEOUT_MS);
    }
    return 0;
}
static int cpu_case(const char *label)
{
    struct dma_buf dummy={0};
    CHECK(vb2_dc_dmabuf_ops_begin_cpu_access(&dummy,DMA_FROM_DEVICE)==0);
    CHECK(vb2_dc_dmabuf_ops_end_cpu_access(&dummy,DMA_FROM_DEVICE)==0);
    /* The pinned extracted bodies only return zero. Their source identity is
     * verified separately; a successful return does not prove cache coherence. */
    return 0;
}
int main(void)
{
    static const char *names[]={"selected-only","already-complete","initial-drain","empty",
        "initial-error","poll-timeout","poll-error","dequeue-error","retry","stalled"};
    for(int i=0;i<10;i++) if(wait_case(names[i],i)) return 1;
    for(int i=0;i<4;i++) if(reader_case("reader",i)) return 1;
    if(cpu_case("cpu-access")) return 1;
    puts("PASS: 15 isolated helper cases; no device or real adapter executed");
    return 0;
}
