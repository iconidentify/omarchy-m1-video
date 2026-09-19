/* SPDX-License-Identifier: GPL-2.0-only */
#define _GNU_SOURCE
#include <assert.h>
#include <dlfcn.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <unistd.h>
#include <va/va_backend.h>

#include "libavutil/buffer.h"
#include "libavutil/frame.h"
#include "libavutil/hwcontext.h"
#include "libavutil/hwcontext_vaapi.h"
#include "libavcodec/avcodec.h"
#include "libavcodec/internal.h"
#include "libavcodec/vaapi_decode.h"

enum {
    MODE_NORMAL, MODE_WRONG_SURFACE, MODE_END_ONCE, MODE_END_ALWAYS,
    MODE_SNAPSHOT_FAIL, MODE_BAD_ABI, MODE_WRONG_RECEIPT, MODE_CLOSE_ONCE,
};
struct fake_counts {
    unsigned open, select, begin, snapshot, end, close;
    unsigned destroy_context, destroy_config;
    unsigned copy_true, copy_false;
};
typedef void (*reset_fn)(void);
typedef void (*mode_fn)(int);
typedef struct fake_counts (*counts_fn)(void);

struct fixture {
    void *module;
    reset_fn reset;
    mode_fn set_mode;
    counts_fn get_counts;
    AVCodecContext avctx;
    AVCodecInternal internal;
    VAAPIDecodeContext decode;
    AVVAAPIDeviceContext hwctx;
    struct VADisplayContext display;
    struct VADriverContext driver;
    struct VADriverVTable vtable;
};

static VAStatus local_end_picture(VADriverContextP driver, VAContextID context)
{
    (void)driver;
    (void)context;
    return VA_STATUS_SUCCESS;
}

static void *symbol(void *module, const char *name)
{
    void *value = dlsym(module, name);
    assert(value);
    return value;
}

static void fixture_init(struct fixture *f, const char *module_path)
{
    memset(f, 0, sizeof(*f));
    f->module = dlopen(module_path, RTLD_NOW | RTLD_LOCAL);
    assert(f->module);
    *(void **)(&f->reset) = symbol(f->module, "fake_reset");
    *(void **)(&f->set_mode) = symbol(f->module, "fake_set_mode");
    *(void **)(&f->get_counts) = symbol(f->module, "fake_get_counts");
    *(void **)(&f->vtable.vaEndPicture) = symbol(f->module, "fake_end_picture");
    *(void **)(&f->vtable.vaDestroyContext) = symbol(f->module, "fake_destroy_context");
    *(void **)(&f->vtable.vaDestroyConfig) = symbol(f->module, "fake_destroy_config");
    f->reset();

    f->driver.pDriverData = f;
    f->driver.vtable = &f->vtable;
    f->display.vadpy_magic = VA_DISPLAY_MAGIC;
    f->display.pDriverContext = &f->driver;
    assert(vaDisplayIsValid(&f->display));

    f->hwctx.display = &f->display;
    f->decode.hwctx = &f->hwctx;
    f->decode.va_context = 7;
    f->decode.va_config = 8;
    f->internal.hwaccel_priv_data = &f->decode;
    f->avctx.internal = &f->internal;
    f->avctx.codec_id = AV_CODEC_ID_HEVC;
    f->avctx.pix_fmt = AV_PIX_FMT_VAAPI;
    f->avctx.thread_count = 1;
}

static AVFrame *frame(VASurfaceID surface)
{
    AVFrame *value = av_frame_alloc();
    assert(value);
    value->buf[0] = av_buffer_alloc(1);
    assert(value->buf[0]);
    value->data[0] = value->buf[0]->data;
    value->data[3] = (uint8_t *)(uintptr_t)surface;
    value->format = AV_PIX_FMT_VAAPI;
    return value;
}

static int output(struct fixture *f, VASurfaceID surface)
{
    AVFrame *value = frame(surface);
    int ret = ff_vaapi_decode_observer_output(&f->avctx, value);
    av_frame_free(&value);
    return ret;
}

struct output_call {
    struct fixture *fixture;
    VASurfaceID surface;
    int ret;
};

struct report_call {
    struct fixture *fixture;
    const char *path;
    int ret;
};

static void *foreign_output(void *opaque)
{
    struct output_call *call = opaque;
    call->ret = output(call->fixture, call->surface);
    return NULL;
}

static void *foreign_report(void *opaque)
{
    struct report_call *call = opaque;
    call->ret = ff_vaapi_decode_observer_write_report(&call->fixture->avctx,
                                                       call->path);
    return NULL;
}

static int path_exists(const char *path)
{
    struct stat status;
    return !stat(path, &status);
}

static void destroy(struct fixture *f, int expected)
{
    int ret = ff_vaapi_decode_uninit(&f->avctx);
    assert((ret < 0) == (expected < 0));
    dlclose(f->module);
}

static void success(const char *module, int copy)
{
    struct fixture f;
    struct fake_counts counts;
    VAAPIObserverResult result;
    fixture_init(&f, module);
    assert(ff_vaapi_decode_observer_arm(&f.avctx, "1,3", copy) == 0);
    assert(output(&f, 40) == 0);
    assert(output(&f, 41) == 0);
    assert(output(&f, 42) == 0);
    assert(output(&f, 43) == 0);
    assert(ff_vaapi_decode_observer_result(&f.avctx, &result) < 0);
    assert(ff_vaapi_decode_observer_finish(&f.avctx) == 0);
    assert(ff_vaapi_decode_observer_result(&f.avctx, &result) == 0);
    assert(result.count == 2);
    assert(result.slot[0].output_index == 1 && result.slot[0].surface == 41);
    assert(result.slot[1].output_index == 3 && result.slot[1].surface == 43);
    assert(result.slot[0].copied == copy && result.slot[1].copied == copy);
    unsigned digest_bytes = 0;
    for (unsigned i = 0; i < sizeof(result.slot[0].sha256); i++)
        digest_bytes += !!result.slot[0].sha256[i];
    assert(copy ? digest_bytes != 0 : digest_bytes == 0);
    counts = f.get_counts();
    assert(counts.open == 1 && counts.select == 2 && counts.begin == 2);
    assert(counts.snapshot == 2 && counts.end == 2 && counts.close == 1);
    assert(copy ? counts.copy_true == 2 : counts.copy_false == 2);
    destroy(&f, 0);
}

static void report_success(const char *module, const char *path, int copy)
{
    struct fixture f;
    struct stat status;

    fixture_init(&f, module);
    assert(ff_vaapi_decode_observer_arm(&f.avctx, "1,3", copy) == 0);
    assert(output(&f, 40) == 0);
    assert(output(&f, 41) == 0);
    assert(output(&f, 42) == 0);
    assert(output(&f, 43) == 0);
    assert(ff_vaapi_decode_observer_write_report(&f.avctx, path) == 0);
    assert(!stat(path, &status));
    assert((status.st_mode & 0777) == 0600);
    destroy(&f, 0);
}

int main(int argc, char **argv)
{
    struct fixture f;
    struct fake_counts counts;
    const char *report = argc == 4 ? argv[3] : NULL;
    assert(argc == 3 || argc == 4);

    if (!strcmp(argv[2], "success-off")) {
        success(argv[1], 0);
    } else if (!strcmp(argv[2], "success-on")) {
        success(argv[1], 1);
    } else if (!strcmp(argv[2], "report-off")) {
        assert(report);
        report_success(argv[1], report, 0);
    } else if (!strcmp(argv[2], "report-on")) {
        assert(report);
        report_success(argv[1], report, 1);
    } else if (!strcmp(argv[2], "report-default-off")) {
        fixture_init(&f, argv[1]);
        assert(report && !path_exists(report));
        assert(ff_vaapi_decode_observer_write_report(&f.avctx, report) < 0);
        assert(!path_exists(report));
        destroy(&f, 0);
    } else if (!strcmp(argv[2], "report-incomplete")) {
        fixture_init(&f, argv[1]);
        assert(report && !path_exists(report));
        assert(ff_vaapi_decode_observer_arm(&f.avctx, "4", 0) == 0);
        assert(output(&f, 64) == 0);
        assert(ff_vaapi_decode_observer_write_report(&f.avctx, report) < 0);
        assert(!path_exists(report));
        destroy(&f, -1);
    } else if (!strcmp(argv[2], "report-sticky")) {
        fixture_init(&f, argv[1]);
        assert(report && !path_exists(report));
        assert(ff_vaapi_decode_observer_arm(&f.avctx, "0", 0) == 0);
        assert(output(&f, 68) == 0);
        assert(ff_vaapi_decode_observer_finish(&f.avctx) == 0);
        assert(output(&f, 69) < 0);
        assert(ff_vaapi_decode_observer_write_report(&f.avctx, report) < 0);
        assert(!path_exists(report));
        destroy(&f, -1);
    } else if (!strcmp(argv[2], "report-end-persistent")) {
        fixture_init(&f, argv[1]);
        assert(report && !path_exists(report));
        f.set_mode(MODE_END_ALWAYS);
        assert(ff_vaapi_decode_observer_arm(&f.avctx, "0", 1) == 0);
        assert(output(&f, 67) < 0);
        assert(ff_vaapi_decode_observer_write_report(&f.avctx, report) < 0);
        assert(!path_exists(report));
        assert(ff_vaapi_decode_uninit(&f.avctx) < 0);
        counts = f.get_counts();
        assert(!counts.destroy_context && !counts.destroy_config);
        f.set_mode(MODE_NORMAL);
        assert(ff_vaapi_decode_uninit(&f.avctx) < 0);
        counts = f.get_counts();
        assert(counts.destroy_context == 1 && counts.destroy_config == 1);
        dlclose(f.module);
    } else if (!strcmp(argv[2], "report-close-failure")) {
        fixture_init(&f, argv[1]);
        assert(report && !path_exists(report));
        f.set_mode(MODE_CLOSE_ONCE);
        assert(ff_vaapi_decode_observer_arm(&f.avctx, "0", 0) == 0);
        assert(output(&f, 74) == 0);
        assert(ff_vaapi_decode_observer_write_report(&f.avctx, report) < 0);
        assert(!path_exists(report));
        counts = f.get_counts();
        assert(counts.close == 1);
        destroy(&f, 0);
    } else if (!strcmp(argv[2], "report-preexisting")) {
        fixture_init(&f, argv[1]);
        assert(report && path_exists(report));
        assert(ff_vaapi_decode_observer_arm(&f.avctx, "0", 0) == 0);
        assert(output(&f, 71) == 0);
        assert(ff_vaapi_decode_observer_write_report(&f.avctx, report) < 0);
        assert(path_exists(report));
        destroy(&f, 0);
    } else if (!strcmp(argv[2], "report-write-failure")) {
        struct rlimit old_limit, limit;
        fixture_init(&f, argv[1]);
        assert(report && !path_exists(report));
        assert(ff_vaapi_decode_observer_arm(&f.avctx, "0", 1) == 0);
        assert(output(&f, 72) == 0);
        assert(!getrlimit(RLIMIT_FSIZE, &old_limit));
        limit = old_limit;
        limit.rlim_cur = 1;
        assert(signal(SIGXFSZ, SIG_IGN) != SIG_ERR);
        assert(!setrlimit(RLIMIT_FSIZE, &limit));
        assert(ff_vaapi_decode_observer_write_report(&f.avctx, report) < 0);
        assert(!setrlimit(RLIMIT_FSIZE, &old_limit));
        assert(!path_exists(report));
        destroy(&f, 0);
    } else if (!strcmp(argv[2], "foreign-report")) {
        pthread_t thread;
        struct report_call call = {.fixture = &f, .path = report};
        fixture_init(&f, argv[1]);
        assert(report && !path_exists(report));
        assert(ff_vaapi_decode_observer_arm(&f.avctx, "0", 0) == 0);
        assert(output(&f, 73) == 0);
        assert(!pthread_create(&thread, NULL, foreign_report, &call));
        assert(!pthread_join(thread, NULL));
        assert(call.ret < 0);
        assert(!path_exists(report));
        destroy(&f, 0);
    } else if (!strcmp(argv[2], "default-off")) {
        fixture_init(&f, argv[1]);
        assert(ff_vaapi_decode_observer_arm(&f.avctx, NULL, 0) == 0);
        assert(output(&f, 50) == 0);
        counts = f.get_counts();
        assert(!counts.open && !counts.select && !counts.snapshot);
        destroy(&f, 0);
    } else if (!strcmp(argv[2], "invalid-display")) {
        fixture_init(&f, argv[1]);
        f.display.vadpy_magic = 0;
        assert(ff_vaapi_decode_observer_arm(&f.avctx, "0", 0) < 0);
        counts = f.get_counts();
        assert(!counts.open);
        f.display.vadpy_magic = VA_DISPLAY_MAGIC;
        destroy(&f, 0);
    } else if (!strcmp(argv[2], "wrong-origin")) {
        fixture_init(&f, argv[1]);
        f.vtable.vaEndPicture = local_end_picture;
        assert(ff_vaapi_decode_observer_arm(&f.avctx, "0", 0) < 0);
        assert(!f.get_counts().open);
        destroy(&f, 0);
    } else if (!strcmp(argv[2], "late-arm")) {
        fixture_init(&f, argv[1]);
        f.decode.observer_issued = 1;
        assert(ff_vaapi_decode_observer_arm(&f.avctx, "0", 0) < 0);
        assert(!f.get_counts().open);
        destroy(&f, 0);
    } else if (!strcmp(argv[2], "threaded-reject")) {
        fixture_init(&f, argv[1]);
        f.avctx.thread_count = 2;
        f.avctx.active_thread_type = FF_THREAD_FRAME;
        assert(ff_vaapi_decode_observer_arm(&f.avctx, "0", 0) < 0);
        assert(!f.get_counts().open);
        destroy(&f, 0);
    } else if (!strcmp(argv[2], "bad-abi")) {
        fixture_init(&f, argv[1]);
        f.set_mode(MODE_BAD_ABI);
        assert(ff_vaapi_decode_observer_arm(&f.avctx, "0", 0) < 0);
        assert(!f.get_counts().open);
        destroy(&f, 0);
    } else if (!strcmp(argv[2], "duplicate")) {
        fixture_init(&f, argv[1]);
        assert(ff_vaapi_decode_observer_arm(&f.avctx, "2,2", 0) < 0);
        assert(!f.get_counts().open);
        destroy(&f, 0);
    } else if (!strcmp(argv[2], "foreign-owner")) {
        pthread_t thread;
        struct output_call call = {.fixture = &f, .surface = 60};
        fixture_init(&f, argv[1]);
        assert(ff_vaapi_decode_observer_arm(&f.avctx, "0", 0) == 0);
        assert(!pthread_create(&thread, NULL, foreign_output, &call));
        assert(!pthread_join(thread, NULL));
        assert(call.ret < 0);
        counts = f.get_counts();
        assert(!counts.select && !counts.begin && !counts.end);
        assert(ff_vaapi_decode_observer_finish(&f.avctx) < 0);
        destroy(&f, -1);
    } else if (!strcmp(argv[2], "wrong-surface")) {
        fixture_init(&f, argv[1]);
        f.set_mode(MODE_WRONG_SURFACE);
        assert(ff_vaapi_decode_observer_arm(&f.avctx, "0", 0) == 0);
        assert(output(&f, 61) < 0);
        counts = f.get_counts();
        assert(counts.select == 1 && !counts.begin && !counts.end);
        assert(ff_vaapi_decode_observer_finish(&f.avctx) < 0);
        destroy(&f, -1);
    } else if (!strcmp(argv[2], "end-retry")) {
        fixture_init(&f, argv[1]);
        f.set_mode(MODE_END_ONCE);
        assert(ff_vaapi_decode_observer_arm(&f.avctx, "0", 1) == 0);
        assert(output(&f, 62) < 0);
        counts = f.get_counts();
        assert(counts.snapshot == 1 && counts.end == 1 && !counts.close);
        assert(ff_vaapi_decode_observer_finish(&f.avctx) < 0);
        counts = f.get_counts();
        assert(counts.end == 2 && counts.close == 1);
        destroy(&f, -1);
    } else if (!strcmp(argv[2], "receipt-mismatch")) {
        fixture_init(&f, argv[1]);
        f.set_mode(MODE_WRONG_RECEIPT);
        assert(ff_vaapi_decode_observer_arm(&f.avctx, "0", 0) == 0);
        assert(output(&f, 65) < 0);
        counts = f.get_counts();
        assert(counts.begin == 1 && counts.end == 1 && !counts.snapshot);
        assert(ff_vaapi_decode_observer_finish(&f.avctx) < 0);
        destroy(&f, -1);
    } else if (!strcmp(argv[2], "snapshot-failure")) {
        fixture_init(&f, argv[1]);
        f.set_mode(MODE_SNAPSHOT_FAIL);
        assert(ff_vaapi_decode_observer_arm(&f.avctx, "0", 1) == 0);
        assert(output(&f, 63) < 0);
        counts = f.get_counts();
        assert(counts.snapshot == 1 && counts.end == 1);
        assert(ff_vaapi_decode_observer_finish(&f.avctx) < 0);
        destroy(&f, -1);
    } else if (!strcmp(argv[2], "flush-retry")) {
        fixture_init(&f, argv[1]);
        f.set_mode(MODE_END_ONCE);
        assert(ff_vaapi_decode_observer_arm(&f.avctx, "0", 1) == 0);
        assert(output(&f, 66) < 0);
        ff_vaapi_decode_observer_flush(&f.avctx);
        counts = f.get_counts();
        assert(counts.end == 2 && counts.close == 1);
        destroy(&f, -1);
    } else if (!strcmp(argv[2], "uninit-retry")) {
        fixture_init(&f, argv[1]);
        f.set_mode(MODE_END_ALWAYS);
        assert(ff_vaapi_decode_observer_arm(&f.avctx, "0", 1) == 0);
        assert(output(&f, 67) < 0);
        assert(ff_vaapi_decode_uninit(&f.avctx) < 0);
        counts = f.get_counts();
        assert(counts.end == 2 && !counts.close);
        assert(!counts.destroy_context && !counts.destroy_config);
        f.set_mode(MODE_NORMAL);
        assert(ff_vaapi_decode_uninit(&f.avctx) < 0);
        counts = f.get_counts();
        assert(counts.end == 3 && counts.close == 1);
        assert(counts.destroy_context == 1 && counts.destroy_config == 1);
        dlclose(f.module);
    } else if (!strcmp(argv[2], "incomplete")) {
        fixture_init(&f, argv[1]);
        assert(ff_vaapi_decode_observer_arm(&f.avctx, "4", 0) == 0);
        assert(output(&f, 64) == 0);
        assert(ff_vaapi_decode_observer_finish(&f.avctx) < 0);
        counts = f.get_counts();
        assert(!counts.select && counts.close == 1);
        destroy(&f, -1);
    } else if (!strcmp(argv[2], "post-finish-output")) {
        VAAPIObserverResult result;
        fixture_init(&f, argv[1]);
        assert(ff_vaapi_decode_observer_arm(&f.avctx, "0", 0) == 0);
        assert(output(&f, 68) == 0);
        assert(ff_vaapi_decode_observer_finish(&f.avctx) == 0);
        assert(ff_vaapi_decode_observer_result(&f.avctx, &result) == 0);
        assert(output(&f, 69) < 0);
        assert(ff_vaapi_decode_observer_result(&f.avctx, &result) < 0);
        counts = f.get_counts();
        assert(counts.select == 1 && counts.begin == 1 && counts.end == 1 &&
               counts.close == 1);
        destroy(&f, -1);
    } else if (!strcmp(argv[2], "close-retry")) {
        VAAPIObserverResult result;
        fixture_init(&f, argv[1]);
        f.set_mode(MODE_CLOSE_ONCE);
        assert(ff_vaapi_decode_observer_arm(&f.avctx, "0", 0) == 0);
        assert(output(&f, 70) == 0);
        assert(ff_vaapi_decode_observer_finish(&f.avctx) < 0);
        assert(ff_vaapi_decode_observer_result(&f.avctx, &result) < 0);
        counts = f.get_counts();
        assert(counts.end == 1 && counts.close == 1);
        assert(ff_vaapi_decode_observer_finish(&f.avctx) == 0);
        assert(ff_vaapi_decode_observer_result(&f.avctx, &result) == 0);
        counts = f.get_counts();
        assert(counts.close == 2);
        destroy(&f, 0);
    } else {
        assert(!"unknown case");
    }
    printf("PASS FFmpeg VA callsite %s\n", argv[2]);
    return 0;
}
