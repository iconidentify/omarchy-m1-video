/* SPDX-License-Identifier: GPL-2.0 */
/*
 * Userspace harness for the actual avd_buf_alloc()/avd_buf_free() text.
 *
 * This is NOT a kernel module and it is never installed.  It supplies the
 * minimum synthetic environment those two functions need, plus a coherent-DMA
 * stand-in with deterministic fault injection and full allocation accounting,
 * so a failed allocation followed by a differently sized retry can be observed
 * without a device.
 *
 * The functions under test are not written here.  tests.py extracts them, and
 * `struct avd_buf`, verbatim from the pinned shipped-patched sources into
 * extracted.h, which this file includes.  Any handwritten copy would test the
 * copy instead of the driver.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef unsigned long dma_addr_t;

#define GFP_KERNEL 0
#define ENOMEM 12

struct avd_dev {
	void *dev;
};

/* struct avd_buf, extracted verbatim from the pinned avd.h. */
#include "extracted-types.h"

/* ---- coherent DMA stand-in ------------------------------------------- */

#define MAX_LIVE 64

static struct {
	void *cpu;
	dma_addr_t addr;
	unsigned long size;
} live[MAX_LIVE];

static int live_count;
static int alloc_calls;
static int alloc_failures;
static int free_calls;
static dma_addr_t next_addr = 0x1000;

/* Call indices (1-based) whose allocation must fail. */
static int fail_at[8];
static int fail_at_count;

static int should_fail(int call)
{
	for (int i = 0; i < fail_at_count; i++)
		if (fail_at[i] == call)
			return 1;
	return 0;
}

static void *dma_alloc_coherent(void *dev, unsigned long size,
				dma_addr_t *addr, int flags)
{
	(void)dev;
	(void)flags;
	alloc_calls++;
	if (should_fail(alloc_calls) || size == 0 || live_count == MAX_LIVE) {
		alloc_failures++;
		return NULL;
	}
	void *cpu = malloc(size);
	if (!cpu) {
		alloc_failures++;
		return NULL;
	}
	/* Poison, so a caller that relies on zeroed storage is visible. */
	memset(cpu, 0xA5, size);
	*addr = next_addr;
	next_addr += 0x1000;
	live[live_count].cpu = cpu;
	live[live_count].addr = *addr;
	live[live_count].size = size;
	live_count++;
	return cpu;
}

static void dma_free_coherent(void *dev, unsigned long size, void *cpu,
			      dma_addr_t addr)
{
	(void)dev;
	free_calls++;
	if (!cpu) {
		printf("FAULT free-null\n");
		exit(90);
	}
	for (int i = 0; i < live_count; i++) {
		if (live[i].cpu != cpu)
			continue;
		if (live[i].size != size) {
			printf("FAULT free-size-mismatch want=%lu got=%lu\n",
			       live[i].size, size);
			exit(91);
		}
		if (live[i].addr != addr) {
			printf("FAULT free-addr-mismatch\n");
			exit(92);
		}
		free(cpu);
		live[i] = live[live_count - 1];
		live_count--;
		return;
	}
	printf("FAULT free-unknown\n");
	exit(93);
}

/* ---- functions under test -------------------------------------------- */

/* avd_buf_alloc() and avd_buf_free(), extracted verbatim. */
#include "extracted.h"

/* ---- scenarios -------------------------------------------------------- */

static struct avd_dev dev_storage;
static struct avd_dev *dev = &dev_storage;
static struct avd_buf buf;

static void report(const char *step, int ret)
{
	printf("%s ret=%d cpu=%s size=%lu allocs=%d fails=%d frees=%d live=%d\n",
	       step, ret, buf.cpu ? "set" : "null", (unsigned long)buf.size,
	       alloc_calls, alloc_failures, free_calls, live_count);
}

static void parse_failures(int argc, char **argv, int from)
{
	for (int i = from; i < argc && fail_at_count < 8; i++)
		fail_at[fail_at_count++] = atoi(argv[i]);
}

int main(int argc, char **argv)
{
	if (argc < 2) {
		printf("usage: harness <scenario> [failing-call-index ...]\n");
		return 2;
	}
	const char *scenario = argv[1];
	parse_failures(argc, argv, 2);

	if (!strcmp(scenario, "single")) {
		report("alloc", avd_buf_alloc(dev, &buf, 4096));
	} else if (!strcmp(scenario, "retry")) {
		report("first", avd_buf_alloc(dev, &buf, 4096));
		report("second", avd_buf_alloc(dev, &buf, 2048));
	} else if (!strcmp(scenario, "retry-equal")) {
		report("first", avd_buf_alloc(dev, &buf, 4096));
		report("second", avd_buf_alloc(dev, &buf, 4096));
	} else if (!strcmp(scenario, "retry-larger")) {
		report("first", avd_buf_alloc(dev, &buf, 4096));
		report("second", avd_buf_alloc(dev, &buf, 8192));
	} else if (!strcmp(scenario, "zero")) {
		report("alloc", avd_buf_alloc(dev, &buf, 0));
	} else if (!strcmp(scenario, "zero-after-failure")) {
		report("first", avd_buf_alloc(dev, &buf, 4096));
		report("second", avd_buf_alloc(dev, &buf, 0));
	} else if (!strcmp(scenario, "free")) {
		report("alloc", avd_buf_alloc(dev, &buf, 4096));
		avd_buf_free(dev, &buf);
		report("free", 0);
	} else if (!strcmp(scenario, "free-twice")) {
		report("alloc", avd_buf_alloc(dev, &buf, 4096));
		avd_buf_free(dev, &buf);
		avd_buf_free(dev, &buf);
		report("free", 0);
	} else if (!strcmp(scenario, "free-after-failure")) {
		report("alloc", avd_buf_alloc(dev, &buf, 4096));
		avd_buf_free(dev, &buf);
		report("free", 0);
	} else if (!strcmp(scenario, "use-after-retry")) {
		/* A caller that trusts the return value writes the buffer. */
		report("first", avd_buf_alloc(dev, &buf, 4096));
		int ret = avd_buf_alloc(dev, &buf, 2048);
		report("second", ret);
		if (ret == 0 && !buf.cpu) {
			printf("FAULT success-without-storage\n");
			return 94;
		}
		if (ret == 0)
			memset(buf.cpu, 0, buf.size);
		report("write", ret);
	} else if (!strcmp(scenario, "sequence")) {
		/* Deterministic resize walk, then release; must balance. */
		static const unsigned long sizes[] = {
			512, 4096, 4096, 1024, 8192, 8192, 256, 16384, 16384, 64
		};
		for (unsigned i = 0; i < sizeof(sizes) / sizeof(sizes[0]); i++) {
			int ret = avd_buf_alloc(dev, &buf, sizes[i]);
			if (ret == 0 && !buf.cpu) {
				printf("FAULT success-without-storage step=%u\n", i);
				return 94;
			}
			if (ret == 0)
				memset(buf.cpu, 0, buf.size);
		}
		avd_buf_free(dev, &buf);
		report("sequence", 0);
	} else {
		printf("unknown scenario %s\n", scenario);
		return 2;
	}

	/* Release whatever the scenario still holds, so a leak checker sees a
	 * clean exit and every scenario ends with a balanced accounting. */
	avd_buf_free(dev, &buf);

	printf("END allocs=%d fails=%d frees=%d live=%d\n",
	       alloc_calls, alloc_failures, free_calls, live_count);
	if (live_count) {
		printf("FAULT leaked=%d\n", live_count);
		return 95;
	}
	return 0;
}
