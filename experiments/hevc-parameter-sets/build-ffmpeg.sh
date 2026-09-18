#!/bin/sh
# Build a minimal pinned FFmpeg with and without the parameter-set patch.
#
# usage: build-ffmpeg.sh WORK_DIR [--sanitize]
#
# Produces WORK_DIR/build-base/ffmpeg and WORK_DIR/build-fixed/ffmpeg; with
# --sanitize, only the patched WORK_DIR/build-fixed-san/ffmpeg, built with
# AddressSanitizer and UndefinedBehaviorSanitizer. The build is software-only:
# no VA-API, libdrm or other system libraries are needed. Nothing is installed;
# the only network access is the source fetch, and an existing WORK_DIR/src-base
# at the pinned commit is reused.
set -eu

FFMPEG_GIT=${FFMPEG_GIT:-https://github.com/FFmpeg/FFmpeg.git}
FFMPEG_COMMIT=bf1b838f2ab88b4f8fd83443325c782ea0e0f7fa  # n9.0.1

here=$(cd "$(dirname "$0")" && pwd)
patch_file=$here/ffmpeg-n9.0.1-hevc-pending-parameter-sets.patch

[ $# -ge 1 ] || { echo "usage: $0 WORK_DIR [--sanitize]" >&2; exit 2; }
mkdir -p "$1"
work=$(cd "$1" && pwd)
suffix=
extra=
if [ "${2:-}" = --sanitize ]; then
  suffix=-san
  extra="--disable-stripping --disable-optimizations --enable-debug=3"
  san="-fsanitize=address,undefined -fno-sanitize-recover=undefined -fno-omit-frame-pointer"
fi

if [ ! -d "$work/src-base/.git" ]; then
  git init -q "$work/src-base"
  git -C "$work/src-base" fetch -q --depth 1 "$FFMPEG_GIT" "$FFMPEG_COMMIT"
  git -C "$work/src-base" -c advice.detachedHead=false checkout -q FETCH_HEAD
fi
head=$(git -C "$work/src-base" rev-parse HEAD)
[ "$head" = "$FFMPEG_COMMIT" ] || { echo "src-base is at $head, expected $FFMPEG_COMMIT" >&2; exit 1; }
[ -z "$(git -C "$work/src-base" status --porcelain)" ] || { echo "src-base has local changes" >&2; exit 1; }

# Reuse src-fixed only when a marker records this exact patch.
patch_sum=$(sha256sum "$patch_file" | cut -d' ' -f1)
if [ "$(cat "$work/src-fixed.patch-sha256" 2>/dev/null)" != "$patch_sum" ] ||
   [ "$(git -C "$work/src-fixed" rev-parse HEAD 2>/dev/null)" != "$FFMPEG_COMMIT" ]; then
  rm -rf "$work/src-fixed" "$work/build-fixed" "$work/build-fixed-san" "$work/src-fixed.patch-sha256"
  git -C "$work/src-base" worktree prune
  git -C "$work/src-base" worktree add -q --detach "$work/src-fixed" "$FFMPEG_COMMIT"
  git -C "$work/src-fixed" apply --check "$patch_file"
  git -C "$work/src-fixed" apply "$patch_file"
  echo "$patch_sum" >"$work/src-fixed.patch-sha256"
fi

build() {
  src=$1
  out=$2
  mkdir -p "$out"
  if [ ! -f "$out/config.h" ]; then
    (cd "$out" && "$src/configure" \
      --disable-everything --disable-doc --disable-network --disable-autodetect \
      --enable-decoder=hevc,rawvideo --enable-encoder=rawvideo,wrapped_avframe \
      --enable-parser=hevc --enable-demuxer=hevc,rawvideo \
      --enable-muxer=rawvideo,framemd5,null --enable-protocol=file,pipe \
      --enable-filter=scale,format,null,copy,showinfo --enable-swscale \
      $extra ${san:+--extra-cflags="$san" --extra-ldflags="$san"} >configure.log) \
      || { tail -20 "$out/configure.log" "$out/ffbuild/config.log" >&2; exit 1; }
  fi
  make -C "$out" -j"$(nproc)" ffmpeg >"$out/make.log" 2>&1 || { tail -40 "$out/make.log" >&2; exit 1; }
  echo "$out/ffmpeg"
}

if [ -z "$suffix" ]; then
  build "$work/src-base" "$work/build-base"
fi
build "$work/src-fixed" "$work/build-fixed$suffix"
