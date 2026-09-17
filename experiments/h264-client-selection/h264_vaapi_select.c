/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include "h264_vaapi_select.h"

static int slice_kind(int slice_type)
{
	return slice_type % 5;
}

enum h264_va_profile h264_va_choose_profile(const struct h264_va_picture *p)
{
	if (!p || !p->parse_ok)
		return H264_VA_NONE;
	if (p->profile_idc == 66 && p->constraint_set1)
		return H264_VA_CONSTRAINED_BASELINE;
	if (p->profile_idc == 77)
		return H264_VA_MAIN;
	if (p->profile_idc == 100)
		return H264_VA_HIGH;
	if (p->profile_idc == 110)
		return H264_VA_HIGH10;
	if (p->profile_idc == 66)
		return H264_VA_CONSTRAINED_BASELINE;
	if (p->profile_idc == 88)
		return H264_VA_MAIN;
	return H264_VA_NONE;
}

enum h264_va_reject h264_va_check_picture(const struct h264_va_picture *p,
					  enum h264_va_profile selected)
{
	int kind;

	if (!p || !p->parse_ok)
		return H264_VA_REJECT_MALFORMED;
	if (p->nal_unit_type == 2 || p->nal_unit_type == 3 || p->nal_unit_type == 4)
		return H264_VA_REJECT_PARTITION;
	if (p->nal_unit_type != 1 && p->nal_unit_type != 5)
		return H264_VA_REJECT_MALFORMED;
#ifndef H264_VA_SKIP_FMO
	if (p->slice_groups > 1)
		return H264_VA_REJECT_FMO;
#endif
	if (!p->frame_mbs_only || p->mbaff || p->field_pic)
		return H264_VA_REJECT_FIELDS;
	kind = slice_kind(p->slice_type);
	if (kind == 3 || kind == 4)
		return H264_VA_REJECT_SP_SI;
	if (p->chroma_format_idc != 1)
		return H264_VA_REJECT_CHROMA;
	if (p->bit_depth_luma_minus8 != p->bit_depth_chroma_minus8)
		return H264_VA_REJECT_DEPTH;
	if (selected == H264_VA_HIGH10) {
		if (p->bit_depth_luma_minus8 > 2)
			return H264_VA_REJECT_DEPTH;
	} else if (p->bit_depth_luma_minus8 != 0) {
		return H264_VA_REJECT_DEPTH;
	}
	if (selected == H264_VA_CONSTRAINED_BASELINE) {
		if (kind == 1 || p->cabac || p->transform_8x8)
			return H264_VA_REJECT_PROFILE;
		if (p->profile_idc != 66 && p->profile_idc != 77)
			return H264_VA_REJECT_PROFILE;
	}
	if (selected == H264_VA_MAIN) {
		if (p->transform_8x8)
			return H264_VA_REJECT_PROFILE;
	}
	if (h264_va_choose_profile(p) == H264_VA_NONE)
		return H264_VA_REJECT_PROFILE;
	return H264_VA_OK;
}

int h264_va_start_frame(struct h264_va_session *s, const struct h264_va_picture *p)
{
	enum h264_va_reject r;
	enum h264_va_profile want;

	if (s->sticky)
		return (s->last_reject = H264_VA_REJECT_STICKY), -1;
	if (!s->selected) {
		want = h264_va_choose_profile(p);
		if (!want)
			return (s->last_reject = H264_VA_REJECT_PROFILE), s->sticky = 1, -1;
		s->selected = want;
	}
	r = h264_va_check_picture(p, s->selected);
	if (r) {
		s->last_reject = r;
		s->sticky = 1;
		s->cancelled = 1;
		return -1;
	}
	s->cancelled = 0;
	return 0;
}

int h264_va_decode_slice(struct h264_va_session *s, const struct h264_va_picture *p)
{
	enum h264_va_reject r;

	if (s->sticky)
		return (s->last_reject = H264_VA_REJECT_STICKY), -1;
	r = h264_va_check_picture(p, s->selected);
	if (r) {
		s->last_reject = r;
		s->sticky = 1;
		s->cancelled = 1;
		return -1;
	}
	return 0;
}

void h264_va_stub_submit(struct h264_va_session *s)
{
	s->submitted++;
}

int h264_va_end_frame(struct h264_va_session *s)
{
	if (s->sticky || s->cancelled)
		return -1;
	h264_va_stub_submit(s);
	return 0;
}
