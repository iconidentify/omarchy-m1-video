/* SPDX-License-Identifier: GPL-2.0 */
/* Userspace harness for extracted avd_av1_start/alloc_bufs/stop. No module. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef unsigned long dma_addr_t;
#define GFP_KERNEL 0
#define ENOMEM 12

struct avd_dev { void *dev; };
#include "actual-buf.h" /* exact pinned struct; other contexts below are synthetic */
struct avd_ctx { struct avd_dev *dev; void *priv; };

#define MAX_LIVE 64
static struct { void *cpu; dma_addr_t addr; unsigned long size; } live[MAX_LIVE];
static int live_count, alloc_calls, alloc_failures, free_calls;
static dma_addr_t next_addr = 0x1000;
static int fail_at[8], fail_at_count, fail_context;

static int should_fail(int call)
{
	for (int i = 0; i < fail_at_count; i++)
		if (fail_at[i] == call)
			return 1;
	return 0;
}

static void *dma_alloc_coherent(void *dev, unsigned long size, dma_addr_t *addr, int flags)
{
	(void)dev; (void)flags;
	alloc_calls++;
	if (should_fail(alloc_calls) || size == 0 || live_count == MAX_LIVE) {
		alloc_failures++;
		return NULL;
	}
	void *cpu = malloc(size);
	if (!cpu) { alloc_failures++; return NULL; }
	memset(cpu, 0xA5, size);
	*addr = next_addr;
	next_addr += 0x1000;
	live[live_count].cpu = cpu;
	live[live_count].addr = *addr;
	live[live_count].size = size;
	live_count++;
	return cpu;
}

static void dma_free_coherent(void *dev, unsigned long size, void *cpu, dma_addr_t addr)
{
	(void)dev;
	free_calls++;
	if (!cpu) { printf("FAULT free-null\n"); exit(90); }
	for (int i = 0; i < live_count; i++) {
		if (live[i].cpu != cpu)
			continue;
		if (live[i].size != size) { printf("FAULT free-size\n"); exit(91); }
		if (live[i].addr != addr) { printf("FAULT free-addr\n"); exit(92); }
		free(cpu);
		live[i] = live[--live_count];
		return;
	}
	printf("FAULT free-unknown\n");
	exit(93);
}

static void *kzalloc(unsigned long n, int flags)
{
	(void)flags;
	if (fail_context)
		return NULL;
	return calloc(1, n);
}
#define kfree(p) free(p)

#define fifo_size() 12582912u
struct avd_av1_cdfs { unsigned char opaque[9166]; };

struct avd_av1_ctx {
	struct {
		struct avd_buf inst;
		struct avd_buf pipe_state;
		struct avd_buf probs;
		struct avd_buf rf_above_info;
		struct avd_buf az_above;
		struct avd_buf ip_above;
		struct avd_buf lf_above;
		struct avd_buf lf_above_info;
		struct avd_buf lf_left;
		struct avd_buf lf_left_info;
		struct avd_buf sr_left;
		struct avd_buf rf_left;
		struct avd_buf rf_left_info;
		struct avd_buf seg;
		struct avd_buf mv_above_info;
	} bufs;
};

#include "extracted.h"

int main(int argc, char **argv)
{
	int failure = argc > 1 ? atoi(argv[1]) : 0;
	fail_at_count = failure > 0 ? 1 : 0;
	fail_at[0] = failure;
	fail_context = failure < 0;
	struct avd_dev dev = {0};
	struct avd_ctx ctx = {.dev = &dev};
	int ret = avd_av1_start(&ctx);
	int bad = 0;
	if (failure == 0 && ret != 0)
		bad = 1;
	if (failure != 0 && (ret != -ENOMEM || ctx.priv != NULL))
		bad = 1;
	if (ret == 0) {
		avd_av1_stop(&ctx);
		ctx.priv = NULL;
	}
	if (argc > 2) {
		/* Framework clears priv; stop is only repeated on NULL, not a freed pointer. */
		avd_av1_stop(&ctx);
		avd_av1_stop(&ctx);
	}
	int leaked = live_count;
	while (live_count)
		free(live[--live_count].cpu);
	printf("ret=%d leaked=%d allocs=%d frees=%d live_at_verdict=%d\n",
	       ret, leaked, alloc_calls, free_calls, leaked);
	return bad ? 96 : leaked ? 95 : 0;
}
