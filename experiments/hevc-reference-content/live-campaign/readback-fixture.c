/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual libavutil VAAPI device/frame entrypoints, synthetic VA calls, no device. */
#include <assert.h>
#include <errno.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include VAAPI_SOURCE

#define CHECK(condition, tag) do { if (!(condition)) { \
    fprintf(stderr, "ASSERT:%s\n", tag); abort(); } } while (0)
static unsigned derives, creates, reads, opens, surfaces;
static unsigned char pixels[64 * 32 * 3 / 2];

int __wrap_open(const char *path, int flags, ...)
{
    (void)path; (void)flags; ++opens; errno = EACCES; return -1;
}
int __wrap_open64(const char *path, int flags, ...)
{
    return __wrap_open(path, flags);
}

VAStatus vaCreateSurfaces(VADisplay display, unsigned format, unsigned width,
                         unsigned height, VASurfaceID *ids, unsigned count,
                         VASurfaceAttrib *attributes, unsigned n_attributes)
{
    (void)display; (void)format; (void)attributes; (void)n_attributes;
    CHECK(width == 64 && height == 32, "surface-geometry");
    for (unsigned i = 0; i < count; ++i) ids[i] = ++surfaces;
    return VA_STATUS_SUCCESS;
}
VAStatus vaDestroySurfaces(VADisplay display, VASurfaceID *ids, int count)
{
    (void)display; (void)ids; (void)count; return VA_STATUS_SUCCESS;
}
static void image_record(VAImage *image)
{
    *image = (VAImage){.image_id = 42, .buf = 43, .width = 64, .height = 32,
        .format = {.fourcc = VA_FOURCC_NV12, .byte_order = VA_LSB_FIRST, .bits_per_pixel = 12},
        .num_planes = 2, .pitches = {64, 64}, .offsets = {0, 64 * 32},
        .data_size = sizeof(pixels)};
}
VAStatus vaDeriveImage(VADisplay display, VASurfaceID surface, VAImage *image)
{
    (void)display; (void)surface; ++derives; image_record(image); return VA_STATUS_SUCCESS;
}
VAStatus vaCreateImage(VADisplay display, VAImageFormat *format, int width, int height, VAImage *image)
{
    (void)display; CHECK(format->fourcc == VA_FOURCC_NV12 && width == 64 && height == 32, "image-geometry");
    ++creates; image_record(image); return VA_STATUS_SUCCESS;
}
VAStatus vaDestroyImage(VADisplay display, VAImageID image)
{
    (void)display; (void)image; return VA_STATUS_SUCCESS;
}
VAStatus vaSyncSurface(VADisplay display, VASurfaceID surface)
{
    (void)display; (void)surface; return VA_STATUS_SUCCESS;
}
VAStatus vaGetImage(VADisplay display, VASurfaceID surface, int x, int y,
                    unsigned width, unsigned height, VAImageID image)
{
    (void)display; (void)surface; (void)image;
    CHECK(x == 0 && y == 0 && width == 64 && height == 32, "read-geometry");
    ++reads; memset(pixels, 0x71, sizeof(pixels)); return VA_STATUS_SUCCESS;
}
VAStatus vaMapBuffer(VADisplay display, VABufferID buffer, void **data)
{
    (void)display; (void)buffer; *data = pixels; return VA_STATUS_SUCCESS;
}
#if VA_CHECK_VERSION(1, 21, 0)
VAStatus vaMapBuffer2(VADisplay display, VABufferID buffer, void **data, uint32_t flags)
{
    (void)flags; return vaMapBuffer(display, buffer, data);
}
#endif
VAStatus vaUnmapBuffer(VADisplay display, VABufferID buffer)
{
    (void)display; (void)buffer; return VA_STATUS_SUCCESS;
}

static void frame_path(const char *option)
{
    derives = creates = reads = opens = 0;
    AVBufferRef *device_ref = av_hwdevice_ctx_alloc(AV_HWDEVICE_TYPE_VAAPI);
    CHECK(device_ref, "device-allocation");
    AVHWDeviceContext *device = (void *)device_ref->data;
    VAAPIDeviceContext *private = device->hwctx;
    AVDictionary *options = NULL;
    if (option) av_dict_set(&options, "observer_copy_readback", option, 0);
    av_dict_set(&options, "connection_type", "drm", 0);
    /* The real device-create option route runs; its only open is interposed. */
    CHECK(vaapi_device_create(device, "/offline/no-device", options, 0) < 0, "synthetic-open-refused");
    CHECK(opens == 1, "one-interposed-open");
    av_dict_free(&options);
    private->formats = av_mallocz(sizeof(*private->formats));
    CHECK(private->formats, "format-allocation");
    private->nb_formats = 1;
    private->formats[0] = (VAAPISurfaceFormat){.pix_fmt = AV_PIX_FMT_NV12,
        .fourcc = VA_FOURCC_NV12, .image_format = {.fourcc = VA_FOURCC_NV12,
        .byte_order = VA_LSB_FIRST, .bits_per_pixel = 12}};
    AVBufferRef *frames_ref = av_hwframe_ctx_alloc(device_ref);
    CHECK(frames_ref, "frames-allocation");
    AVHWFramesContext *frames = (void *)frames_ref->data;
    frames->format = AV_PIX_FMT_VAAPI; frames->sw_format = AV_PIX_FMT_NV12;
    frames->width = 64; frames->height = 32; frames->initial_pool_size = 4;
    CHECK(av_hwframe_ctx_init(frames_ref) == 0, "real-frames-init");
    const int copy = option && !strcmp(option, "1");
    CHECK(derives == (copy ? 0 : 1), "copy-readback-probe");
    AVFrame *source = av_frame_alloc(), *output = av_frame_alloc();
    CHECK(source && output, "frame-allocation");
    CHECK(av_hwframe_get_buffer(frames_ref, source, 0) == 0, "actual-pool-buffer");
    output->format = AV_PIX_FMT_NV12; output->width = 64; output->height = 32;
    CHECK(av_frame_get_buffer(output, 0) == 0, "output-buffer");
    CHECK(av_hwframe_transfer_data(output, source, 0) == 0, "actual-pixel-transfer");
    CHECK(creates == 1 && reads == 1 && output->data[0][0] == 0x71 && output->data[1][0] == 0x71,
          "independent-image-readback");
    CHECK(derives == (copy ? 0 : 1), "no-readback-alias");
    av_frame_free(&source); av_frame_free(&output);
    av_buffer_unref(&frames_ref); av_buffer_unref(&device_ref);
}

int main(void)
{
    frame_path(NULL); frame_path("0"); frame_path("1");
    AVBufferRef *reference = av_hwdevice_ctx_alloc(AV_HWDEVICE_TYPE_VAAPI);
    CHECK(reference, "invalid-device-allocation");
    AVDictionary *options = NULL;
    av_dict_set(&options, "observer_copy_readback", "invalid", 0);
    opens = 0;
    CHECK(vaapi_device_create((void *)reference->data, "/offline/no-device", options, 0) == AVERROR(EINVAL),
          "invalid-option-refused");
    CHECK(!opens, "invalid-option-before-open");
    av_dict_free(&options); av_buffer_unref(&reference);
    puts("PASS actual device/frame initialization, default/0/1, copied pixel readback and invalid option");
    return 0;
}
