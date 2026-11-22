# CMakeLists.txt - builds libkestrel, the Kestrel modem library (C++17, C interface).
#
# Copyright 2026 P. H. Ewen (KO4WSC). Licensed under the Apache License 2.0.
#
# Build (any platform):
#   cmake -S cpp -B cpp/build -DCMAKE_BUILD_TYPE=Release
#   cmake --build cpp/build
# or simply: python tools/build_native.py  (which also copies the result to modem/_native/)

cmake_minimum_required(VERSION 3.16)  # an old enough CMake for every platform Kestrel aims at
project(kestrel VERSION 0.31 LANGUAGES CXX)  # the library, versioned with the program

set(CMAKE_CXX_STANDARD 17)  # C++17
set(CMAKE_CXX_STANDARD_REQUIRED ON)  # and nothing older
set(CMAKE_CXX_EXTENSIONS OFF)  # plain standard C++, no compiler extensions
if(NOT CMAKE_BUILD_TYPE)  # no build type chosen
  set(CMAKE_BUILD_TYPE Release)  # build optimized
endif()  # end of the default

add_library(kestrel SHARED src/kestrel.cpp)  # the library itself (kestrel.dll on Windows, libkestrel.so on Linux)
target_include_directories(kestrel PRIVATE include third_party/pocketfft)  # its own header, and the FFT
find_package(Threads REQUIRED)  # the platform's thread library (the heavy loops share work among threads)
target_link_libraries(kestrel PRIVATE Threads::Threads)  # linked in
set_target_properties(kestrel PROPERTIES CXX_VISIBILITY_PRESET hidden PREFIX "")  # export only the kes_ functions; name the file "kestrel..." on every platform
if(NOT MSVC)  # GCC and Clang (MinGW on Windows, g++ on Linux and the Raspberry Pi)
  target_compile_options(kestrel PRIVATE -O3 -fno-fast-math -ffp-contract=off)  # fast, but with exact IEEE arithmetic so results match the Python reference (no fused multiply-add)
endif()  # end of GCC and Clang
if(MINGW)  # MinGW on Windows
  target_link_options(kestrel PRIVATE -static -static-libgcc -static-libstdc++ -s)  # carry the C++ runtime inside the DLL, so it needs no other DLL; strip the symbols (smaller, and no build details inside)
endif()  # end of MinGW
if(MSVC)  # Microsoft's compiler
  target_compile_options(kestrel PRIVATE /O2 /fp:precise)  # optimized, exact arithmetic
endif()  # end of MSVC
