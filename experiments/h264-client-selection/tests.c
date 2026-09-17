/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include "h264_vaapi_select.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static struct h264_va_picture pic(int profile, int nal, int st)
{
	struct h264_va_picture p;
	memset(&p, 0, sizeof(p));
	p.profile_idc = profile;
	p.frame_mbs_only = 1;
	p.chroma_format_idc = 1;
	p.slice_groups = 1;
	p.nal_unit_type = nal;
	p.slice_type = st;
	p.parse_ok = 1;
	return p;
}

int main(void)
{
	struct h264_va_session s;
	struct h264_va_picture a, b;

	memset(&s, 0, sizeof(s));
	a = pic(77, 5, 2);
	assert(h264_va_on_nal(&s, 5, &a) == 0);
	assert(h264_va_end_frame(&s) == 0);
	assert(s.submitted == 1);
	assert(s.selected == H264_VA_MAIN);

	memset(&s, 0, sizeof(s));
	a = pic(66, 5, 2);
	assert(h264_va_on_nal(&s, 5, &a) == 0);
	assert(s.selected == H264_VA_CONSTRAINED_BASELINE);
	assert(h264_va_end_frame(&s) == 0);

	memset(&s, 0, sizeof(s));
	a = pic(88, 5, 1);
	assert(h264_va_on_nal(&s, 5, &a) == 0);
	assert(s.selected == H264_VA_MAIN);
	assert(h264_va_end_frame(&s) == 0);

	memset(&s, 0, sizeof(s));
	a = pic(66, 5, 2);
	a.slice_groups = 2;
	assert(h264_va_on_nal(&s, 5, &a) < 0);
	assert(s.last_reject == H264_VA_REJECT_FMO);
	assert(h264_va_end_frame(&s) < 0);
	assert(s.submitted == 0);

	memset(&s, 0, sizeof(s));
	a = pic(66, 5, 2);
	a.cabac = 1;
	assert(h264_va_on_nal(&s, 5, &a) < 0);
	assert(s.last_reject == H264_VA_REJECT_CABAC);

	memset(&s, 0, sizeof(s));
	a = pic(66, 5, 1);
	assert(h264_va_on_nal(&s, 5, &a) < 0);
	assert(s.last_reject == H264_VA_REJECT_PROFILE);

	memset(&s, 0, sizeof(s));
	a = pic(110, 5, 2);
	a.bit_depth_luma_minus8 = 1;
	a.bit_depth_chroma_minus8 = 1;
	assert(h264_va_on_nal(&s, 5, &a) < 0);
	assert(s.submitted == 0);

	memset(&s, 0, sizeof(s));
	assert(h264_va_end_frame(&s) < 0);
	assert(s.submitted == 0);

	memset(&s, 0, sizeof(s));
	a = pic(77, 5, 10);
	assert(h264_va_on_nal(&s, 5, &a) < 0);
	assert(s.last_reject == H264_VA_REJECT_MALFORMED);

	memset(&s, 0, sizeof(s));
	a = pic(77, 5, 2);
	a.slice_groups = 0;
	assert(h264_va_on_nal(&s, 5, &a) < 0);
	assert(s.last_reject == H264_VA_REJECT_MALFORMED);

	memset(&s, 0, sizeof(s));
	a = pic(77, 5, 2);
	assert(h264_va_on_nal(&s, 5, &a) == 0);
	assert(h264_va_on_nal(&s, 2, &a) < 0);
	assert(s.last_reject == H264_VA_REJECT_PARTITION);
	assert(h264_va_end_frame(&s) < 0);
	assert(s.submitted == 0);

	memset(&s, 0, sizeof(s));
	a = pic(77, 5, 2);
	assert(h264_va_on_nal(&s, 5, &a) == 0);
	assert(h264_va_end_frame(&s) == 0);
	assert(s.submitted == 1);
	b = pic(77, 1, 0);
	b.slice_groups = 2;
	assert(h264_va_on_nal(&s, 1, &b) < 0);
	assert(h264_va_end_frame(&s) < 0);
	assert(s.submitted == 1);

	memset(&s, 0, sizeof(s));
	a = pic(77, 5, 2);
	assert(h264_va_on_nal(&s, 5, &a) == 0);
	b = a;
	b.slice_type = 3;
	b.first_mb = 10;
	assert(h264_va_on_nal(&s, 1, &b) < 0);
	assert(s.last_reject == H264_VA_REJECT_SP_SI);
	assert(h264_va_end_frame(&s) < 0);
	assert(s.submitted == 0);

	puts("PASS: dispatch NAL 2 after prefix does not submit; incomplete end_frame fails closed; High10 not advertised");
	return 0;
}
