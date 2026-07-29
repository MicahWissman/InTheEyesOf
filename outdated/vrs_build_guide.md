gemini.md: Building Facebook VRS from Source
1. Prerequisites

VRS requires a C++17 compiler and several libraries. Use your package manager to install the system dependencies first.

On Ubuntu/Debian:
Bash

sudo apt-get update
sudo apt-get install -y cmake git ninja-build ccache libgtest-dev libfmt-dev \
libturbojpeg-dev libpng-dev liblz4-dev libzstd-dev libxxhash-dev \
libboost-system-dev libboost-filesystem-dev libboost-thread-dev \
libboost-chrono-dev libboost-date-time-dev

2. Clone the Repository

Clone the official VRS repository into your home directory.
Bash

cd ~
git clone https://github.com/facebookresearch/vrs.git
cd vrs

3. Configure and Build

To ensure the installation stays within your home directory (~/vrs_install), we use the -DCMAKE_INSTALL_PREFIX flag during configuration.
Bash

# Create a build directory
mkdir build && cd build

# Configure with CMake (pointing installation to ~/vrs_install)
cmake -S .. -B . -G Ninja -DCMAKE_INSTALL_PREFIX=$HOME/vrs_install

# Build all targets
ninja all

# Run tests to ensure stability
ctest -j8

4. Install to Home Directory

After a successful build, install the binaries and headers to your local folder.
Bash

ninja install

5. Environment Setup

To use the vrs command-line tool from anywhere, add the new installation path to your .bashrc or .zshrc.
Bash

echo 'export PATH="$HOME/vrs_install/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc

Verifying the Installation

You can verify the build by checking the version of the VRS CLI tool:
Bash

vrs --version

Common Commands for VRS Files
Action	Command
Inspect File	vrs <filename>.vrs
List Records	vrs list <filename>.vrs
Extract JSON	vrs json-description <filename>.vrs
Check Integrity	vrs check <filename>.vrs

    [!TIP]
    If you need Python support for VRS files, you can also install the bridge via pip install vrs, or build pyvrs from the same GitHub organization.