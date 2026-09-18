/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Reuse the pinned driver's syscall/allocator model, unchanged. All contexts,
 * surfaces, capture allocations, queues, completions and destruction below
 * run actual driver code. Only V4L2 and codec payloads are modelled. */
#define main upstream_failure_cleanup_main
#include "failure-cleanup.c"
#undef main

static struct v4l2r_observer_session session;
static struct v4l2r_observer_target target;
static struct v4l2r_observer_receipt receipt;
static VAContextID cid;
static VASurfaceID sid, reference_id = VA_INVALID_ID;
static _Atomic bool block_codec, codec_entered, release_codec, owner_ready, release_owner;

static VAStatus observer_codec_end(struct v4l2r_context *ctx)
{
    if (atomic_load(&block_codec)) {
        atomic_store(&codec_entered, true);
        while (!atomic_load(&release_codec)) sched_yield();
    }
    if (reference_id != VA_INVALID_ID)
        assert(v4l2r_surface_timestamp(ctx, reference_id));
    return codec_end(ctx);
}
static struct v4l2r_codec observed_codec;
static void start(void)
{
    setup();
    observed_codec = codec;
    observed_codec.end_picture = observer_codec_end;
    V4L2R_CONFIG(drv, cfg)->codec = &observed_codec;
    cid = context(); sid = surface();
    assert(picture(cid, sid) == VA_STATUS_SUCCESS);
    assert(v4l2r_observer_open(&va, cid, &session) == VA_STATUS_SUCCESS);
    assert(v4l2r_observer_select(&va, &session, sid, &target) == VA_STATUS_SUCCESS);
}
static void begin(void)
{
    assert(v4l2r_observer_begin(&va, &session, &target, 0, &receipt) == VA_STATUS_SUCCESS);
    assert(receipt.lease && receipt.completed == receipt.submitted);
    assert(receipt.target.writer == target.writer && receipt.target.surface == sid);
    assert(receipt.session.nonce == session.nonce && receipt.planes == 1);
    assert(receipt.plane_size[0] >= 64 * 96);
}
static void end(void)
{
    assert(v4l2r_observer_end(&va, &session, receipt.lease) == VA_STATUS_SUCCESS);
}
static void *foreign(void *unused)
{
    (void)unused;
    for (unsigned i = 0; i < 40; i++) {
        struct v4l2r_observer_receipt other;
        assert(v4l2r_observer_begin(&va, &session, &target, 0, &other) != VA_STATUS_SUCCESS);
        assert(v4l2r_observer_end(&va, &session, receipt.lease) != VA_STATUS_SUCCESS);
        assert(table.vaBeginPicture(&va, cid, sid) == VA_STATUS_ERROR_OPERATION_FAILED);
        assert(table.vaRenderPicture(&va, cid, NULL, 0) == VA_STATUS_ERROR_OPERATION_FAILED);
        assert(table.vaEndPicture(&va, cid) == VA_STATUS_ERROR_OPERATION_FAILED);
        assert(table.vaDestroyContext(&va, cid) == VA_STATUS_ERROR_OPERATION_FAILED);
        assert(table.vaDestroySurfaces(&va, &sid, 1) == VA_STATUS_ERROR_OPERATION_FAILED);
        VAContextID new_id;
        assert(table.vaCreateContext(&va, cfg, 64, 64, 0, NULL, 0, &new_id) == VA_STATUS_ERROR_OPERATION_FAILED);
        VADRMPRIMESurfaceDescriptor desc;
        VAImage image;
        assert(table.vaExportSurfaceHandle(&va, sid, VA_SURFACE_ATTRIB_MEM_TYPE_DRM_PRIME_2, 0, &desc) == VA_STATUS_ERROR_OPERATION_FAILED);
        assert(table.vaDeriveImage(&va, sid, &image) == VA_STATUS_ERROR_OPERATION_FAILED);
        assert(table.vaGetImage(&va, sid, 0, 0, 64, 64, VA_INVALID_ID) == VA_STATUS_ERROR_OPERATION_FAILED);
        assert(table.vaPutImage(&va, sid, VA_INVALID_ID, 0, 0, 64, 64, 0, 0, 64, 64) == VA_STATUS_ERROR_OPERATION_FAILED);
        assert(v4l2r_Terminate(&va) == VA_STATUS_ERROR_OPERATION_FAILED);
    }
    return NULL;
}
static void lifecycle(void)
{
    setup(); cid = context(); sid = surface();
    /* No session: default-off refuses even a successfully submitted surface. */
    assert(picture(cid, sid) == VA_STATUS_SUCCESS);
    assert(v4l2r_observer_begin(&va, &session, &target, 0, &receipt) != VA_STATUS_SUCCESS);
    assert(v4l2r_observer_open(&va, cid, &session) == VA_STATUS_SUCCESS);
    struct v4l2r_observer_session duplicate;
    assert(v4l2r_observer_open(&va, cid, &duplicate) != VA_STATUS_SUCCESS);
    assert(v4l2r_observer_select(&va, &session, sid, &target) == VA_STATUS_SUCCESS);
    assert(target.writer == 1 && target.allocation_generation && target.surface_generation);
    begin();
    struct resources before = resources();
    unsigned before_queues = queues;
    assert(v4l2r_observer_close(&va, &session) != VA_STATUS_SUCCESS);
    assert(v4l2r_observer_end(&va, &session, receipt.lease + 1) != VA_STATUS_SUCCESS);
    duplicate = session; duplicate.nonce++;
    assert(v4l2r_observer_end(&va, &duplicate, receipt.lease) != VA_STATUS_SUCCESS);
    pthread_t t; assert(!pthread_create(&t, NULL, foreign, NULL)); assert(!pthread_join(t, NULL));
    assert_resources(before); assert(queues == before_queues);
    uint64_t old_lease = receipt.lease;
    assert(v4l2r_observer_begin(&va, &session, &target, 0, &receipt) != VA_STATUS_SUCCESS);
    assert(receipt.lease == old_lease); /* refusal cannot erase the only end token */
    end();
    assert(v4l2r_observer_end(&va, &session, old_lease) != VA_STATUS_SUCCESS);
    begin();
    assert(receipt.lease != old_lease);
    assert(v4l2r_observer_end(&va, &session, old_lease) != VA_STATUS_SUCCESS);
    end();
    assert(picture(cid, sid) == VA_STATUS_SUCCESS);
    assert(v4l2r_observer_begin(&va, &session, &target, 0, &receipt) != VA_STATUS_SUCCESS);
    struct v4l2r_observer_target old = target;
    assert(v4l2r_observer_select(&va, &session, sid, &target) == VA_STATUS_SUCCESS);
    assert(target.writer == 2 && target.allocation_generation == old.allocation_generation);
    begin(); end();
    assert(table.vaDestroySurfaces(&va, &sid, 1) == VA_STATUS_SUCCESS);
    sid = surface();
    assert(sid == old.surface); /* force numerical-handle ABA */
    assert(picture(cid, sid) == VA_STATUS_SUCCESS);
    assert(v4l2r_observer_begin(&va, &session, &old, 0, &receipt) != VA_STATUS_SUCCESS);
    assert(v4l2r_observer_select(&va, &session, sid, &target) == VA_STATUS_SUCCESS);
    assert(target.surface_generation != old.surface_generation);
    assert(target.allocation_generation == old.allocation_generation); /* actual CAPTURE recycle */
    begin(); end();
    assert(v4l2r_observer_close(&va, &session) == VA_STATUS_SUCCESS);
    duplicate = session;
    assert(v4l2r_observer_open(&va, cid, &session) == VA_STATUS_SUCCESS);
    assert(session.nonce != duplicate.nonce);
    assert(v4l2r_observer_begin(&va, &duplicate, &target, 0, &receipt) != VA_STATUS_SUCCESS);
    assert(table.vaDestroyContext(&va, cid) == VA_STATUS_SUCCESS);
    cid = context();
    assert(cid == duplicate.context);
    assert(v4l2r_observer_select(&va, &session, sid, &target) != VA_STATUS_SUCCESS);
    assert(v4l2r_observer_close(&va, &session) != VA_STATUS_SUCCESS);
    assert(v4l2r_observer_open(&va, cid, &duplicate) == VA_STATUS_SUCCESS);
    assert(duplicate.context_generation != session.context_generation);
    teardown();
}
static void readers(void)
{
    start(); reference_id = sid;
    VASurfaceID second = surface();
    assert(picture(cid, second) == VA_STATUS_SUCCESS);
    reference_id = VA_INVALID_ID;
    struct v4l2r_context *ctx = V4L2R_CONTEXT(drv, cid);
    assert(!ctx->pic.target); /* do not select the cleared current-picture pointer */
    assert(ctx->captures[0].last_ref_seq == 2);
    begin();
    assert(receipt.submitted == 2 && receipt.completed == 2 && receipt.last_reference == 2);
    assert(receipt.target.writer == 1 && receipt.capture_index == 0);
    end(); teardown();
}
static void alias(const char *mode)
{
    start();
    if (!strcmp(mode, "derive")) {
        VAImage image;
        assert(table.vaDeriveImage(&va, sid, &image) == VA_STATUS_SUCCESS);
        assert(v4l2r_DestroyImage(&va, image.image_id) == VA_STATUS_SUCCESS);
    } else {
        VADRMPRIMESurfaceDescriptor desc;
        assert(table.vaExportSurfaceHandle(&va, sid, VA_SURFACE_ATTRIB_MEM_TYPE_DRM_PRIME_2, 0, &desc) == VA_STATUS_SUCCESS);
        close_export(&desc);
    }
    assert(v4l2r_observer_begin(&va, &session, &target, 0, &receipt) != VA_STATUS_SUCCESS);
    assert(table.vaDestroySurfaces(&va, &sid, 1) == VA_STATUS_SUCCESS);
    sid = surface();
    assert(picture(cid, sid) == VA_STATUS_SUCCESS);
    /* Sticky allocation history must survive recycling and closing a VA alias. */
    assert(v4l2r_observer_select(&va, &session, sid, &target) != VA_STATUS_SUCCESS);
    teardown();
}
static void upload(void)
{
    start();
    VAImageFormat fmt = {.fourcc = VA_FOURCC_NV12};
    VAImage image;
    assert(v4l2r_CreateImage(&va, &fmt, 64, 64, &image) == VA_STATUS_SUCCESS);
    assert(table.vaPutImage(&va, sid, image.image_id, 0, 0, 64, 64, 0, 0, 64, 64) == VA_STATUS_SUCCESS);
    assert(v4l2r_DestroyImage(&va, image.image_id) == VA_STATUS_SUCCESS);
    assert(v4l2r_observer_begin(&va, &session, &target, 0, &receipt) != VA_STATUS_SUCCESS);
    assert(v4l2r_observer_select(&va, &session, sid, &target) != VA_STATUS_SUCCESS);
    assert(picture(cid, sid) == VA_STATUS_SUCCESS);
    assert(v4l2r_observer_select(&va, &session, sid, &target) == VA_STATUS_SUCCESS);
    begin(); end(); teardown();
}
static void trace_join(void)
{
#if HAVE_V4L2_CTRL_HEVC
    start();
    FILE *sink = tmpfile(); assert(sink);
    v4l2r_hevc_trace_configure(&(struct v4l2r_hevc_trace_options){.enable = true, .sink = sink});
    struct v4l2_ctrl_hevc_decode_params params = {0};
    struct v4l2r_context *ctx = V4L2R_CONTEXT(drv, cid);
    /* The payload is fake; the tracer and queue-derived identities are real. */
    v4l2r_hevc_trace_request(ctx, &(struct v4l2r_hevc_trace_request){
        .decode_params = &params, .target_index = 0, .first_slice = true, .last_slice = true,
        .picture = 1, .request = 1});
    begin();
    char expected[512], line[8192];
    snprintf(expected, sizeof(expected),
        "\"observer\":{\"run\":\"%016llx%016llx\",\"context\":%llu,\"allocation\":%llu,\"surface\":%llu,\"writer\":%llu}",
        (unsigned long long)receipt.session.run[0], (unsigned long long)receipt.session.run[1],
        (unsigned long long)receipt.session.context_generation,
        (unsigned long long)receipt.target.allocation_generation,
        (unsigned long long)receipt.target.surface_generation, (unsigned long long)receipt.target.writer);
    rewind(sink); assert(fgets(line, sizeof(line), sink)); assert(strstr(line, expected));
    assert(!fgets(line, sizeof(line), sink));
    v4l2r_hevc_trace_configure(&(struct v4l2r_hevc_trace_options){.enable = false});
    fclose(sink); end(); teardown();
#else
    assert(!"trace-join requires HEVC UAPI headers");
#endif
}
static void *producer(void *unused)
{
    (void)unused;
    assert(picture(cid, sid) == VA_STATUS_SUCCESS);
    return NULL;
}
static void contention(void)
{
    start();
    atomic_store(&block_codec, true);
    pthread_t t; assert(!pthread_create(&t, NULL, producer, NULL));
    while (!atomic_load(&codec_entered)) sched_yield();
    uint64_t start_ns = v4l2r_now_ns();
    assert(v4l2r_observer_begin(&va, &session, &target, start_ns + 10000000, &receipt) != VA_STATUS_SUCCESS);
    assert(v4l2r_now_ns() - start_ns < 500000000);
    atomic_store(&release_codec, true);
    assert(!pthread_join(t, NULL));
    atomic_store(&block_codec, false);
    assert(v4l2r_observer_begin(&va, &session, &target, 0, &receipt) != VA_STATUS_SUCCESS);
    assert(v4l2r_observer_select(&va, &session, sid, &target) == VA_STATUS_SUCCESS);
    begin(); end(); teardown();
}
static void *cancellable_owner(void *unused)
{
    (void)unused;
    assert(v4l2r_observer_open(&va, cid, &session) == VA_STATUS_SUCCESS);
    assert(v4l2r_observer_select(&va, &session, sid, &target) == VA_STATUS_SUCCESS);
    begin();
    atomic_store(&owner_ready, true);
    while (!atomic_load(&release_owner)) sched_yield();
    end();
    pthread_testcancel();
    return NULL;
}
static void cancellation(void)
{
    setup(); cid = context(); sid = surface(); assert(picture(cid, sid) == VA_STATUS_SUCCESS);
    pthread_t t; assert(!pthread_create(&t, NULL, cancellable_owner, NULL));
    while (!atomic_load(&owner_ready)) sched_yield();
    assert(!pthread_cancel(t));
    assert(table.vaDestroyContext(&va, cid) == VA_STATUS_ERROR_OPERATION_FAILED);
    atomic_store(&release_owner, true);
    void *result; assert(!pthread_join(t, &result)); assert(result == PTHREAD_CANCELED);
    assert(!drv->observer_active);
    assert(picture(cid, sid) == VA_STATUS_SUCCESS);
    teardown();
}
static void unsupported(const char *mode)
{
    setup(); sid = surface();
    if (!strcmp(mode, "vpp")) {
        V4L2R_CONFIG(drv, cfg)->codec = NULL;
        V4L2R_CONFIG(drv, cfg)->profile = VAProfileNone;
    } else {
        VADRMPRIMESurfaceDescriptor desc;
        assert(table.vaExportSurfaceHandle(&va, sid, VA_SURFACE_ATTRIB_MEM_TYPE_DRM_PRIME_2, 0, &desc) == VA_STATUS_SUCCESS);
        close_export(&desc);
    }
    cid = context();
    if (strcmp(mode, "vpp")) assert(picture(cid, sid) == VA_STATUS_SUCCESS);
    assert(v4l2r_observer_open(&va, cid, &session) == VA_STATUS_SUCCESS);
    assert(v4l2r_observer_select(&va, &session, sid, &target) != VA_STATUS_SUCCESS);
    assert(v4l2r_observer_begin(&va, &session, &target, 0, &receipt) != VA_STATUS_SUCCESS);
    teardown();
}
static void foreign_display(void)
{
    start();
    struct VADriverContext first_va = va;
    struct v4l2r_driver *first_drv = drv;
    struct v4l2r_observer_session first_session = session;
    VAConfigID first_cfg = cfg;
    setup(); VAContextID other_id = context();
    assert(v4l2r_observer_begin(&va, &first_session, &target, 0, &receipt) != VA_STATUS_SUCCESS);
    assert(v4l2r_observer_open(&va, other_id, &session) == VA_STATUS_SUCCESS);
    assert(memcmp(session.run, first_session.run, sizeof(session.run)));
    assert(v4l2r_observer_begin(&first_va, &session, &target, 0, &receipt) != VA_STATUS_SUCCESS);
    assert(v4l2r_Terminate(&va) == VA_STATUS_SUCCESS);
    va = first_va; drv = first_drv; cfg = first_cfg;
    teardown();
}
static void *open_then_exit(void *unused)
{
    (void)unused;
    assert(v4l2r_observer_open(&va, cid, &session) == VA_STATUS_SUCCESS);
    return NULL;
}
static void *try_dead_owner(void *unused)
{
    (void)unused;
    assert(v4l2r_observer_select(&va, &session, sid, &target) != VA_STATUS_SUCCESS);
    assert(v4l2r_observer_close(&va, &session) != VA_STATUS_SUCCESS);
    return NULL;
}
static void owner_reuse(void)
{
    setup(); cid = context(); sid = surface(); assert(picture(cid, sid) == VA_STATUS_SUCCESS);
    pthread_t first, next;
    assert(!pthread_create(&first, NULL, open_then_exit, NULL)); assert(!pthread_join(first, NULL));
    assert(!pthread_create(&next, NULL, try_dead_owner, NULL)); assert(!pthread_join(next, NULL));
    teardown();
}
static void refused(const char *mode)
{
    if (!strcmp(mode, "conversion")) packed = true;
    if (!strcmp(mode, "partial-queue")) hold = true;
    start();
    if (!strcmp(mode, "partial-queue")) {
        sliced = true;
        assert(table.vaBeginPicture(&va, cid, surface()) == VA_STATUS_SUCCESS);
        unsigned char first_only = 1;
        VABufferID buffer;
        assert(v4l2r_CreateBuffer(&va, cid, VASliceDataBufferType, 1, 1, &first_only, &buffer) == VA_STATUS_SUCCESS);
        assert(table.vaRenderPicture(&va, cid, &buffer, 1) == VA_STATUS_SUCCESS);
    } else if (!strcmp(mode, "partial")) {
        assert(table.vaBeginPicture(&va, cid, surface()) == VA_STATUS_SUCCESS);
    } else if (!strcmp(mode, "contexts")) {
        (void)context();
    } else if (!strcmp(mode, "failed-queue")) {
        inject(MEDIA_REQUEST_IOC_QUEUE, -1, 1, EIO);
        assert(picture(cid, sid) != VA_STATUS_SUCCESS);
        armed = false;
    } else if (!strcmp(mode, "failed-decode")) {
        capture_flags = V4L2_BUF_FLAG_ERROR;
    } else if (!strcmp(mode, "timeout") || !strcmp(mode, "eintr")) {
        fast_clock = true; dequeue_blocked = true;
        if (!strcmp(mode, "eintr")) { poll_error = EINTR; poll_error_count = 10000; }
    } else if (!strcmp(mode, "expired")) {
        assert(v4l2r_observer_begin(&va, &session, &target, 1, &receipt) != VA_STATUS_SUCCESS);
        begin(); end(); teardown(); return;
    } else if (strcmp(mode, "conversion")) abort();
    assert(v4l2r_observer_begin(&va, &session, &target, 0, &receipt) != VA_STATUS_SUCCESS);
    assert(!drv->observer_active && !receipt.lease);
    fast_clock = false; dequeue_blocked = false; poll_error = poll_error_count = 0;
    capture_flags = 0;
    teardown();
}
int main(int argc, char **argv)
{
    assert(argc == 2);
    if (!strcmp(argv[1], "lifecycle")) lifecycle();
    else if (!strcmp(argv[1], "readers")) readers();
    else if (!strcmp(argv[1], "upload")) upload();
    else if (!strcmp(argv[1], "trace-join")) trace_join();
    else if (!strcmp(argv[1], "export") || !strcmp(argv[1], "derive")) alias(argv[1]);
    else if (!strcmp(argv[1], "contention")) contention();
    else if (!strcmp(argv[1], "cancellation")) cancellation();
    else if (!strcmp(argv[1], "import") || !strcmp(argv[1], "vpp")) unsupported(argv[1]);
    else if (!strcmp(argv[1], "foreign-display")) foreign_display();
    else if (!strcmp(argv[1], "owner-reuse")) owner_reuse();
    else refused(argv[1]);
    printf("PASS actual driver observer %s (fake V4L2, no device)\n", argv[1]);
    return 0;
}
