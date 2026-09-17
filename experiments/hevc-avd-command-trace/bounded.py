#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Apply storage-only changes to private recorder copies, preserving wire rows.

Accepted hevc-avd-trace sources/captures are never edited. Its copied snapshot
reader pins one sealed capture; fresh arm requires off and no pinned reader.
"""
from pathlib import Path


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('bounded storage patch drift: ' + old[:70])
    return text.replace(old, new, 1)


def constrain(path: Path, command=False):
    text = path.read_text()
    prefix = 'cmd' if command else 'atr'
    lock = prefix + '_control_lock'
    # The control mutex serializes allocation, reader opens and replacement.
    needle = '\tmutex_lock(&' + lock + ');\n\tif (arm) {'
    text = replace_once(text, needle, '''\tmutex_lock(&LOCK);
	/* No capture replacement and no free while a snapshot reader pins it. */
	if (snapshot_busy || (arm && capture)) {
		mutex_unlock(&LOCK);
		return -EBUSY;
	}
	if (arm) {'''.replace('LOCK', lock))
    start = text.index('static int snapshot_show(')
    end = text.index('/* A fixed-size status read', start) if not command else text.index('static ssize_t status_read', start)
    if command:
        rows = '''static unsigned int snapshot_rows(const struct cmd_capture *c)
{
	return 1 + CMD_PICTURES + 2 * CMD_WINDOW;
}
static int snapshot_row(struct seq_file *s, unsigned int row)
{
	const struct cmd_capture *c = s->private;
	unsigned int j;
	if (!row) {
		seq_printf(s, "H 2 %llu %llu %llu %llu %llu %llu %u %u %u %u %zu %zu\\n",
			c->run, c->context, c->phase, c->errors, c->pictures,
			c->completions, CMD_CAPACITY_MARK, CMD_FIRST, CMD_LAST,
			CMD_WORDS, sizeof(*c), sizeof(struct cmd_window));
	} else if (row <= CMD_PICTURES) {
		const struct cmd_hist *h = &c->hist[row - 1];
		seq_printf(s, "P %u %u %u %u %u %u\\n", h->picture, h->poc,
			h->type, h->target, h->flags, h->intra);
	} else {
		unsigned int slot = (row - 1 - CMD_PICTURES) / 2;
		const struct cmd_window *w = &c->window[slot];
		if ((row - 1 - CMD_PICTURES) % 2 == 0) {
			seq_printf(s, "W %u %u %u %u %u %u %u %u %u %u", w->picture,
				w->poc, w->type, w->nwords, w->nbytes, w->inactive,
				w->decomp, w->revision, w->quirks, w->bytesperline);
			for (j = 0; j < w->nwords; j++)
				seq_printf(s, " %u %u", w->sites[j], w->words[j]);
		} else {
			seq_putc(s, 'C');
			for (j = 0; j < CMD_CONTROL; j++)
				seq_printf(s, " %u", w->controls[j]);
		}
		seq_putc(s, '\\n');
	}
	return 0;
}
'''
    else:
        rows = '''static unsigned int snapshot_rows(const struct atr_capture *c)
{
	return 1 + c->count;
}
static int snapshot_row(struct seq_file *s, unsigned int row)
{
	const struct atr_capture *c = s->private;
	unsigned int j;
	if (!row) {
		seq_printf(s, "H 2 %llu %llu %llu %llu %llu %llu %llu %llu %u %u %u %zu\\n",
			c->run, c->context, c->phase, c->errors, c->count, c->attempted,
			c->pictures, c->completions, ATR_CAPACITY, ATR_FIRST, ATR_LAST,
			sizeof(struct atr_record));
	} else {
		const struct atr_record *r = &c->records[row - 1];
		seq_printf(s, "R %llu %llu %llu %llu %llu", r->run, r->context,
			r->sequence, r->kind, r->picture);
		for (j = 0; j < ATR_VALUES; j++)
			seq_printf(s, " %llu", r->v[j]);
		seq_putc(s, '\\n');
	}
	return 0;
}
'''
    rows += '\n#define BND_CONTROL_LOCK '+lock+'\n#define BND_LOCK '+prefix+'_lock\n'
    rows += '#define BND_SEALED '+prefix.upper()+'_SEALED\n#include "bounded-snapshot.h"\n\n'
    path.write_text(text[:start] + rows + text[end:])
