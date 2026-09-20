// Copyright 2026 The omarchy-m1-video contributors
// SPDX-License-Identifier: BSD-3-Clause
#ifndef CONTENT_COMMON_APPLE_AVD_GPU_PERMISSIONS_LINUX_H_
#define CONTENT_COMMON_APPLE_AVD_GPU_PERMISSIONS_LINUX_H_

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "content/common/content_export.h"

namespace content::apple_avd {

struct CharacterDevice {
  uint32_t major;
  uint32_t minor;
  uint64_t filesystem;
  uint64_t inode;
  bool operator==(const CharacterDevice&) const = default;
};

// Implementations return no value on missing, malformed or inaccessible input.
// GetCharacterDevice must reject symlinks, non-character files and non-root
// owners. ReadMetadata returns at most 4096 bytes, rejecting larger files.
class DeviceFileSystem {
 public:
  virtual ~DeviceFileSystem() = default;
  virtual std::optional<CharacterDevice> GetCharacterDevice(
      const std::string& path) = 0;
  virtual std::optional<std::string> CanonicalPath(const std::string& path) = 0;
  virtual std::optional<std::string> ReadMetadata(const std::string& path) = 0;
};

class CONTENT_EXPORT NativeDeviceFileSystem final : public DeviceFileSystem {
 public:
  std::optional<CharacterDevice> GetCharacterDevice(
      const std::string& path) override;
  std::optional<std::string> CanonicalPath(const std::string& path) override;
  std::optional<std::string> ReadMetadata(const std::string& path) override;
};

enum class Permission { kReadWrite, kReadOnly, kStatOnly };
struct Rule {
  Permission permission;
  std::string path;
  bool operator==(const Rule&) const = default;
};

// Pre-sandbox only. Inspects metadata; never opens a device or performs an
// ioctl. Returns a complete selected-M1 set or no additional permissions. The
// caller must independently enforce the feature, architecture and VA-API build
// gates.
CONTENT_EXPORT std::vector<Rule> DiscoverPermissions(DeviceFileSystem& fs);

}  // namespace content::apple_avd
#endif  // CONTENT_COMMON_APPLE_AVD_GPU_PERMISSIONS_LINUX_H_
