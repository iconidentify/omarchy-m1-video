/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "avd-trace-core.h"
static struct atr_capture c;
static void arm(void)
{
	memset(&c, 0, sizeof(c));
	c.run = 1; c.pid = 123; c.phase = ATR_ARMED;
}
int main(void)
{
	struct atr_record *r;
	assert(sizeof(struct atr_record) == 616);
	assert(sizeof(struct atr_capture) == 1261648);
	/* Default off, mismatched PID, additional context, and stale owner. */
	atr_bind(&c, 123, 8, 1); assert(!atr_append(&c, 8, ATR_START));
	arm(); atr_open(&c, 124); assert(c.errors == ATR_FOREIGN);
	assert(c.count == 0 && c.phase == ATR_ARMED);
	atr_bind(&c, 123, 8, 1); assert(c.phase == ATR_ACTIVE);
	assert(!atr_append(&c, 7, ATR_START));
	atr_bind(&c, 123, 9, 1); assert(c.context == 8);
	arm(); atr_open(&c,123); atr_close(&c,7);
	assert(c.phase == ATR_ARMED && !c.errors); /* harmless probe */
	atr_bind(&c,123,8,0); assert(c.errors == ATR_FOREIGN);
	/* Max designed one-slice extent: 600 + 11*(16+32+1). */
	arm(); atr_bind(&c, 123, 8, 1);
	for (unsigned int p = 1; p <= 300; p++) {
		atr_start(&c, 8, 1, 0);
		r=atr_append(&c, 8, ATR_START); assert(r && r->picture == p);
		if (p >= 24 && p <= 34)
			for (unsigned int i=0; i<49; i++) assert(atr_append(&c, 8, ATR_TABLE));
		assert(atr_append(&c, 8, ATR_DONE)); atr_done(&c, 8, 1);
	}
	atr_close(&c, 8); assert(c.phase == ATR_DRAINED && !c.errors);
	assert(atr_seal(&c)); assert(c.phase == ATR_SEALED);
	assert(c.count == 1139 && c.attempted == 1139);
	assert(!atr_append(&c, 8, ATR_START));
	atr_open(&c, 1); assert(!c.errors); /* sealed snapshot immutable */
	/* A second decode context after the selected close invalidates the run. */
	arm(); atr_bind(&c,123,8,1); c.pictures=c.completions=300; atr_close(&c,8);
	atr_bind(&c,123,9,1);assert(c.errors & ATR_FOREIGN);assert(atr_seal(&c));
	arm();assert(atr_seal(&c));assert(c.errors & ATR_EXTENT);
	/* Every failure remains sticky; full storage never overwrites old data. */
	arm(); atr_bind(&c,123,8,1);
	for(unsigned int i=0;i<ATR_CAPACITY;i++) assert(atr_append(&c,8,ATR_TABLE));
	assert(!atr_append(&c,8,ATR_TABLE)); assert(c.errors & ATR_OVERFLOW);
	assert(c.attempted == ATR_CAPACITY+1 && c.records[0].sequence == 1);
	arm();atr_bind(&c,123,8,1);atr_start(&c,8,2,0);assert(c.errors & ATR_SHAPE);
	arm();atr_bind(&c,123,8,1);atr_start(&c,8,1,1);assert(c.errors & ATR_SHAPE);
	arm();atr_bind(&c,123,8,1);atr_done(&c,8,0);assert(c.errors & ATR_FAILED);assert(c.errors & ATR_ORDER);
	arm();atr_bind(&c,123,8,1);atr_start(&c,8,1,0);atr_start(&c,8,1,0);assert(c.errors & ATR_ORDER);
	atr_close(&c,8);assert(c.errors & ATR_EXTENT);
	arm();atr_bind(&c,123,8,1);c.pictures=300;atr_start(&c,8,1,0);assert(c.errors & ATR_EXTENT);
	puts("PASS: actual shared C recorder transitions, 1139-record bound, overflow and rejection states");
	return 0;
}
