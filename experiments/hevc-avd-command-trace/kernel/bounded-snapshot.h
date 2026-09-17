/* SPDX-License-Identifier: GPL-2.0-only */
/* Included once per recorder. The sealed capture is immutable and pinned by
 * snapshot_busy under the control mutex. control_write refuses free/replacement
 * while pinned. Render one row per seq item, not the whole capture at once. */
static void *snapshot_seq_start(struct seq_file *s, loff_t *pos)
{
	return *pos >= 0 && *pos < snapshot_rows(s->private) ?
		(void *)(unsigned long)(*pos + 1) : NULL;
}

static void *snapshot_seq_next(struct seq_file *s, void *v, loff_t *pos)
{
	++*pos;
	return snapshot_seq_start(s, pos);
}

static void snapshot_seq_stop(struct seq_file *s, void *v) {}

static int snapshot_seq_show(struct seq_file *s, void *v)
{
	return snapshot_row(s, (unsigned long)v - 1);
}

static const struct seq_operations snapshot_seq_ops = {
	.start = snapshot_seq_start, .next = snapshot_seq_next,
	.stop = snapshot_seq_stop, .show = snapshot_seq_show,
};

static int snapshot_open(struct inode *inode, struct file *file)
{
	unsigned long flags;
	int ret = -EBUSY;
	bool sealed;
	mutex_lock(&BND_CONTROL_LOCK);
	spin_lock_irqsave(&BND_LOCK, flags);
	sealed = capture && capture->phase == BND_SEALED;
	spin_unlock_irqrestore(&BND_LOCK, flags);
	if (sealed && !snapshot_busy) {
		ret = seq_open(file, &snapshot_seq_ops);
		if (!ret) {
			((struct seq_file *)file->private_data)->private = capture;
			snapshot_busy = true;
		}
	}
	mutex_unlock(&BND_CONTROL_LOCK);
	return ret;
}

static int snapshot_release(struct inode *inode, struct file *file)
{
	int ret;
	mutex_lock(&BND_CONTROL_LOCK);
	ret = seq_release(inode, file);
	snapshot_busy = false;
	mutex_unlock(&BND_CONTROL_LOCK);
	return ret;
}
