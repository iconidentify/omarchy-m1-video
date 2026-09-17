/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include "h264_vaapi_select.h"
#include <string.h>

static enum h264_va_reject fail(struct h264_va_session *s, enum h264_va_reject r)
{
	s->last_reject = r;
	s->sticky = 1;
	s->cancelled = 1;
	return r;
}

enum h264_va_profile h264_va_choose_profile(const struct h264_va_picture *p,
					    int advertised)
{
	enum h264_va_profile want = H264_VA_NONE;

	if (!p || !p->parse_ok)
		return H264_VA_NONE;
	if (p->profile_idc == 66 && p->constraint_set1)
		want = H264_VA_CONSTRAINED_BASELINE;
	else if (p->profile_idc == 66)
		want = H264_VA_CONSTRAINED_BASELINE;
	else if (p->profile_idc == 88)
		want = H264_VA_MAIN;
	else if (p->profile_idc == 77)
		want = H264_VA_MAIN;
	else if (p->profile_idc == 100)
		want = H264_VA_HIGH;
	else if (p->profile_idc == 110)
		want = H264_VA_HIGH10;
	if (want && !(advertised & want))
		return H264_VA_NONE;
	return want;
}

enum h264_va_reject h264_va_check_picture(const struct h264_va_picture *p,
					  enum h264_va_profile selected)
{
	if (!p || !p->parse_ok)
		return H264_VA_REJECT_MALFORMED;
	if (p->slice_groups < 1)
		return H264_VA_REJECT_MALFORMED;
	if (p->slice_type < 0 || p->slice_type > 4)
		return H264_VA_REJECT_MALFORMED;
	if (p->nal_unit_type == H264_NAL_DPA || p->nal_unit_type == H264_NAL_DPB ||
	    p->nal_unit_type == H264_NAL_DPC)
		return H264_VA_REJECT_PARTITION;
	if (p->nal_unit_type != H264_NAL_SLICE && p->nal_unit_type != H264_NAL_IDR_SLICE)
		return H264_VA_REJECT_MALFORMED;
#ifndef H264_VA_SKIP_FMO
	if (p->slice_groups > 1)
		return H264_VA_REJECT_FMO;
#endif
	if (!p->frame_mbs_only || p->mbaff || p->field_pic)
		return H264_VA_REJECT_FIELDS;
	if (p->slice_type == 3 || p->slice_type == 4)
		return H264_VA_REJECT_SP_SI;
	if (p->chroma_format_idc != 1)
		return H264_VA_REJECT_CHROMA;
	if (p->bit_depth_luma_minus8 != p->bit_depth_chroma_minus8)
		return H264_VA_REJECT_DEPTH;
	if (p->redundant_pic_cnt_present)
		return H264_VA_REJECT_REDUNDANCY;
	if (selected == H264_VA_HIGH10) {
		if (p->bit_depth_luma_minus8 > 2)
			return H264_VA_REJECT_DEPTH;
	} else if (p->bit_depth_luma_minus8 != 0) {
		return H264_VA_REJECT_DEPTH;
	}
	if (selected == H264_VA_CONSTRAINED_BASELINE) {
		if (p->slice_type == 1)
			return H264_VA_REJECT_PROFILE;
		if (p->cabac)
			return H264_VA_REJECT_CABAC;
		if (p->transform_8x8)
			return H264_VA_REJECT_TRANSFORM;
		if (p->profile_idc != 66)
			return H264_VA_REJECT_PROFILE;
	}
	if (selected == H264_VA_MAIN && p->transform_8x8)
		return H264_VA_REJECT_TRANSFORM;
	if (p->profile_idc != 66 && p->profile_idc != 77 && p->profile_idc != 88 &&
	    p->profile_idc != 100 && p->profile_idc != 110)
		return H264_VA_REJECT_PROFILE;
	return H264_VA_OK;
}

int h264_va_start_frame(struct h264_va_session *s, const struct h264_va_picture *p)
{
	enum h264_va_reject r;
	enum h264_va_profile want;

	if (!s)
		return -1;
	if (s->sticky)
		return s->last_reject = H264_VA_REJECT_STICKY, -1;
	if (!s->advertised)
		s->advertised = H264_VA_CONSTRAINED_BASELINE | H264_VA_MAIN | H264_VA_HIGH;
	if (!s->selected) {
		want = h264_va_choose_profile(p, s->advertised);
		if (!want)
			return fail(s, H264_VA_REJECT_PROFILE), -1;
		s->selected = want;
	}
	r = h264_va_check_picture(p, s->selected);
	if (r)
		return fail(s, r), -1;
	s->cancelled = 0;
	s->in_picture = 1;
	s->last_first_mb = p->first_mb;
	return 0;
}

int h264_va_decode_slice(struct h264_va_session *s, const struct h264_va_picture *p)
{
	enum h264_va_reject r;

	if (!s)
		return -1;
	if (!s->in_picture)
		return fail(s, H264_VA_REJECT_MALFORMED), -1;
	if (s->sticky)
		return s->last_reject = H264_VA_REJECT_STICKY, -1;
	r = h264_va_check_picture(p, s->selected);
	if (r)
		return fail(s, r), -1;
	if (p->first_mb < s->last_first_mb)
		return fail(s, H264_VA_REJECT_ORDER), -1;
	s->last_first_mb = p->first_mb;
	return 0;
}

void h264_va_stub_submit(struct h264_va_session *s)
{
	s->submitted++;
}

int h264_va_end_frame(struct h264_va_session *s)
{
	if (!s || !s->in_picture)
		return s ? (s->last_reject = H264_VA_REJECT_MALFORMED, -1) : -1;
	if (s->sticky || s->cancelled) {
		s->in_picture = 0;
		return -1;
	}
	h264_va_stub_submit(s);
	s->in_picture = 0;
	return 0;
}

int h264_va_on_nal(struct h264_va_session *s, int nal,
		   const struct h264_va_picture *p)
{
	struct h264_va_picture pic;

	if (!s)
		return -1;
	if (nal == H264_NAL_DPA || nal == H264_NAL_DPB || nal == H264_NAL_DPC)
		return fail(s, H264_VA_REJECT_PARTITION), -1;
	if (nal != H264_NAL_SLICE && nal != H264_NAL_IDR_SLICE)
		return 0;
	if (!p)
		return fail(s, H264_VA_REJECT_MALFORMED), -1;
	pic = *p;
	pic.nal_unit_type = nal;
	if (!s->in_picture) {
		if (h264_va_start_frame(s, &pic) < 0)
			return -1;
	}
	return h264_va_decode_slice(s, &pic);
}

#if CONFIG_H264_VAAPI_HWACCEL
#include "h264dec.h"
#include "vaapi_decode.h"

int ff_h264_vaapi_mark_unsupported(AVCodecContext *avctx)
{
	VAAPIDecodeContext *ctx;

	if (!avctx || !avctx->internal || !avctx->internal->hwaccel_priv_data)
		return AVERROR(EINVAL);
	ctx = avctx->internal->hwaccel_priv_data;
	fail(&ctx->h264_sel, H264_VA_REJECT_PARTITION);
	return AVERROR(EINVAL);
}

int ff_h264_vaapi_mark_malformed(AVCodecContext *avctx)
{
	VAAPIDecodeContext *ctx;

	if (!avctx || !avctx->internal || !avctx->internal->hwaccel_priv_data)
		return AVERROR(EINVAL);
	ctx = avctx->internal->hwaccel_priv_data;
	fail(&ctx->h264_sel, H264_VA_REJECT_MALFORMED);
	return AVERROR(EINVAL);
}

int ff_h264_vaapi_gate_start(AVCodecContext *avctx, const H264Context *h)
{
	VAAPIDecodeContext *ctx;
	const SPS *sps;
	const PPS *pps;
	const H264SliceContext *sl;
	struct h264_va_picture p;

	if (!avctx || !h || !avctx->internal || !avctx->internal->hwaccel_priv_data)
		return AVERROR(EINVAL);
	ctx = avctx->internal->hwaccel_priv_data;
	sps = h->ps.sps;
	pps = h->ps.pps;
	sl = &h->slice_ctx[0];
	if (!sps || !pps)
		return ff_h264_vaapi_mark_malformed(avctx);
	memset(&p, 0, sizeof(p));
	p.profile_idc = sps->profile_idc;
	p.constraint_set1 = !!(sps->constraint_set_flags & (1 << 1));
	p.frame_mbs_only = sps->frame_mbs_only_flag;
	p.mbaff = sps->mb_aff;
	p.field_pic = h->picture_structure != PICT_FRAME;
	p.chroma_format_idc = sps->chroma_format_idc;
	p.bit_depth_luma_minus8 = sps->bit_depth_luma - 8;
	p.bit_depth_chroma_minus8 = sps->bit_depth_chroma - 8;
	p.slice_groups = pps->slice_group_count;
	p.nal_unit_type = h->nal_unit_type;
	if (sl->slice_type == AV_PICTURE_TYPE_P)
		p.slice_type = 0;
	else if (sl->slice_type == AV_PICTURE_TYPE_B)
		p.slice_type = 1;
	else if (sl->slice_type == AV_PICTURE_TYPE_I)
		p.slice_type = 2;
	else if (sl->slice_type == AV_PICTURE_TYPE_SP)
		p.slice_type = 3;
	else if (sl->slice_type == AV_PICTURE_TYPE_SI)
		p.slice_type = 4;
	else
		p.slice_type = 10;
	p.cabac = pps->cabac;
	p.transform_8x8 = pps->transform_8x8_mode;
	p.redundant_pic_cnt_present = pps->redundant_pic_cnt_present;
	p.first_mb = sl->mb_y * h->mb_width + sl->mb_x;
	p.parse_ok = 1;
	ctx->h264_sel.advertised = H264_VA_CONSTRAINED_BASELINE | H264_VA_MAIN | H264_VA_HIGH;
	if (h264_va_start_frame(&ctx->h264_sel, &p) < 0)
		return AVERROR(EINVAL);
	return 0;
}

int ff_h264_vaapi_gate_slice(AVCodecContext *avctx, const H264Context *h)
{
	VAAPIDecodeContext *ctx;
	const PPS *pps;
	const SPS *sps;
	const H264SliceContext *sl;
	struct h264_va_picture p;

	if (!avctx || !h || !avctx->internal || !avctx->internal->hwaccel_priv_data)
		return AVERROR(EINVAL);
	ctx = avctx->internal->hwaccel_priv_data;
	sps = h->ps.sps;
	pps = h->ps.pps;
	sl = &h->slice_ctx[0];
	if (!sps || !pps)
		return ff_h264_vaapi_mark_malformed(avctx);
	memset(&p, 0, sizeof(p));
	p.profile_idc = sps->profile_idc;
	p.constraint_set1 = !!(sps->constraint_set_flags & (1 << 1));
	p.frame_mbs_only = sps->frame_mbs_only_flag;
	p.mbaff = sps->mb_aff;
	p.field_pic = h->picture_structure != PICT_FRAME;
	p.chroma_format_idc = sps->chroma_format_idc;
	p.bit_depth_luma_minus8 = sps->bit_depth_luma - 8;
	p.bit_depth_chroma_minus8 = sps->bit_depth_chroma - 8;
	p.slice_groups = pps->slice_group_count;
	p.nal_unit_type = h->nal_unit_type;
	if (sl->slice_type == AV_PICTURE_TYPE_P)
		p.slice_type = 0;
	else if (sl->slice_type == AV_PICTURE_TYPE_B)
		p.slice_type = 1;
	else if (sl->slice_type == AV_PICTURE_TYPE_I)
		p.slice_type = 2;
	else if (sl->slice_type == AV_PICTURE_TYPE_SP)
		p.slice_type = 3;
	else if (sl->slice_type == AV_PICTURE_TYPE_SI)
		p.slice_type = 4;
	else
		p.slice_type = 10;
	p.cabac = pps->cabac;
	p.transform_8x8 = pps->transform_8x8_mode;
	p.redundant_pic_cnt_present = pps->redundant_pic_cnt_present;
	p.first_mb = sl->mb_y * h->mb_width + sl->mb_x;
	p.parse_ok = 1;
	if (h264_va_decode_slice(&ctx->h264_sel, &p) < 0)
		return AVERROR(EINVAL);
	return 0;
}

int ff_h264_vaapi_gate_end(AVCodecContext *avctx)
{
	VAAPIDecodeContext *ctx;

	if (!avctx || !avctx->internal || !avctx->internal->hwaccel_priv_data)
		return AVERROR(EINVAL);
	ctx = avctx->internal->hwaccel_priv_data;
	if (ctx->h264_sel.sticky || ctx->h264_sel.cancelled)
		return AVERROR(EINVAL);
	return 0;
}
#endif
