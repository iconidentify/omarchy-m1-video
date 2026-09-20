// Isolated-test support only; never copied into Chromium.
#pragma once
#include <cstdlib>
#include <iostream>
struct IsolatedCheck {
  bool passed;
  template <typename T> IsolatedCheck& operator<<(const T& value) {
    if (!passed) std::cerr << value;
    return *this;
  }
  ~IsolatedCheck() { if (!passed) std::abort(); }
};
#define CHECK(condition) IsolatedCheck{static_cast<bool>(condition)}
