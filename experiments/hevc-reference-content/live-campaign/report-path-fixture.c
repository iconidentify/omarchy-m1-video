/* SPDX-License-Identifier: GPL-2.0-only */
/* Test-only report sink and copy tracer: real CLI, demux, decoder and cleanup; no VA.
 *
 * Linked into the pinned FFmpeg CLI with
 *   -Wl,--wrap=av_strdup,--wrap=ff_vaapi_decode_observer_write_report
 * so the experimental report option's ownership can be observed without a
 * device and without publishing a real observer record.
 *
 * A fully owned report path is duplicated exactly three times before the
 * decoder worker could use it:
 *   1. write_option()  - the parsed option string, freed by uninit_options()
 *   2. ist_add()       - the demuxer's copy, freed by ist_free()
 *   3. dec_open()      - the decoder's copy, freed by dec_free()
 * Copy 2 is the ownership step this fixture exists to hold in place: without
 * it, copy 3 reads the already freed copy 1.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct AVCodecContext;
char *__real_av_strdup(const char *value);

static unsigned path_copies;

char *__wrap_av_strdup(const char *value)
{
    const char *expected = getenv("OMARCHY_TEST_REPORT_PATH");
    const char *fail = getenv("OMARCHY_TEST_REPORT_OOM");
    char *copy;

    if (!value || !expected || strcmp(value, expected))
        return __real_av_strdup(value);

    path_copies++;
    if (fail && path_copies == (unsigned)atoi(fail)) {
        fprintf(stderr, "REPORT-PATH-COPY %u injected-failure\n", path_copies);
        return NULL;
    }
    copy = __real_av_strdup(value);
    fprintf(stderr, "REPORT-PATH-COPY %u %s\n", path_copies, copy ? "ok" : "oom");
    return copy;
}

int __wrap_ff_vaapi_decode_observer_write_report(struct AVCodecContext *context,
                                                 const char *path)
{
    const char *expected = getenv("OMARCHY_TEST_REPORT_PATH");

    if (!context || !expected || !path || strcmp(path, expected) ||
        path_copies != 3) {
        fputs("ASSERT: report-path-owned-through-worker\n", stderr);
        abort();
    }
    fputs("PASS actual CLI report path reached worker after option teardown\n", stderr);
    return 0;
}
