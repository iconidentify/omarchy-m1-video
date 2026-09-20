// Copyright 2026 The omarchy-m1-video contributors
// SPDX-License-Identifier: BSD-3-Clause
#ifndef CONTENT_COMMON_APPLE_AVD_GPU_BROKER_LINUX_H_
#define CONTENT_COMMON_APPLE_AVD_GPU_BROKER_LINUX_H_

#include "content/common/apple_avd_gpu_permissions_linux.h"
#include "sandbox/linux/syscall_broker/broker_file_permission.h"

namespace content::apple_avd {

inline void AppendBrokerPermissions(
    const std::vector<Rule>& rules,
    std::vector<sandbox::syscall_broker::BrokerFilePermission>* permissions) {
  using BrokerPermission = sandbox::syscall_broker::BrokerFilePermission;
  for (const auto& rule : rules) {
    switch (rule.permission) {
      case Permission::kReadWrite:
        permissions->push_back(BrokerPermission::ReadWrite(rule.path));
        break;
      case Permission::kReadOnly:
        permissions->push_back(BrokerPermission::ReadOnly(rule.path));
        break;
      case Permission::kStatOnly:
        permissions->push_back(
            BrokerPermission::StatOnlyWithIntermediateDirs(rule.path));
        break;
    }
  }
}

}  // namespace content::apple_avd
#endif  // CONTENT_COMMON_APPLE_AVD_GPU_BROKER_LINUX_H_
