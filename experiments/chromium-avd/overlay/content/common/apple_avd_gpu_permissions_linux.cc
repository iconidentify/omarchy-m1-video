// Copyright 2026 The omarchy-m1-video contributors
// SPDX-License-Identifier: BSD-3-Clause
#include "content/common/apple_avd_gpu_permissions_linux.h"

#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>

#include <array>
#include <string_view>
#include <utility>

namespace content::apple_avd {
namespace {

constexpr size_t kMaxMetadata = 4096;
constexpr unsigned kMaxNodes = 64;

bool IsCanonicalPlatformPath(const std::string& path) {
  return path.starts_with("/sys/devices/platform/") &&
         path.size() <= kMaxMetadata && path.find('\0') == std::string::npos &&
         path.find("/../") == std::string::npos &&
         path.find("/./") == std::string::npos &&
         path.find("//") == std::string::npos && !path.ends_with("/..") &&
         !path.ends_with("/.") && !path.ends_with('/');
}

bool HasCompatible(const std::string& data, std::string_view wanted) {
  if (data.empty() || data.size() > kMaxMetadata || data.back() != '\0') {
    return false;
  }
  size_t begin = 0;
  while (begin < data.size()) {
    const size_t end = data.find('\0', begin);
    if (std::string_view(data).substr(begin, end - begin) == wanted) {
      return true;
    }
    begin = end + 1;
  }
  return false;
}

struct Node {
  CharacterDevice identity;
  std::string path;
  std::string sysfs;
  std::string canonical;
  std::string physical;
  bool operator==(const Node&) const = default;
};

std::optional<Node> ReadNode(DeviceFileSystem& fs, const std::string& path) {
  auto identity = fs.GetCharacterDevice(path);
  if (!identity) {
    return std::nullopt;
  }
  std::string number =
      std::to_string(identity->major) + ":" + std::to_string(identity->minor);
  std::string sysfs = "/sys/dev/char/" + number;
  auto dev = fs.ReadMetadata(sysfs + "/dev");
  auto canonical = fs.CanonicalPath(sysfs);
  if (!dev || *dev != number + "\n" || !canonical ||
      !IsCanonicalPlatformPath(*canonical)) {
    return std::nullopt;
  }
  return Node{*identity, path, std::move(sysfs), *canonical, {}};
}

std::optional<Node> ReadVideoOrRender(DeviceFileSystem& fs,
                                      unsigned index,
                                      bool render) {
  const std::string name =
      (render ? "renderD" : "video") + std::to_string(index);
  auto node = ReadNode(fs, (render ? "/dev/dri/" : "/dev/") + name);
  if (!node || node->identity.major != (render ? 226u : 81u) ||
      (render && node->identity.minor != index)) {
    return std::nullopt;
  }
  auto physical = fs.CanonicalPath(node->sysfs + "/device");
  if (!physical || !IsCanonicalPlatformPath(*physical) ||
      node->canonical !=
          *physical + (render ? "/drm/" : "/video4linux/") + name) {
    return std::nullopt;
  }
  auto driver = fs.CanonicalPath(*physical + "/driver");
  auto compatible = fs.ReadMetadata(*physical + "/of_node/compatible");
  if (!driver ||
      *driver != (render ? "/sys/bus/platform/drivers/asahi"
                         : "/sys/bus/platform/drivers/avd") ||
      !compatible ||
      !HasCompatible(*compatible,
                     render ? "apple,agx-t8103" : "apple,t8103-avd")) {
    return std::nullopt;
  }
  node->physical = *physical;
  return node;
}

std::optional<Node> ReadMedia(DeviceFileSystem& fs,
                              unsigned index,
                              const Node& video) {
  const std::string name = "media" + std::to_string(index);
  auto node = ReadNode(fs, "/dev/" + name);
  // Media class entries have no device symlink on the measured M1. Require the
  // media node to be a direct child of the already validated AVD device.
  if (!node || node->canonical != video.physical + "/" + name ||
      node->sysfs == video.sysfs) {
    return std::nullopt;
  }
  node->physical = video.physical;
  return node;
}

}  // namespace

std::optional<CharacterDevice> NativeDeviceFileSystem::GetCharacterDevice(
    const std::string& path) {
  struct stat st;
  if (lstat(path.c_str(), &st) != 0 || !S_ISCHR(st.st_mode) || st.st_uid != 0) {
    return std::nullopt;
  }
  return CharacterDevice{static_cast<uint32_t>(major(st.st_rdev)),
                         static_cast<uint32_t>(minor(st.st_rdev)),
                         static_cast<uint64_t>(st.st_dev),
                         static_cast<uint64_t>(st.st_ino)};
}

std::optional<std::string> NativeDeviceFileSystem::CanonicalPath(
    const std::string& path) {
  char* canonical = realpath(path.c_str(), nullptr);
  if (!canonical) {
    return std::nullopt;
  }
  std::string result(canonical);
  free(canonical);
  return result;
}

std::optional<std::string> NativeDeviceFileSystem::ReadMetadata(
    const std::string& path) {
  const int fd = open(path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
  if (fd < 0) {
    return std::nullopt;
  }
  std::string result;
  std::array<char, 512> buffer;
  for (;;) {
    const ssize_t count = read(fd, buffer.data(), buffer.size());
    if (count < 0 && errno == EINTR) {
      continue;
    }
    if (count < 0 || (count > 0 && result.size() + static_cast<size_t>(count) >
                                       kMaxMetadata)) {
      close(fd);
      return std::nullopt;
    }
    if (count == 0) {
      close(fd);
      return result;
    }
    result.append(buffer.data(), static_cast<size_t>(count));
  }
}

std::vector<Rule> DiscoverPermissions(DeviceFileSystem& fs) {
  std::vector<std::pair<unsigned, Node>> render, video, media;
  for (unsigned i = 0; i < kMaxNodes; ++i) {
    if (auto node = ReadVideoOrRender(fs, i + 128, true)) {
      render.emplace_back(i + 128, *node);
    }
    if (auto node = ReadVideoOrRender(fs, i, false)) {
      video.emplace_back(i, *node);
    }
  }
  if (render.size() != 1 || video.size() != 1) {
    return {};
  }
  for (unsigned i = 0; i < kMaxNodes; ++i) {
    if (auto node = ReadMedia(fs, i, video.front().second)) {
      media.emplace_back(i, *node);
    }
  }
  if (media.size() != 1 ||
      media.front().second.sysfs == render.front().second.sysfs) {
    return {};
  }
  const Node& r = render.front().second;
  const Node& v = video.front().second;
  const Node& m = media.front().second;
  // Fail closed if the selected observations change while constructing policy.
  // This is a startup snapshot, not a hotplug-aware broker or retained device
  // FD.
  if (ReadVideoOrRender(fs, render.front().first, true) != r ||
      ReadVideoOrRender(fs, video.front().first, false) != v ||
      ReadMedia(fs, media.front().first, v) != m) {
    return {};
  }
  return {{Permission::kReadWrite, r.path},
          {Permission::kStatOnly, r.sysfs + "/device/drm"},
          {Permission::kReadWrite, v.path},
          {Permission::kReadOnly, v.sysfs + "/uevent"},
          {Permission::kReadWrite, m.path}};
}

}  // namespace content::apple_avd
