/* SPDX-License-Identifier: GPL-2.0-only */
/* Experimental command/control recorder state. Callers serialize every access. */
#ifndef CMD_CORE_H
#define CMD_CORE_H
#define CMD_PICTURES 300
#define CMD_FIRST 24
#define CMD_LAST 34
#define CMD_WINDOW 11
#define CMD_WORDS 1024
#define CMD_CONTROL 1392
#define CMD_SPS 34
#define CMD_PPS 63
#define CMD_SCALING 1000
#define CMD_SLICE 275
#define CMD_FLAGS 8
#define CMD_PACKED (CMD_SPS + CMD_PPS + CMD_SCALING + CMD_SLICE + CMD_FLAGS)

enum cmd_phase { CMD_OFF, CMD_ARMED, CMD_ACTIVE, CMD_DRAINED, CMD_SEALED };
enum cmd_error {
	CMD_FOREIGN = 1, CMD_OVERFLOW = 2, CMD_EXTENT = 4,
	CMD_ORDER = 8, CMD_FAILED = 16, CMD_SHAPE = 32, CMD_WORDS_FULL = 64,
};
enum cmd_site {
	CMD_SITE_HDR_START = 1, CMD_SITE_HDR_MODE, CMD_SITE_HDR_DIM,
	CMD_SITE_HDR_SHIFT3, CMD_SITE_HDR_TXFM, CMD_SITE_HDR_PCM,
	CMD_SITE_HDR_SPSFLAGS, CMD_SITE_HDR_PPSFLAGS, CMD_SITE_HDR_QP,
	CMD_SITE_HDR_ZERO, CMD_SITE_HDR_FEAT, CMD_SITE_SCL_DIMS,
	CMD_SITE_SCL_DC16, CMD_SITE_SCL_DC32, CMD_SITE_SCL_4,
	CMD_SITE_SCL_8, CMD_SITE_SCL_16, CMD_SITE_SCL_32, CMD_SITE_SCL_OFF,
	CMD_SITE_QP, CMD_SITE_DBLK, CMD_SITE_WT_HDR, CMD_SITE_WT_LUMA,
	CMD_SITE_WT_LUMA_OFF, CMD_SITE_WT_CHR, CMD_SITE_WT_CHR_OFF,
	CMD_SITE_WT_SKIP, CMD_SITE_LOC_CABAC, CMD_SITE_LOC_CTB,
	CMD_SITE_LOC_MV, CMD_SITE_SLICE_META,
};

struct cmd_hist {
	unsigned int picture, poc, type, target, flags, intra;
};
struct cmd_window {
	unsigned int picture, poc, type, nwords, nbytes, inactive;
	unsigned char controls[CMD_CONTROL];
	unsigned int words[CMD_WORDS];
	unsigned short sites[CMD_WORDS];
};
struct cmd_capture {
	unsigned long long run, context, pid, phase, errors;
	unsigned long long pictures, completions, pending;
	struct cmd_hist hist[CMD_PICTURES];
	struct cmd_window window[CMD_WINDOW];
};

static inline int cmd_selected(const struct cmd_capture *c,
			       unsigned long long context)
{
	return c->phase == CMD_ACTIVE && context == c->context;
}

static inline int cmd_detail(const struct cmd_capture *c)
{
	return c->pictures >= CMD_FIRST && c->pictures <= CMD_LAST;
}

static inline struct cmd_window *cmd_slot(struct cmd_capture *c)
{
	if (!cmd_detail(c))
		return 0;
	return &c->window[c->pictures - CMD_FIRST];
}

static inline void cmd_open(struct cmd_capture *c, unsigned long long pid)
{
	if ((c->phase == CMD_ARMED || c->phase == CMD_ACTIVE ||
	     c->phase == CMD_DRAINED) && pid != c->pid)
		c->errors |= CMD_FOREIGN;
}

static inline void cmd_bind(struct cmd_capture *c, unsigned long long pid,
			    unsigned long long context, int hevc)
{
	if (c->phase == CMD_ARMED && pid == c->pid && hevc) {
		c->context = context;
		c->phase = CMD_ACTIVE;
	} else if ((c->phase == CMD_ARMED || c->phase == CMD_ACTIVE ||
		    c->phase == CMD_DRAINED) &&
		   (context != c->context || !hevc || c->phase == CMD_DRAINED)) {
		c->errors |= CMD_FOREIGN;
	}
}

static inline void cmd_start(struct cmd_capture *c, unsigned long long context,
			     unsigned int slices, unsigned int entry_capacity,
			     unsigned int entry_points)
{
	struct cmd_window *w;
	if (!cmd_selected(c, context))
		return;
	if (c->pending)
		c->errors |= CMD_ORDER;
	c->pending = ++c->pictures;
	if (c->pictures > CMD_PICTURES)
		c->errors |= CMD_EXTENT;
	if (slices != 1 || !entry_capacity || entry_capacity > 256 || entry_points)
		c->errors |= CMD_SHAPE;
	if (cmd_detail(c)) {
		w = cmd_slot(c);
		w->picture = (unsigned int)c->pictures;
		w->nbytes = 0;
		w->nwords = 0;
		w->inactive = 0;
	}
}

static inline void cmd_hist_set(struct cmd_capture *c, unsigned int poc,
				unsigned int type, unsigned int target,
				unsigned int flags, unsigned int intra)
{
	struct cmd_hist *h;
	if (!c->pictures || c->pictures > CMD_PICTURES)
		return;
	h = &c->hist[c->pictures - 1];
	h->picture = (unsigned int)c->pictures;
	h->poc = poc;
	h->type = type;
	h->target = target;
	h->flags = flags;
	h->intra = intra;
}

static inline void cmd_controls(struct cmd_capture *c, const unsigned char *packed,
				unsigned int n)
{
	struct cmd_window *w = cmd_slot(c);
	unsigned int i;
	if (!w)
		return;
	if (n > CMD_PACKED)
		n = CMD_PACKED;
	for (i = 0; i < n; i++)
		w->controls[i] = packed[i];
	for (; i < CMD_CONTROL; i++)
		w->controls[i] = 0;
	w->nbytes = CMD_CONTROL;
}

static inline void cmd_word(struct cmd_capture *c, unsigned int site,
			    unsigned int word)
{
	struct cmd_window *w = cmd_slot(c);
	if (!w)
		return;
	if (w->nwords >= CMD_WORDS) {
		c->errors |= CMD_WORDS_FULL | CMD_OVERFLOW;
		return;
	}
	w->sites[w->nwords] = (unsigned short)site;
	w->words[w->nwords] = word;
	w->nwords++;
}

static inline void cmd_inactive(struct cmd_capture *c, unsigned int site)
{
	struct cmd_window *w = cmd_slot(c);
	if (!w)
		return;
	w->inactive |= 1u << (site % 32);
}

static inline void cmd_done(struct cmd_capture *c, unsigned long long context,
			    int success)
{
	if (!cmd_selected(c, context))
		return;
	if (!c->pending)
		c->errors |= CMD_ORDER;
	c->pending = 0;
	c->completions++;
	if (!success)
		c->errors |= CMD_FAILED;
}

static inline void cmd_close(struct cmd_capture *c, unsigned long long context)
{
	if (!cmd_selected(c, context))
		return;
	if (c->pictures != CMD_PICTURES || c->completions != CMD_PICTURES ||
	    c->pending)
		c->errors |= CMD_EXTENT;
	c->phase = CMD_DRAINED;
}

static inline int cmd_seal(struct cmd_capture *c)
{
	if (c->phase != CMD_DRAINED && c->phase != CMD_ARMED)
		return 0;
	if (c->phase == CMD_ARMED)
		c->errors |= CMD_EXTENT;
	c->phase = CMD_SEALED;
	return 1;
}
#endif
