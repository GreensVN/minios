#!/usr/bin/env bash
# =============================================================================
#  build.sh - one-shot build / run helper for MiniOS v4.1
#
#     ./build.sh            build output/minios.img
#     ./build.sh run        build and boot in QEMU (graphical)
#     ./build.sh serial     build and boot in QEMU with the console on stdio
#     ./build.sh test       build and run the binary sanity checks
#     ./build.sh clean      remove build artefacts
#
#  Dependencies: nasm, gcc (multilib for -m32), binutils, make; qemu-system-i386
#  to run.  Install on Debian/Ubuntu:
#     sudo apt install build-essential gcc-multilib nasm qemu-system-x86
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info() { printf "${BLUE}[*]${NC} %s\n" "$*"; }
ok()   { printf "${GREEN}[✓]${NC} %s\n" "$*"; }
warn() { printf "${YELLOW}[!]${NC} %s\n" "$*"; }
die()  { printf "${RED}[✗]${NC} %s\n" "$*" >&2; exit 1; }

need() { command -v "$1" >/dev/null 2>&1 || die "'$1' not found – $2"; }

check_deps() {
    info "Checking toolchain"
    need nasm "install nasm"
    need gcc  "install gcc"
    need ld   "install binutils"
    need make "install make"
    need objcopy "install binutils"
    # 32-bit support?
    if ! printf 'int main(void){return 0;}' | gcc -m32 -x c -c -o /dev/null - 2>/dev/null; then
        die "gcc cannot produce 32-bit objects – install gcc-multilib (Debian/Ubuntu) or a cross i686-elf-gcc and pass CROSS=i686-elf-"
    fi
    ok "nasm $(nasm -v | awk '{print $3}'), $(gcc --version | head -1)"
}

cmd="${1:-build}"
case "$cmd" in
    build)
        check_deps
        make
        ;;
    test)
        check_deps
        make test
        ;;
    run)
        check_deps
        need qemu-system-i386 "install qemu-system-x86"
        make run
        ;;
    serial)
        check_deps
        need qemu-system-i386 "install qemu-system-x86"
        warn "Exit QEMU with Ctrl-A then X"
        make run-serial
        ;;
    iso)
        check_deps
        need grub-mkrescue "install grub-pc-bin and xorriso"
        make iso
        ;;
    clean)
        make clean
        ok "clean"
        ;;
    *)
        sed -n '2,13p' "$0" | sed 's/^# \{0,2\}//'
        exit 1
        ;;
esac
