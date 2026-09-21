// Copyright 2026 The omarchy-m1-video contributors
// SPDX-License-Identifier: BSD-3-Clause
#include "content/common/apple_avd_gpu_broker_linux.h"

#include <fcntl.h>
#include <unistd.h>

#include <cstdlib>
#include <fstream>
#include <functional>
#include <map>
#include <string>

#include "testing/gtest/include/gtest/gtest.h"

namespace content::apple_avd {
namespace {

const std::string kGpu = "/sys/devices/platform/soc/206400000.gpu";
const std::string kAvd = "/sys/devices/platform/soc/269080000.avd";
const std::string kRenderSys = "/sys/dev/char/226:128";
const std::string kVideoSys = "/sys/dev/char/81:0";
const std::string kMediaSys = "/sys/dev/char/243:0";

class FakeFileSystem : public DeviceFileSystem {
 public:
  std::map<std::string, CharacterDevice> nodes;
  std::map<std::string, std::string> canonical;
  std::map<std::string, std::string> metadata;
  std::map<std::string, unsigned> reads;
  std::function<void(const std::string&, unsigned)> on_node_read;

  std::optional<CharacterDevice> GetCharacterDevice(
      const std::string& path) override {
    if (on_node_read) {
      on_node_read(path, ++reads[path]);
    }
    auto it = nodes.find(path);
    return it == nodes.end() ? std::nullopt : std::make_optional(it->second);
  }
  std::optional<std::string> CanonicalPath(const std::string& path) override {
    auto it = canonical.find(path);
    return it == canonical.end() ? std::nullopt
                                 : std::make_optional(it->second);
  }
  std::optional<std::string> ReadMetadata(const std::string& path) override {
    auto it = metadata.find(path);
    return it == metadata.end() ? std::nullopt : std::make_optional(it->second);
  }

  void AddNode(const std::string& path,
               unsigned major,
               unsigned minor,
               const std::string& physical,
               const std::string& suffix) {
    nodes[path] = {major, minor, 1, nodes.size() + 1};
    std::string sys =
        "/sys/dev/char/" + std::to_string(major) + ":" + std::to_string(minor);
    metadata[sys + "/dev"] =
        std::to_string(major) + ":" + std::to_string(minor) + "\n";
    canonical[sys] = physical + suffix;
    if (suffix.starts_with("/drm/") || suffix.starts_with("/video4linux/")) {
      canonical[sys + "/device"] = physical;
    }
  }
  void AddM1(unsigned render = 128,
             unsigned video = 0,
             unsigned media = 0,
             unsigned media_major = 243) {
    AddNode("/dev/dri/renderD" + std::to_string(render), 226, render, kGpu,
            "/drm/renderD" + std::to_string(render));
    AddNode("/dev/video" + std::to_string(video), 81, video, kAvd,
            "/video4linux/video" + std::to_string(video));
    AddNode("/dev/media" + std::to_string(media), media_major, media, kAvd,
            "/media" + std::to_string(media));
    canonical[kGpu + "/driver"] = "/sys/bus/platform/drivers/asahi";
    canonical[kAvd + "/driver"] = "/sys/bus/platform/drivers/avd";
    metadata[kGpu + "/of_node/compatible"] =
        std::string("apple,agx-t8103") + '\0' + "apple,agx-g13g" + '\0';
    metadata[kAvd + "/of_node/compatible"] =
        std::string("apple,t8103-avd") + '\0';
  }
};

using Broker = sandbox::syscall_broker::BrokerFilePermission;

// The broker client handles O_CLOEXEC before these permission predicates.
bool OpenAllowed(const std::vector<Broker>& permissions,
                 const std::string& path,
                 int flags) {
  for (const auto& permission : permissions) {
    if (permission.CheckOpen(path.c_str(), flags).first) {
      return true;
    }
  }
  return false;
}

bool StatAllowed(const std::vector<Broker>& permissions,
                 const std::string& path) {
  for (const auto& permission : permissions) {
    if (permission.CheckStatWithIntermediates(path.c_str())) {
      return true;
    }
  }
  return false;
}

TEST(AppleAvdPermissions, OnlyRequiredOperations) {
  FakeFileSystem fs;
  fs.AddM1();
  const auto rules = DiscoverPermissions(fs);
  ASSERT_EQ(rules.size(), 5u);
  std::vector<Broker> permissions;
  AppendBrokerPermissions(rules, &permissions);
  for (const std::string path :
       {"/dev/dri/renderD128", "/dev/video0", "/dev/media0"}) {
    EXPECT_TRUE(OpenAllowed(permissions, path, O_RDWR | O_NONBLOCK));
    EXPECT_TRUE(StatAllowed(permissions, path));
    bool access = false;
    for (const auto& permission : permissions) {
      access |= permission.CheckAccess(path.c_str(), F_OK) != nullptr;
    }
    EXPECT_TRUE(access);
    EXPECT_FALSE(OpenAllowed(permissions, path, O_RDWR | O_CREAT));
  }
  EXPECT_TRUE(OpenAllowed(permissions, kVideoSys + "/uevent", O_RDONLY));
  EXPECT_FALSE(OpenAllowed(permissions, kVideoSys + "/uevent", O_RDWR));
  EXPECT_FALSE(
      OpenAllowed(permissions, kVideoSys + "/uevent", O_RDONLY | O_TRUNC));
  EXPECT_TRUE(StatAllowed(permissions, kRenderSys + "/device/drm"));
  EXPECT_TRUE(StatAllowed(permissions, kRenderSys + "/device"));
  EXPECT_FALSE(OpenAllowed(permissions, kRenderSys + "/device/drm", O_RDONLY));
  for (const auto& permission : permissions) {
    EXPECT_EQ(
        permission.CheckAccess((kRenderSys + "/device/drm").c_str(), F_OK),
        nullptr);
  }
  for (const std::string path :
       {"/dev/video1", "/dev/media1", "/dev/dri/renderD129", "/dev/dri/card0",
        "/dev/video0/child", "/dev/media00", "/dev/../dev/video0",
        "/dev/./video0", "/dev/video0/", "dev/video0", "/etc/passwd",
        "/sys/dev/char/81:0/uevent/child", "/sys/dev/char/81:1/uevent",
        "/sys/dev/char/226:128/device/drm/child",
        "/sys/dev/char/226:129/device/drm"}) {
    SCOPED_TRACE(path);
    EXPECT_FALSE(OpenAllowed(permissions, path, O_RDONLY));
    EXPECT_FALSE(OpenAllowed(permissions, path, O_RDWR));
    EXPECT_FALSE(StatAllowed(permissions, path));
  }
}

TEST(AppleAvdPermissions, RenumberedDevicesAndDynamicMediaMajor) {
  FakeFileSystem fs;
  fs.AddM1(135, 7, 9, 250);
  auto rules = DiscoverPermissions(fs);
  ASSERT_EQ(rules.size(), 5u);
  std::vector<Broker> permissions;
  AppendBrokerPermissions(rules, &permissions);
  EXPECT_TRUE(OpenAllowed(permissions, "/dev/dri/renderD135", O_RDWR));
  EXPECT_TRUE(OpenAllowed(permissions, "/dev/video7", O_RDWR));
  EXPECT_TRUE(OpenAllowed(permissions, "/dev/media9", O_RDWR));
  EXPECT_TRUE(OpenAllowed(permissions, "/sys/dev/char/81:7/uevent", O_RDONLY));
  EXPECT_TRUE(StatAllowed(permissions, "/sys/dev/char/226:135/device/drm"));
  EXPECT_FALSE(OpenAllowed(permissions, "/dev/video0", O_RDWR));
}

TEST(AppleAvdPermissions, MissingNodesOrMetadataRejectCompleteSet) {
  FakeFileSystem complete;
  complete.AddM1();
  for (const auto& [path, unused] : complete.nodes) {
    SCOPED_TRACE(path);
    auto fs = complete;
    fs.nodes.erase(path);
    EXPECT_TRUE(DiscoverPermissions(fs).empty());
  }
  for (const auto& [path, unused] : complete.metadata) {
    SCOPED_TRACE(path);
    auto fs = complete;
    fs.metadata.erase(path);
    EXPECT_TRUE(DiscoverPermissions(fs).empty());
  }
  for (const auto& [path, unused] : complete.canonical) {
    SCOPED_TRACE(path);
    auto fs = complete;
    fs.canonical.erase(path);
    EXPECT_TRUE(DiscoverPermissions(fs).empty());
  }
}

TEST(AppleAvdPermissions, CameraCannotSubstituteForAvd) {
  FakeFileSystem fs;
  fs.AddM1();
  fs.canonical[kAvd + "/driver"] = "/sys/bus/platform/drivers/uvcvideo";
  EXPECT_TRUE(DiscoverPermissions(fs).empty());
}

TEST(AppleAvdPermissions, UnrelatedCameraDoesNotAcquirePermissions) {
  FakeFileSystem fs;
  fs.AddM1();
  fs.AddNode("/dev/video1", 81, 1, "/sys/devices/platform/camera",
             "/video4linux/video1");
  fs.AddNode("/dev/media1", 243, 1, "/sys/devices/platform/camera", "/media1");
  auto rules = DiscoverPermissions(fs);
  ASSERT_EQ(rules.size(), 5u);
  std::vector<Broker> permissions;
  AppendBrokerPermissions(rules, &permissions);
  EXPECT_FALSE(OpenAllowed(permissions, "/dev/video1", O_RDWR));
  EXPECT_FALSE(OpenAllowed(permissions, "/dev/media1", O_RDWR));
}

TEST(AppleAvdPermissions, MediaMustBelongToSameAvd) {
  FakeFileSystem fs;
  fs.AddM1();
  fs.canonical[kMediaSys] = "/sys/devices/platform/soc/other.avd/media0";
  EXPECT_TRUE(DiscoverPermissions(fs).empty());
}

TEST(AppleAvdPermissions, RejectAmbiguousSets) {
  for (unsigned kind = 0; kind != 3; ++kind) {
    SCOPED_TRACE(kind);
    FakeFileSystem fs;
    fs.AddM1();
    if (kind == 0) {
      fs.AddNode("/dev/dri/renderD129", 226, 129, kGpu, "/drm/renderD129");
    } else if (kind == 1) {
      fs.AddNode("/dev/video1", 81, 1, kAvd, "/video4linux/video1");
    } else {
      fs.AddNode("/dev/media1", 243, 1, kAvd, "/media1");
    }
    EXPECT_TRUE(DiscoverPermissions(fs).empty());
  }
}

TEST(AppleAvdPermissions, WrongCompatibleOrDriverRejects) {
  for (const std::string& physical : {kGpu, kAvd}) {
    for (const std::string& data :
         {std::string(), std::string("apple,t8103-avd"),
          std::string("apple,t8112-avd") + '\0',
          std::string("xapple,t8103-avd") + '\0', std::string(4097, '\0')}) {
      FakeFileSystem fs;
      fs.AddM1();
      fs.metadata[physical + "/of_node/compatible"] = data;
      EXPECT_TRUE(DiscoverPermissions(fs).empty());
    }
    FakeFileSystem fs;
    fs.AddM1();
    fs.canonical[physical + "/driver"] += "-other";
    EXPECT_TRUE(DiscoverPermissions(fs).empty());
  }
}

TEST(AppleAvdPermissions, DeviceNumbersAndCanonicalTopologyMustAgree) {
  for (unsigned variation = 0; variation != 6; ++variation) {
    SCOPED_TRACE(variation);
    FakeFileSystem fs;
    fs.AddM1();
    if (variation == 0)
      fs.metadata[kVideoSys + "/dev"] = "81:1\n";
    if (variation == 1)
      fs.nodes["/dev/video0"].major = 1;
    if (variation == 2)
      fs.nodes["/dev/dri/renderD128"].minor = 129;
    if (variation == 3)
      fs.canonical[kVideoSys] = kAvd + "/video4linux/video1";
    if (variation == 4)
      fs.canonical[kRenderSys] = kGpu + "/drm/renderD129";
    if (variation == 5)
      fs.canonical[kVideoSys + "/device"] = "/tmp/avd";
    EXPECT_TRUE(DiscoverPermissions(fs).empty());
  }
  for (const std::string path :
       {"/tmp/avd", "/sys/devices/platform/../avd",
        "/sys/devices/platform/./avd", "/sys/devices/platform//avd",
        "/sys/devices/platform/avd/.."}) {
    FakeFileSystem fs;
    fs.AddM1();
    fs.canonical[kVideoSys + "/device"] = path;
    fs.canonical[kVideoSys] = path + "/video4linux/video0";
    fs.canonical[kMediaSys] = path + "/media0";
    fs.canonical[path + "/driver"] = fs.canonical[kAvd + "/driver"];
    fs.metadata[path + "/of_node/compatible"] =
        fs.metadata[kAvd + "/of_node/compatible"];
    EXPECT_TRUE(DiscoverPermissions(fs).empty());
  }
}

TEST(AppleAvdPermissions, ChangesBeforePublicationRejectCompleteSet) {
  for (const std::string path :
       {"/dev/dri/renderD128", "/dev/video0", "/dev/media0"}) {
    for (bool remove : {false, true}) {
      FakeFileSystem fs;
      fs.AddM1();
      fs.on_node_read = [&](const std::string& requested, unsigned reads) {
        if (requested == path && reads == 2) {
          if (remove)
            fs.nodes.erase(path);
          else
            ++fs.nodes[path].inode;
        }
      };
      EXPECT_TRUE(DiscoverPermissions(fs).empty());
    }
  }
}

TEST(AppleAvdPermissions, BoundedDiscovery) {
  for (unsigned kind = 0; kind != 3; ++kind) {
    FakeFileSystem fs;
    fs.AddM1(kind == 0 ? 192 : 128, kind == 1 ? 64 : 0, kind == 2 ? 64 : 0);
    EXPECT_TRUE(DiscoverPermissions(fs).empty());
  }
}

TEST(AppleAvdPermissions, NativeAdapterMetadataAndSymlinkLimits) {
  // Ordinary temporary files only. No device opens, mknod, ioctls or root
  // needed.
  std::string pattern =
      std::string(getenv("TMPDIR") ? getenv("TMPDIR") : "/tmp") +
      "/apple-avd-policy-XXXXXX";
  char* created = mkdtemp(pattern.data());
  ASSERT_NE(created, nullptr);
  const std::string dir(created), file = dir + "/metadata",
                                  link = dir + "/link";
  NativeDeviceFileSystem fs;
  {
    std::ofstream stream(file);
    stream << std::string(4096, 'a');
  }
  EXPECT_EQ(fs.ReadMetadata(file), std::string(4096, 'a'));
  EXPECT_FALSE(fs.GetCharacterDevice(file));
  {
    std::ofstream stream(file, std::ios::app);
    stream << 'b';
  }
  EXPECT_FALSE(fs.ReadMetadata(file));
  EXPECT_EQ(symlink(file.c_str(), link.c_str()), 0);
  EXPECT_FALSE(fs.ReadMetadata(link));
  EXPECT_FALSE(fs.GetCharacterDevice(link));
  EXPECT_EQ(fs.CanonicalPath(link), fs.CanonicalPath(file));
  EXPECT_FALSE(fs.ReadMetadata(dir + "/missing"));
  EXPECT_FALSE(fs.CanonicalPath(dir + "/missing"));
  EXPECT_EQ(unlink(link.c_str()), 0);
  EXPECT_EQ(unlink(file.c_str()), 0);
  EXPECT_EQ(rmdir(dir.c_str()), 0);
}

}  // namespace
}  // namespace content::apple_avd
