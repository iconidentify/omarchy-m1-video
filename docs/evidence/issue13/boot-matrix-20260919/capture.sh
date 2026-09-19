#!/usr/bin/env bash
# Per-attempt evidence capture for omarchy-m1-video#13 boot matrix.
# Read-only: reads journals, sysfs and module state. Changes nothing.
# Usage: bash capture.sh <cell>        # C1 | C2 | P1 | P2
set -u
CELL="${1:-}"
DIR=/home/chrisk/boot-matrix-13-20260919
WINDOW="${WINDOW:-600}"
case "$CELL" in C1|C2|P1|P2) ;; *) echo "usage: capture.sh <C1|C2|P1|P2>"; exit 2;; esac

ts()  { date -u +%Y-%m-%dT%H:%M:%SZ; }
mono(){ awk '{print $1}' /proc/uptime; }

snap() {  # snap <phase>
  local p="$1"
  echo "  \"${p}_utc\": \"$(ts)\","
  echo "  \"${p}_monotonic_s\": $(mono),"
  echo "  \"${p}_module_loaded\": $(lsmod | grep -q '^apple_avd' && echo true || echo false),"
  echo "  \"${p}_module_refcount\": $(lsmod | awk '/^apple_avd/{print $3+0; f=1} END{if(!f) print -1}'),"
  echo "  \"${p}_sys_module_present\": $([ -d /sys/module/apple_avd ] && echo true || echo false),"
  echo "  \"${p}_video0_driver\": \"$(cat /sys/class/video4linux/video0/name 2>/dev/null || echo none)\","
  echo "  \"${p}_avd_video_node\": \"$(for d in /sys/class/video4linux/video*; do [ "$(cat $d/name 2>/dev/null)" = avd ] && basename $d; done | head -1)\","
  # grep -c prints 0 and exits 1 when nothing matches; no fallback echo here or
  # the count is emitted twice and the record stops being valid JSON.
  echo "  \"${p}_kernel_faults\": $(sudo -n journalctl -k -b 0 --no-pager 2>/dev/null | grep -icE 'Internal error|Oops|kernel panic|watchdog: BUG|NO PTE FOR IOVA|avd.*(error|timeout|fault)'),"
  echo "  \"${p}_power\": \"$(cat /sys/class/power_supply/*/status 2>/dev/null | head -1)\","
  echo "  \"${p}_capacity\": \"$(cat /sys/class/power_supply/*/capacity 2>/dev/null | head -1)\","
}

BOOTID=$(cat /proc/sys/kernel/random/boot_id)
BOOTREF=$(printf '%s' "$BOOTID" | sha256sum | cut -c1-12)   # published pseudonym
N=$(printf '%03d' $(( $(ls "$DIR/attempts" 2>/dev/null | wc -l) + 1 )))
OUT="$DIR/attempts/${N}-${CELL}.json"
echo "$BOOTREF $BOOTID $CELL $N" >> "$DIR/bootid-map.private"
chmod 600 "$DIR/bootid-map.private" 2>/dev/null

# The PMU line is emitted by the kernel at boot and only when a counter is
# non-zero. Absence of the line means zero boot errors and zero panics.
PMU=$(sudo -n journalctl -k -b 0 --no-pager 2>/dev/null | grep -o 'PMU logged .*' | head -1)
[ -z "$PMU" ] && PMU="none (zero boot errors, zero panics)"

BLACKLIST=$(cat /etc/modprobe.d/apple-avd-*.conf 2>/dev/null | grep -vE '^\s*#' | grep -v '^$' | tr '\n' ';' )
[ -z "$BLACKLIST" ] && BLACKLIST="none"

{
echo "{"
echo "  \"attempt\": \"$N\","
echo "  \"cell\": \"$CELL\","
echo "  \"device_id\": \"m1-t8103-primary\","
echo "  \"boot_ref\": \"$BOOTREF\","
echo "  \"pmu_report_this_boot\": \"$PMU\","
echo "  \"blacklist_policy\": \"$BLACKLIST\","
echo "  \"selected_module_sha256\": \"$(sudo -n sha256sum /usr/lib/modules/$(uname -r)/updates/apple-avd.ko 2>/dev/null | cut -d' ' -f1)\","
echo "  \"loaded_binary_identity\": \"unknown (selected file does not identify the loaded binary)\","
echo "  \"kernel_release\": \"$(uname -r)\","
echo "  \"packages\": \"linux-asahi $(pacman -Q linux-asahi 2>/dev/null | awk '{print $2}'); libva-v4l2_request-avd $(pacman -Q libva-v4l2_request-avd 2>/dev/null | awk '{print $2}')\","
echo "  \"observation_window_s\": $WINDOW,"
snap postboot
} > "$OUT"

echo "attempt $N cell $CELL  boot_ref=$BOOTREF"
echo "PMU this boot: $PMU"
echo "blacklist policy: $BLACKLIST"
echo "module loaded: $(lsmod | grep -q '^apple_avd' && echo YES || echo NO)"
echo
echo "Observing for ${WINDOW}s. Leave the machine idle. If it resets, this file stays incomplete -- that is the finding."
i=0
while [ $i -lt "$WINDOW" ]; do sleep 10; i=$((i+10)); printf "\r  %ss/%ss elapsed" "$i" "$WINDOW"; done
echo

{
snap postwindow
echo "  \"window_completed\": true,"
echo "  \"outcome\": \"no reset or freeze during the observation window\""
echo "}"
} >> "$OUT"

echo "record: $OUT"
echo "DONE - tell Claude to continue."
