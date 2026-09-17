/* SPDX-License-Identifier: GPL-2.0-only */
/* Experimental recorder state. Callers serialize every access. No pointers. */
#ifndef AVD_TRACE_CORE_H
#define AVD_TRACE_CORE_H
#define ATR_CAPACITY 2048
#define ATR_VALUES 72
#define ATR_PICTURES 300
#define ATR_FIRST 24
#define ATR_LAST 34

enum atr_phase { ATR_OFF, ATR_ARMED, ATR_ACTIVE, ATR_DRAINED, ATR_SEALED };
enum atr_kind { ATR_START = 1, ATR_DONE, ATR_TABLE, ATR_LIST, ATR_MOTION };
enum atr_error {
	ATR_FOREIGN = 1, ATR_OVERFLOW = 2, ATR_EXTENT = 4,
	ATR_ORDER = 8, ATR_FAILED = 16, ATR_SHAPE = 32,
};
struct atr_record {
	unsigned long long run, context, sequence, kind, picture;
	unsigned long long v[ATR_VALUES];
};
struct atr_capture {
	unsigned long long run, context, pid, phase, errors;
	unsigned long long count, attempted, pictures, completions, pending;
	struct atr_record records[ATR_CAPACITY];
};

/* Same-process capability probes may open/close without ever decoding. */
static inline void atr_open(struct atr_capture *c, unsigned long long pid)
{
	if ((c->phase == ATR_ARMED || c->phase == ATR_ACTIVE ||
	     c->phase == ATR_DRAINED) && pid != c->pid)
		c->errors |= ATR_FOREIGN;
}

static inline void atr_bind(struct atr_capture *c, unsigned long long pid,
			    unsigned long long context, int hevc)
{
	if (c->phase == ATR_ARMED && pid == c->pid && hevc) {
		c->context = context;
		c->phase = ATR_ACTIVE;
	} else if ((c->phase == ATR_ARMED || c->phase == ATR_ACTIVE ||
	     c->phase == ATR_DRAINED) &&
		   (context != c->context || !hevc || c->phase == ATR_DRAINED)) {
		c->errors |= ATR_FOREIGN;
	}
}

static inline int atr_selected(const struct atr_capture *c,
			       unsigned long long context)
{
	return c->phase == ATR_ACTIVE && context == c->context;
}

static inline struct atr_record *atr_append(struct atr_capture *c,
					   unsigned long long context,
					   unsigned int kind)
{
	struct atr_record *r;
	if (!atr_selected(c, context))
		return 0;
	c->attempted++;
	if (c->count == ATR_CAPACITY) {
		c->errors |= ATR_OVERFLOW;
		return 0;
	}
	r = &c->records[c->count++];
	r->run = c->run;
	r->context = context;
	r->sequence = c->attempted;
	r->kind = kind;
	r->picture = c->pictures;
	return r;
}

static inline void atr_start(struct atr_capture *c, unsigned long long context,
			     unsigned int slices, unsigned int entry_points)
{
	if (!atr_selected(c, context))
		return;
	if (c->pending)
		c->errors |= ATR_ORDER;
	c->pending = ++c->pictures;
	if (c->pictures > ATR_PICTURES)
		c->errors |= ATR_EXTENT;
	if (slices != 1 || entry_points)
		c->errors |= ATR_SHAPE;
}

static inline void atr_done(struct atr_capture *c, unsigned long long context,
			    int success)
{
	if (!atr_selected(c, context))
		return;
	if (!c->pending)
		c->errors |= ATR_ORDER;
	c->pending = 0;
	c->completions++;
	if (!success)
		c->errors |= ATR_FAILED;
}

static inline void atr_close(struct atr_capture *c, unsigned long long context)
{
	if (!atr_selected(c, context))
		return;
	if (c->pictures != ATR_PICTURES || c->completions != ATR_PICTURES ||
	    c->pending)
		c->errors |= ATR_EXTENT;
	c->phase = ATR_DRAINED;
}

/* Control caller must additionally prove all device contexts are closed. */
static inline int atr_seal(struct atr_capture *c)
{
	if (c->phase != ATR_DRAINED && c->phase != ATR_ARMED)
		return 0;
	if (c->phase == ATR_ARMED)
		c->errors |= ATR_EXTENT;
	c->phase = ATR_SEALED;
	return 1;
}
#endif
