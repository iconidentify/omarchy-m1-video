/* SPDX-License-Identifier: GPL-2.0 */
/* Synthetic storage/API scaffolding around actual generated kernel functions.
 * Imported function copyright: The Asahi Linux Contributors and Linux authors.
 * This executable has no device or allocator API. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <string.h>
typedef uint32_t u32;
#define DIV_ROUND_UP(n,d) (((n)+(d)-1)/(d))
#define ALIGN(x,a) (((x)+((a)-1)) & ~((a)-1))
#define V4L2_PIX_FMT_NV12 1
#define V4L2_PIX_FMT_P010 2
#define V4L2_PIXEL_ENC_YUV 1
struct v4l2_format_info {
    u32 format, pixel_enc, mem_planes, comp_planes, bpp[4], bpp_div[4], hdiv, vdiv, block_w[4], block_h[4];
};
struct v4l2_plane_pix_format { u32 bytesperline, sizeimage; };
struct v4l2_pix_format_mplane { u32 width, height, pixelformat, num_planes; struct v4l2_plane_pix_format plane_fmt[4]; };
enum avd_image_fmt { AVD_IMG_FMT_420_8BIT, AVD_IMG_FMT_422_8BIT, AVD_IMG_FMT_420_10BIT, AVD_IMG_FMT_422_10BIT };
struct avd_comp { u32 start_offset, size, offsets[4]; };
struct avd_ctx;
struct ops { void (*adjust_decoded_fmt)(struct avd_ctx *,struct v4l2_pix_format_mplane *); };
struct desc { struct ops *ops; };
struct avd_ctx { struct avd_comp comp; enum avd_image_fmt image_fmt; struct desc *coded_fmt_desc; };
static u32 roundup_pow_of_two(u32 n) {
    u32 result=1;
    while (result<n) result <<= 1;
    return result;
}
#include "extracted.inc"
static int number(const char *s, uint64_t *out) {
    char *end;
    if (!*s || *s=='-') return -1;
    errno=0; *out=strtoull(s,&end,10);
    return errno || *end ? -1 : 0;
}
int main(int argc, char **argv) {
    uint64_t args[4];
    if (argc!=5) return 2;
    for (int i=0;i<4;i++) if(number(argv[i+1],&args[i])) return 2;
    /* Harness admission domain, not a change to kernel validation. The actual
     * AVD HEVC capture constraints are width step64 / height step16, max16384. */
    if(args[0]<64 || args[0]>16384 || args[0]%64 || args[1]<64 || args[1]>16384 || args[1]%16 ||
       (args[2]!=8 && args[2]!=10) || args[3]>UINT32_MAX) return 2;
    struct ops ops={avd_hevc_adjust_decoded_fmt};
    struct desc desc={&ops};
    struct avd_ctx ctx={.image_fmt=args[2]==8?AVD_IMG_FMT_420_8BIT:AVD_IMG_FMT_420_10BIT,.coded_fmt_desc=&desc};
    struct v4l2_pix_format_mplane fmt={.width=args[0],.height=args[1],.pixelformat=args[2]==8?V4L2_PIX_FMT_NV12:V4L2_PIX_FMT_P010};
    avd_fill_decoded_pixfmt(&ctx,&fmt);
    uint64_t length=args[3]?args[3]:fmt.plane_fmt[0].sizeimage;
    u32 mv=mv_color_size(fmt.width,fmt.height);
    if(length<fmt.plane_fmt[0].sizeimage || length<mv) return 2;
    uint64_t mv_offset=place_mv(length,mv);
    if((uint64_t)ctx.comp.start_offset+ctx.comp.size>mv_offset) return 2;
    printf("{\"start\":%u,\"comp\":%u,\"offsets\":[%u,%u,%u,%u],\"mv\":%u,\"packed\":%u,\"length\":%llu,\"mv_offset\":%llu}\n",
       ctx.comp.start_offset,ctx.comp.size,ctx.comp.offsets[0],ctx.comp.offsets[1],ctx.comp.offsets[2],ctx.comp.offsets[3],mv,fmt.plane_fmt[0].sizeimage,(unsigned long long)length,(unsigned long long)mv_offset);
    return 0;
}
