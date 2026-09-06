// =============================================================================
//  driver_manager.cpp - device driver framework for MiniOS (freestanding C++)
//
//  Build: g++ -m32 -c driver_manager.cpp -ffreestanding -fno-exceptions -fno-rtti
//         -fno-pie -O2   (see Makefile)
//
//  No C++ runtime is available: no exceptions, no RTTI, no global constructors
//  with side effects, no libstdc++.  Objects are created with placement-new in
//  static storage.  The kernel uses the C API from driver_manager.h.
// =============================================================================

#include "driver_manager.h"
#include <stdint.h>
#include <stddef.h>

// ------------------------------------------------------------- placement new
inline void *operator new(size_t, void *p) noexcept { return p; }

// ------------------------------------------------------------------ Port I/O
namespace PortIO {
    static inline void outb(uint16_t port, uint8_t v)  { asm volatile("outb %0, %1" : : "a"(v), "Nd"(port)); }
    static inline uint8_t inb(uint16_t port)           { uint8_t r; asm volatile("inb %1, %0" : "=a"(r) : "Nd"(port)); return r; }
    static inline void outw(uint16_t port, uint16_t v) { asm volatile("outw %0, %1" : : "a"(v), "Nd"(port)); }
    static inline uint16_t inw(uint16_t port)          { uint16_t r; asm volatile("inw %1, %0" : "=a"(r) : "Nd"(port)); return r; }
    static inline void io_wait()                       { outb(0x80, 0); }
}

// -------------------------------------------------------------- Base class
class Driver {
protected:
    const char *name;
    bool initialized;
    uint32_t id;
    uint32_t irq;

public:
    Driver(const char *n, uint32_t driver_id, uint32_t interrupt)
        : name(n), initialized(false), id(driver_id), irq(interrupt) {}
    virtual ~Driver() {}

    virtual bool init() = 0;
    virtual void shutdown() { initialized = false; }
    virtual void handleInterrupt() {}

    const char *getName() const { return name; }
    bool isInitialized() const { return initialized; }
    uint32_t getId() const { return id; }
    uint32_t getIRQ() const { return irq; }
};

// ------------------------------------------------------------ PS/2 keyboard
class KeyboardDriver : public Driver {
    static const int BUFFER_SIZE = 256;
    char buffer[BUFFER_SIZE];
    volatile int readPos, writePos;
    bool shift, ctrl, alt, caps, extended;

    static const char scancodeToAscii[128];
    static const char scancodeToAsciiShift[128];

    void push(char c) {
        int next = (writePos + 1) % BUFFER_SIZE;
        if (next == readPos) return;            // full: drop
        buffer[writePos] = c;
        writePos = next;
    }

public:
    KeyboardDriver() : Driver("PS/2 Keyboard", DRIVER_KEYBOARD, 1),
                       readPos(0), writePos(0), shift(false), ctrl(false),
                       alt(false), caps(false), extended(false) {}

    bool init() override {
        while (PortIO::inb(0x64) & 1) PortIO::inb(0x60);   // drain output buffer
        initialized = true;
        return true;
    }

    void shutdown() override { initialized = false; }

    void handleInterrupt() override {
        uint8_t sc = PortIO::inb(0x60);
        if (sc == 0xE0) { extended = true; return; }
        if (extended) { extended = false; return; }
        bool release = sc & 0x80;
        sc &= 0x7F;
        switch (sc) {
        case 0x2A: case 0x36: shift = !release; return;
        case 0x1D: ctrl = !release; return;
        case 0x38: alt = !release; return;
        case 0x3A: if (!release) caps = !caps; return;
        }
        if (release) return;
        char c = shift ? scancodeToAsciiShift[sc] : scancodeToAscii[sc];
        if (!c) return;
        if (caps && ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z'))) c ^= 0x20;
        if (ctrl && c >= 'a' && c <= 'z') c = static_cast<char>(c - 'a' + 1);
        push(c);
    }

    bool hasKey() const { return readPos != writePos; }
    char getKey() {
        if (readPos == writePos) return 0;
        char c = buffer[readPos];
        readPos = (readPos + 1) % BUFFER_SIZE;
        return c;
    }
};

const char KeyboardDriver::scancodeToAscii[128] = {
    0, 27, '1','2','3','4','5','6','7','8','9','0','-','=','\b','\t',
    'q','w','e','r','t','y','u','i','o','p','[',']','\n', 0,
    'a','s','d','f','g','h','j','k','l',';','\'','`', 0,'\\',
    'z','x','c','v','b','n','m',',','.','/', 0,'*', 0,' ', 0,
};
const char KeyboardDriver::scancodeToAsciiShift[128] = {
    0, 27, '!','@','#','$','%','^','&','*','(',')','_','+','\b','\t',
    'Q','W','E','R','T','Y','U','I','O','P','{','}','\n', 0,
    'A','S','D','F','G','H','J','K','L',':','"','~', 0,'|',
    'Z','X','C','V','B','N','M','<','>','?', 0,'*', 0,' ', 0,
};

// -------------------------------------------------------------- ATA PIO disk
class ATADriver : public Driver {
    static const uint16_t IO   = 0x1F0;
    static const uint16_t CTRL = 0x3F6;

    uint32_t sectorCount;
    char model[41];

    void delay400ns() { for (int i = 0; i < 4; i++) PortIO::inb(CTRL); }

    bool waitNotBusy() {
        for (int i = 0; i < 1000000; i++)
            if (!(PortIO::inb(IO + 7) & 0x80)) return true;
        return false;
    }
    bool waitDRQ() {
        for (int i = 0; i < 1000000; i++) {
            uint8_t s = PortIO::inb(IO + 7);
            if (s & 0x01) return false;             // ERR
            if (s & 0x08) return true;              // DRQ
        }
        return false;
    }
    void setupLBA(uint32_t lba, uint8_t cmd) {
        PortIO::outb(IO + 6, static_cast<uint8_t>(0xE0 | ((lba >> 24) & 0x0F)));
        PortIO::outb(IO + 2, 1);
        PortIO::outb(IO + 3, static_cast<uint8_t>(lba));
        PortIO::outb(IO + 4, static_cast<uint8_t>(lba >> 8));
        PortIO::outb(IO + 5, static_cast<uint8_t>(lba >> 16));
        PortIO::outb(IO + 7, cmd);
    }

public:
    ATADriver() : Driver("ATA/IDE Disk", DRIVER_ATA, 14), sectorCount(0) {
        for (int i = 0; i < 41; i++) model[i] = 0;
    }

    bool init() override {
        PortIO::outb(IO + 6, 0xA0);                  // master
        delay400ns();
        PortIO::outb(CTRL, 0x02);                    // nIEN: no IRQs (polling)
        PortIO::outb(IO + 2, 0); PortIO::outb(IO + 3, 0);
        PortIO::outb(IO + 4, 0); PortIO::outb(IO + 5, 0);
        PortIO::outb(IO + 7, 0xEC);                  // IDENTIFY
        delay400ns();
        if (PortIO::inb(IO + 7) == 0) return false;  // no drive
        if (!waitNotBusy()) return false;
        if (PortIO::inb(IO + 4) || PortIO::inb(IO + 5)) return false;  // not ATA (ATAPI/SATA)
        if (!waitDRQ()) return false;

        uint16_t id[256];
        for (int i = 0; i < 256; i++) id[i] = PortIO::inw(IO);

        for (int i = 0; i < 20; i++) {              // model string is byte-swapped
            model[i * 2]     = static_cast<char>(id[27 + i] >> 8);
            model[i * 2 + 1] = static_cast<char>(id[27 + i] & 0xFF);
        }
        model[40] = 0;
        for (int i = 39; i >= 0 && model[i] == ' '; i--) model[i] = 0;
        sectorCount = (static_cast<uint32_t>(id[61]) << 16) | id[60];
        initialized = true;
        return true;
    }

    bool readSector(uint32_t lba, uint8_t *buf) {
        if (!initialized || lba >= sectorCount || !waitNotBusy()) return false;
        setupLBA(lba, 0x20);
        if (!waitNotBusy() || !waitDRQ()) return false;
        uint16_t *w = reinterpret_cast<uint16_t *>(buf);
        for (int i = 0; i < 256; i++) w[i] = PortIO::inw(IO);
        delay400ns();
        return true;
    }

    bool writeSector(uint32_t lba, const uint8_t *buf) {
        if (!initialized || lba >= sectorCount || !waitNotBusy()) return false;
        setupLBA(lba, 0x30);
        if (!waitNotBusy() || !waitDRQ()) return false;
        const uint16_t *w = reinterpret_cast<const uint16_t *>(buf);
        for (int i = 0; i < 256; i++) { PortIO::outw(IO, w[i]); asm volatile("jmp 1f\n1:"); }
        PortIO::outb(IO + 7, 0xE7);                  // flush cache
        return waitNotBusy();
    }

    uint32_t getSectorCount() const { return sectorCount; }
    const char *getModel() const { return model; }
};

// ---------------------------------------------------------------- PIT timer
class TimerDriver : public Driver {
    volatile uint32_t ticks;
    uint32_t frequency;

public:
    TimerDriver() : Driver("PIT Timer", DRIVER_TIMER, 0), ticks(0), frequency(100) {}

    bool init() override { return init(frequency); }
    bool init(uint32_t hz) {
        if (hz < 19) hz = 19;                        // divisor must fit 16 bits
        if (hz > 1193182) hz = 1193182;
        frequency = hz;
        uint32_t divisor = 1193182 / hz;
        PortIO::outb(0x43, 0x36);
        PortIO::outb(0x40, static_cast<uint8_t>(divisor));
        PortIO::outb(0x40, static_cast<uint8_t>(divisor >> 8));
        ticks = 0;
        initialized = true;
        return true;
    }
    void handleInterrupt() override { ticks++; }
    uint32_t getTicks() const { return ticks; }
    uint32_t getFrequency() const { return frequency; }
};

// ------------------------------------------------------------------- CMOS RTC
class RTCDriver : public Driver {
    static uint8_t readReg(uint8_t r) { PortIO::outb(0x70, static_cast<uint8_t>(0x80 | r)); return PortIO::inb(0x71); }
    static uint8_t bcd(uint8_t v, bool isBcd) { return isBcd ? static_cast<uint8_t>((v >> 4) * 10 + (v & 0x0F)) : v; }

    void readRaw(rtc_datetime_t &d) {
        while (readReg(0x0A) & 0x80) ;               // update in progress
        d.second = readReg(0x00); d.minute = readReg(0x02); d.hour = readReg(0x04);
        d.day = readReg(0x07); d.month = readReg(0x08); d.year = readReg(0x09);
    }

public:
    RTCDriver() : Driver("CMOS RTC", DRIVER_RTC, 8) {}

    bool init() override { initialized = true; return true; }   // polled: no IRQ 8 needed

    bool read(rtc_datetime_t *out) {
        if (!initialized || !out) return false;
        rtc_datetime_t a, b;
        do { readRaw(a); readRaw(b); }               // read twice until stable
        while (a.second != b.second || a.minute != b.minute || a.hour != b.hour || a.day != b.day);
        uint8_t regB = readReg(0x0B);
        bool isBcd = !(regB & 0x04);
        bool h24   = regB & 0x02;
        uint8_t hour = a.hour;
        bool pm = hour & 0x80;
        hour &= 0x7F;
        out->second = bcd(a.second, isBcd);
        out->minute = bcd(a.minute, isBcd);
        out->hour   = bcd(hour, isBcd);
        if (!h24) { if (out->hour == 12) out->hour = 0; if (pm) out->hour = static_cast<uint8_t>(out->hour + 12); }
        out->day    = bcd(a.day, isBcd);
        out->month  = bcd(a.month, isBcd);
        out->year   = static_cast<uint16_t>(2000 + bcd(static_cast<uint8_t>(a.year), isBcd));
        return true;
    }
};

// ------------------------------------------------------------ Driver manager
class DriverManager {
    static const int MAX_DRIVERS = 8;
    Driver *drivers[MAX_DRIVERS];
    int count;

public:
    DriverManager() : count(0) { for (auto &d : drivers) d = nullptr; }

    bool add(Driver *d) {
        if (count >= MAX_DRIVERS || !d) return false;
        if (!d->init()) return false;
        drivers[count++] = d;
        return true;
    }
    Driver *byId(uint32_t id) const {
        for (int i = 0; i < count; i++) if (drivers[i]->getId() == id) return drivers[i];
        return nullptr;
    }
    Driver *byIRQ(uint32_t irq) const {
        for (int i = 0; i < count; i++) if (drivers[i]->getIRQ() == irq) return drivers[i];
        return nullptr;
    }
    Driver *at(int i) const { return (i >= 0 && i < count) ? drivers[i] : nullptr; }
    int size() const { return count; }
};

// static storage for the singletons (no heap, no global ctors)
namespace {
    alignas(DriverManager) unsigned char mgr_mem[sizeof(DriverManager)];
    alignas(KeyboardDriver) unsigned char kbd_mem[sizeof(KeyboardDriver)];
    alignas(ATADriver)      unsigned char ata_mem[sizeof(ATADriver)];
    alignas(TimerDriver)    unsigned char tmr_mem[sizeof(TimerDriver)];
    alignas(RTCDriver)      unsigned char rtc_mem[sizeof(RTCDriver)];
    DriverManager *mgr = nullptr;
    KeyboardDriver *kbd = nullptr;
    ATADriver *ata = nullptr;
    TimerDriver *tmr = nullptr;
    RTCDriver *rtc = nullptr;

    DriverManager &manager() {
        if (!mgr) mgr = new (mgr_mem) DriverManager();
        return *mgr;
    }
}

// ------------------------------------------------------------------ C API
extern "C" {

bool driver_manager_init_keyboard(void) {
    if (!kbd) kbd = new (kbd_mem) KeyboardDriver();
    return manager().add(kbd);
}
bool driver_manager_init_disk(void) {
    if (!ata) ata = new (ata_mem) ATADriver();
    return manager().add(ata);
}
bool driver_manager_init_timer(uint32_t hz) {
    if (!tmr) tmr = new (tmr_mem) TimerDriver();
    if (!tmr->init(hz)) return false;
    return manager().add(tmr);
}
bool driver_manager_init_rtc(void) {
    if (!rtc) rtc = new (rtc_mem) RTCDriver();
    return manager().add(rtc);
}
void driver_manager_handle_irq(uint32_t irq) {
    if (Driver *d = manager().byIRQ(irq)) d->handleInterrupt();
}
int driver_manager_count(void) { return manager().size(); }
const char *driver_manager_name(int i) { Driver *d = manager().at(i); return d ? d->getName() : nullptr; }
bool driver_manager_present(uint32_t id) { Driver *d = manager().byId(id); return d && d->isInitialized(); }

bool driver_keyboard_has_key(void) { return kbd && kbd->hasKey(); }
char driver_keyboard_get_key(void) { return kbd ? kbd->getKey() : 0; }

uint32_t driver_disk_sector_count(void) { return ata ? ata->getSectorCount() : 0; }
const char *driver_disk_model(void) { return ata ? ata->getModel() : ""; }
bool driver_disk_read(uint32_t lba, uint8_t *buf) { return ata && ata->readSector(lba, buf); }
bool driver_disk_write(uint32_t lba, const uint8_t *buf) { return ata && ata->writeSector(lba, buf); }

uint32_t driver_timer_ticks(void) { return tmr ? tmr->getTicks() : 0; }
uint32_t driver_timer_frequency(void) { return tmr ? tmr->getFrequency() : 0; }

bool driver_rtc_read(rtc_datetime_t *out) { return rtc && rtc->read(out); }

// Required by the compiler for pure virtuals; never called.
void __cxa_pure_virtual(void) { for (;;) asm volatile("cli; hlt"); }

}  // extern "C"

// Virtual destructors reference these; nothing is ever heap-allocated.
void operator delete(void *) noexcept {}
void operator delete(void *, size_t) noexcept {}
