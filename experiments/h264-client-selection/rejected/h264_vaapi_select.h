/* SPDX-License-Identifier: LGPL-2.1-or-later */
#ifndef H264_VAAPI_SELECT_H
#define H264_VAAPI_SELECT_H

enum h264_va_profile {
	H264_VA_NONE = 0,
	H264_VA_CONSTRAINED_BASELINE = 1,
	H264_VA_MAIN = 2,
	H264_VA_HIGH = 4,
	H264_VA_HIGH10 = 8,
};

enum h264_va_reject {
	H264_VA_OK = 0,
	H264_VA_REJECT_FMO,
	H264_VA_REJECT_FIELDS,
	H264_VA_REJECT_PARTITION,
	H264_VA_REJECT_SP_SI,
	H264_VA_REJECT_MALFORMED,
	H264_VA_REJECT_PROFILE,
	H264_VA_REJECT_STICKY,
	H264_VA_REJECT_CHROMA,
	H264_VA_REJECT_DEPTH,
	H264_VA_REJECT_CABAC,
	H264_VA_REJECT_TRANSFORM,
	H264_VA_REJECT_REDUNDANCY,
	H264_VA_REJECT_ORDER,
};

#define H264_NAL_SLICE 1
#define H264_NAL_DPA 2
#define H264_NAL_DPB 3
#define H264_NAL_DPC 4
#define H264_NAL_IDR_SLICE 5

struct h264_va_picture {
	int profile_idc;
	int constraint_set1;
	int frame_mbs_only;
	int mbaff;
	int field_pic;
	int chroma_format_idc;
	int bit_depth_luma_minus8;
	int bit_depth_chroma_minus8;
	int slice_groups;
	int nal_unit_type;
	int slice_type; /* 0=P 1=B 2=I 3=SP 4=SI only */
	int cabac;
	int transform_8x8;
	int redundant_pic_cnt_present;
	int first_mb;
	int parse_ok;
};

struct h264_va_session {
	int sticky;
	int submitted;
	int cancelled;
	int in_picture;
	int advertised;
	int last_first_mb;
	enum h264_va_profile selected;
	enum h264_va_reject last_reject;
};

enum h264_va_profile h264_va_choose_profile(const struct h264_va_picture *p,
					    int advertised);
enum h264_va_reject h264_va_check_picture(const struct h264_va_picture *p,
					  enum h264_va_profile selected);
int h264_va_start_frame(struct h264_va_session *s, const struct h264_va_picture *p);
int h264_va_decode_slice(struct h264_va_session *s, const struct h264_va_picture *p);
int h264_va_end_frame(struct h264_va_session *s);
int h264_va_on_nal(struct h264_va_session *s, int nal,
		   const struct h264_va_picture *p);
void h264_va_stub_submit(struct h264_va_session *s);

struct AVCodecContext;
struct H264Context;
int ff_h264_vaapi_mark_unsupported(struct AVCodecContext *avctx);
int ff_h264_vaapi_mark_malformed(struct AVCodecContext *avctx);
int ff_h264_vaapi_gate_start(struct AVCodecContext *avctx, const struct H264Context *h);
int ff_h264_vaapi_gate_slice(struct AVCodecContext *avctx, const struct H264Context *h);
int ff_h264_vaapi_gate_end(struct AVCodecContext *avctx);

#endif
