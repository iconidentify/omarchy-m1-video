// Only the two-argument, case-sensitive overload used by the pinned broker.
#pragma once
#include <string_view>
namespace base {
inline bool StartsWith(std::string_view value, std::string_view prefix) {
  return value.starts_with(prefix);
}
}
