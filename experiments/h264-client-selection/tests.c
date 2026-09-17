/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include "h264_vaapi_select.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static struct h264_va_picture pic(int profile, int cs1, int nal, int st)
{
	struct h264_va_picture p;
	memset(&p, 0, sizeof(p));
	p.profile_idc = profile;
	p.constraint_set1 = cs1;
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
	a = pic(77, 0, 5, 2);
	assert(h264_va_start_frame(&s, &a) == 0);
	assert(h264_va_decode_slice(&s, &a) == 0);
	assert(h264_va_end_frame(&s) == 0);
	assert(s.submitted == 1);
	assert(s.selected == H264_VA_MAIN);

	memset(&s, 0, sizeof(s));
	a = pic(66, 0, 5, 2);
	assert(h264_va_start_frame(&s, &a) == 0);
	assert(s.selected == H264_VA_CONSTRAINED_BASELINE);
	assert(h264_va_decode_slice(&s, &a) == 0);
	assert(h264_va_end_frame(&s) == 0);

	memset(&s, 0, sizeof(s));
	a = pic(88, 0, 5, 2);
	a.slice_type = 1;
	assert(h264_va_start_frame(&s, &a) == 0);
	assert(s.selected == H264_VA_MAIN);
	assert(h264_va_end_frame(&s) == 0);

	memset(&s, 0, sizeof(s));
	a = pic(66, 0, 5, 2);
	a.slice_groups = 2;
	assert(h264_va_start_frame(&s, &a) < 0);
	assert(s.last_reject == H264_VA_REJECT_FMO);
	assert(h264_va_end_frame(&s) < 0);
	assert(s.submitted == 0);

	memset(&s, 0, sizeof(s));
	a = pic(66, 0, 5, 2);
	a.frame_mbs_only = 0;
	assert(h264_va_start_frame(&s, &a) < 0);
	assert(s.last_reject == H264_VA_REJECT_FIELDS);
	assert(s.submitted == 0);

	memset(&s, 0, sizeof(s));
	a = pic(66, 0, 2, 0);
	assert(h264_va_start_frame(&s, &a) < 0);
	assert(s.last_reject == H264_VA_REJECT_PARTITION);

	memset(&s, 0, sizeof(s));
	a = pic(88, 0, 5, 3);
	assert(h264_va_start_frame(&s, &a) < 0);
	assert(s.last_reject == H264_VA_REJECT_SP_SI);

	memset(&s, 0, sizeof(s));
	a = pic(77, 0, 5, 2);
	assert(h264_va_start_frame(&s, &a) == 0);
	assert(h264_va_decode_slice(&s, &a) == 0);
	assert(h264_va_end_frame(&s) == 0);
	assert(s.submitted == 1);
	b = pic(77, 0, 1, 0);
	b.slice_groups = 2;
	assert(h264_va_start_frame(&s, &b) < 0);
	assert(h264_va_decode_slice(&s, &b) < 0);
	assert(h264_va_end_frame(&s) < 0);
	assert(s.submitted == 1);
	assert(s.sticky);

	memset(&s, 0, sizeof(s));
	a = pic(77, 0, 5, 2);
	assert(h264_va_start_frame(&s, &a) == 0);
	assert(h264_va_decode_slice(&s, &a) == 0);
	b = a;
	b.nal_unit_type = 2;
	assert(h264_va_decode_slice(&s, &b) < 0);
	assert(h264_va_end_frame(&s) < 0);
	assert(s.submitted == 0);

	memset(&s, 0, sizeof(s));
	a = pic(66, 0, 5, 2);
	a.parse_ok = 0;
	assert(h264_va_start_frame(&s, &a) < 0);
	assert(s.submitted == 0);

	puts("PASS: extracted callbacks select CB/Main, reject FMO/fields/partitions/SP-SI, sticky cancel, no submit of rejected picture");
	return 0;
}
