/* SPDX-License-Identifier: MIT
 * Verbatim selected definitions from AsahiLinux/linux avd-inst.h.
 * Attribution: the Asahi Linux Contributors; original AVD reverse engineering
 * by Eileen Yoon and contributors. Source/revision/hash: source-map.json.
 * Original file carries SPDX-License-Identifier: MIT (retained above).
 * Extracted definitions only; BIT/GENMASK/FIELD_PREP supplied by the test.
 */
#define AVD_OP_SL_REF			FIELD_PREP(GENMASK(31, 24), 0x2d)
#define AVD_OP_SL_REF_MAX_MERGE(v)	FIELD_PREP(GENMASK(3, 1), v)
#define AVD_OP_SL_REF_FLAG0(v)		FIELD_PREP(BIT(4), !!(v))
#define AVD_OP_SL_REF_FLAG_CABAC(v)	FIELD_PREP(BIT(5), !!(v))
#define AVD_OP_SL_REF_FLAG1(v)		FIELD_PREP(BIT(6), !!(v))
#define AVD_OP_SL_REF_NUM_L0(v)		FIELD_PREP(GENMASK(15, 11), v)
#define AVD_OP_SL_REF_NUM_L1(v)		FIELD_PREP(GENMASK(10, 7), v)
#define AVD_OP_SL_REF_FLAG2(v)		FIELD_PREP(BIT(15), !!(v))
#define AVD_OP_SL_REF_SLICE_P(v)	FIELD_PREP(BIT(16), !!(v))
#define AVD_OP_SL_REF_SLICE_I(v)	FIELD_PREP(BIT(17), !!(v))
#define AVD_OP_SL_REF_SLICE_B(v)	FIELD_PREP(BIT(18), !!(v))
#define AVD_OP_REF			FIELD_PREP(GENMASK(31, 20), 0x2dc)
#define AVD_OP_REF_DBP_IDX(v)		FIELD_PREP(GENMASK(3, 0), v)
#define AVD_OP_REF_LOOP_IDX(v)		FIELD_PREP(GENMASK(7, 4), v)
#define AVD_OP_REF_LIST_IDX(v)		FIELD_PREP(GENMASK(11, 8), v)
#define AVD_REF_NUM(v)			FIELD_PREP(GENMASK(31, 28), v)
#define AVD_REF_FLAG_CONST		FIELD_PREP(BIT(24), 1)
#define AVD_REF_FLAG_LONG(v)		FIELD_PREP(BIT(17), !!(v))
#define AVD_REF_DELTA_POC(v)		FIELD_PREP(GENMASK(16, 0), v)
