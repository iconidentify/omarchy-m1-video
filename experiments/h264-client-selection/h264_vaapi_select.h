/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Extracted H.264 VA-API picture gate. Same rules as the local n9.0.1 patch. */
#ifndef H264_VAAPI_SELECT_H
#define H264_VAAPI_SELECT_H

enum h264_va_profile {
	H264_VA_NONE = 0,
	H264_VA_CONSTRAINED_BASELINE,
	H264_VA_MAIN,
	H264_VA_HIGH,
	H264_VA_HIGH10,
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
};

struct h264_va_picture {
	int profile_idc;
	int constraint_set1;
	int frame_mbs_only;
	int mbaff;
	int field_pic;
	int chroma_format_idc;
	int bit_depth_luma_minus8;
	int bit_depth_chroma_minus8;
	int slice_groups; /* num_slice_groups_minus1 + 1 */
	int nal_unit_type;
	int slice_type; /* 0 P, 1 B, 2 I, 3 SP, 4 SI, plus 5-9 */
	int cabac;
	int transform_8x8;
	int parse_ok;
};

struct h264_va_session {
	int sticky;
	int submitted;
	int cancelled;
	enum h264_va_profile selected;
	enum h264_va_reject last_reject;
};

enum h264_va_profile h264_va_choose_profile(const struct h264_va_picture *p);
enum h264_va_reject h264_va_check_picture(const struct h264_va_picture *p,
					  enum h264_va_profile selected);
int h264_va_start_frame(struct h264_va_session *s, const struct h264_va_picture *p);
int h264_va_decode_slice(struct h264_va_session *s, const struct h264_va_picture *p);
int h264_va_end_frame(struct h264_va_session *s);
void h264_va_stub_submit(struct h264_va_session *s);

#endif
