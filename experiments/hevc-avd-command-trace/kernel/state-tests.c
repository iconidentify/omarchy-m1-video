/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "cmd-core.h"

static struct cmd_capture c;
static void arm(void)
{
	memset(&c, 0, sizeof(c));
	c.run = 1;
	c.pid = 123;
	c.phase = CMD_ARMED;
}

int main(void)
{
	unsigned char packed[CMD_PACKED];
	unsigned int i;
	struct cmd_window *w;

	assert(CMD_PACKED == 1380);
	assert(CMD_PACKED < CMD_CONTROL);
	assert(PEAK_ALLOC_BYTES == 2u * TRACE_CAPTURE_BYTES +
	       2u * (unsigned)sizeof(struct cmd_capture));
	assert(PEAK_ALLOC_BYTES > 2097152u);

	cmd_bind(&c, 123, 8, 1);
	assert(c.phase != CMD_ACTIVE);

	arm();
	cmd_open(&c, 124);
	assert(c.errors == CMD_FOREIGN);
	arm();
	cmd_bind(&c, 123, 8, 1);
	assert(c.phase == CMD_ACTIVE);
	cmd_bind(&c, 123, 9, 1);
	assert(c.errors & CMD_FOREIGN);

	arm();
	cmd_bind(&c, 123, 8, 1);
	for (i = 1; i <= CMD_PICTURES; i++) {
		cmd_start(&c, 8, 1, 1, 0, 0);
		cmd_hist_set(&c, i * 2, i == 28 ? 2 : 0, 3, 0, i == 28);
		if (i >= CMD_FIRST && i <= CMD_LAST) {
			memset(packed, (unsigned char)i, sizeof(packed));
			cmd_controls(&c, packed, CMD_PACKED);
			cmd_word(&c, CMD_SITE_QP, 0x2d906800);
			cmd_word(&c, CMD_SITE_DBLK, 0x2da00000);
			if (i == 28)
				cmd_inactive(&c, CMD_SITE_WT_SKIP);
		}
		cmd_done(&c, 8, 1);
	}
	cmd_close(&c, 8);
	assert(!c.errors);
	assert(cmd_seal(&c));
	assert(c.phase == CMD_SEALED);
	w = &c.window[28 - CMD_FIRST];
	assert(w->picture == 28);
	assert(w->poc == 56);
	assert(w->type == 2);
	assert(w->nwords == 2);
	assert(w->controls[0] == 28);
	assert(w->inactive != 0);
	assert(c.hist[27].intra == 1);

	arm();
	cmd_bind(&c, 123, 8, 0);
	assert(c.errors & CMD_FOREIGN);

	arm();
	cmd_bind(&c, 123, 8, 1);
	cmd_start(&c, 8, 2, 1, 0, 0);
	assert(c.errors & CMD_SHAPE);

	arm();
	cmd_bind(&c, 123, 8, 1);
	cmd_start(&c, 8, 1, 1, 1, 0);
	assert(c.errors & CMD_SHAPE);

	arm();
	cmd_bind(&c, 123, 8, 1);
	cmd_start(&c, 8, 1, 1, 0, 1);
	assert(c.errors & CMD_SHAPE);

	arm();
	cmd_bind(&c, 123, 8, 1);
	cmd_start(&c, 8, 1, 0, 0, 0);
	assert(c.errors & CMD_SHAPE);

	arm();
	cmd_bind(&c, 123, 8, 1);
	for (i = 1; i < CMD_FIRST; i++) {
		cmd_start(&c, 8, 1, 1, 0, 0);
		cmd_done(&c, 8, 1);
	}
	cmd_start(&c, 8, 1, 1, 0, 0);
	cmd_controls(&c, packed, 12);
	assert(c.errors & CMD_OVERFLOW);
	cmd_slice_meta(&c, 0x10000, 0x200, 4, 16);
	assert(c.window[0].slice_size == 0x10000);
	assert(c.window[0].slice_coded == 0x200 + 16);

	arm();
	cmd_bind(&c, 123, 8, 1);
	cmd_start(&c, 8, 1, 1, 0, 0);
	cmd_done(&c, 8, 1);
	cmd_close(&c, 8);
	assert(c.errors & CMD_EXTENT);
	assert(c.phase == CMD_DRAINED);
	assert(cmd_seal(&c));
	arm();
	cmd_bind(&c, 123, 8, 1);
	assert(c.phase == CMD_ACTIVE);
	assert(!c.errors);

	arm();
	cmd_bind(&c, 123, 8, 1);
	for (i = 1; i < CMD_FIRST; i++) {
		cmd_start(&c, 8, 1, 1, 0, 0);
		cmd_done(&c, 8, 1);
	}
	cmd_start(&c, 8, 1, 1, 0, 0);
	for (i = 0; i < CMD_WORDS; i++)
		cmd_word(&c, CMD_SITE_SCL_4, i);
	cmd_word(&c, CMD_SITE_SCL_4, 0);
	assert(c.errors & CMD_OVERFLOW);
	assert(c.window[0].nwords == CMD_WORDS);
	assert(c.window[0].words[0] == 0);

	arm();
	cmd_bind(&c, 123, 8, 1);
	cmd_done(&c, 8, 0);
	assert(c.errors & CMD_FAILED);
	assert(c.errors & CMD_ORDER);

	puts("PASS: command recorder bounds, CRA window, overflow, shape and inactive records");
	return 0;
}
