// driver_manager.cpp - Enhanced Driver System cho MiniOS v2.0
// Biên dịch: g++ -m32 -c driver_manager.cpp -o driver_manager.o -ffreestanding -fno-exceptions -fno-rtti -fno-pie -O2

#include <stdint.h>
#include <stddef.h>

// ========== Base Classes ==========
class Driver {
protected:
    const char* name;
    bool initialized;
    uint32_t id;
    uint32_t irq;
    
public:
    Driver(const char* n, uint32_t driver_id, uint32_t interrupt = 0) 
        : name(n), initialized(false), id(driver_id), irq(interrupt) {}
    
    virtual ~Driver() {}
    
    virtual bool init() = 0;
    virtual void shutdown() = 0;
    virtual void handleInterrupt() {}
    
    const char* getName() const { return name; }
    bool isInitialized() const { return initialized; }
    uint32_t getId() const { return id; }
    uint32_t getIRQ() const { return irq; }
};

// ========== Port I/O ==========
class PortIO {
public:
    static inline void outb(uint16_t port, uint8_t val) {
        asm volatile("outb %0, %1" : : "a"(val), "Nd"(port));
    }
    
    static inline uint8_t inb(uint16_t port) {
        uint8_t ret;
        asm volatile("inb %1, %0" : "=a"(ret) : "Nd"(port));
        return ret;
    }
    
    static inline void outw(uint16_t port, uint16_t val) {
        asm volatile("outw %0, %1" : : "a"(val), "Nd"(port));
    }
    
    static inline uint16_t inw(uint16_t port) {
        uint16_t ret;
        asm volatile("inw %1, %0" : "=a"(ret) : "Nd"(port));
        return ret;
    }
    
    static inline void outl(uint16_t port, uint32_t val) {
        asm volatile("outl %0, %1" : : "a"(val), "Nd"(port));
    }
    
    static inline uint32_t inl(uint16_t port) {
        uint32_t ret;
        asm volatile("inl %1, %0" : "=a"(ret) : "Nd"(port));
        return ret;
    }
    
    static inline void io_wait() {
        outb(0x80, 0);
    }
};

// ========== Keyboard Driver ==========
class KeyboardDriver : public Driver {
private:
    static const int BUFFER_SIZE = 256;
    uint8_t buffer[BUFFER_SIZE];
    volatile int readPos;
    volatile int writePos;
    bool shiftPressed;
    bool ctrlPressed;
    bool altPressed;
    bool capsLock;
    
    static const char scancodeToAscii[128];
    static const char scancodeToAsciiShift[128];
    
public:
    KeyboardDriver() : Driver("PS/2 Keyboard", 1, 1), 
                       readPos(0), writePos(0),
                       shiftPressed(false), ctrlPressed(false),
                       altPressed(false), capsLock(false) {}
    
    bool init() override {
        // Enable keyboard
        PortIO::outb(0x64, 0xAE);
        PortIO::io_wait();
        
        // Enable scanning
        PortIO::outb(0x60, 0xF4);
        PortIO::io_wait();
        
        // Wait for ACK
        while ((PortIO::inb(0x64) & 1) == 0);
        uint8_t result = PortIO::inb(0x60);
        
        initialized = (result == 0xFA);
        return initialized;
    }
    
    void shutdown() override {
        PortIO::outb(0x64, 0xAD);
        initialized = false;
    }
    
    void handleInterrupt() override {
        uint8_t scancode = PortIO::inb(0x60);
        
        // Handle special keys
        if (scancode == 0x2A || scancode == 0x36) {
            shiftPressed = true;
            return;
        }
        if (scancode == 0xAA || scancode == 0xB6) {
            shiftPressed = false;
            return;
        }
        if (scancode == 0x1D) {
            ctrlPressed = true;
            return;
        }
        if (scancode == 0x9D) {
            ctrlPressed = false;
            return;
        }
        if (scancode == 0x38) {
            altPressed = true;
            return;
        }
        if (scancode == 0xB8) {
            altPressed = false;
            return;
        }
        if (scancode == 0x3A) {
            capsLock = !capsLock;
            setLEDs();
            return;
        }
        
        // Convert to ASCII
        if (scancode < 128) {
            char c = shiftPressed ? scancodeToAsciiShift[scancode] : scancodeToAscii[scancode];
            
            if (capsLock && c >= 'a' && c <= 'z') {
                c -= 32;
            }
            
            if (c != 0) {
                buffer[writePos] = c;
                writePos = (writePos + 1) % BUFFER_SIZE;
            }
        }
    }
    
    bool hasKey() const {
        return readPos != writePos;
    }
    
    char getKey() {
        if (readPos == writePos)
            return 0;
        
        char c = buffer[readPos];
        readPos = (readPos + 1) % BUFFER_SIZE;
        return c;
    }
    
    void setLEDs() {
        uint8_t leds = 0;
        if (capsLock) leds |= 0x04;
        
        PortIO::outb(0x60, 0xED);
        PortIO::io_wait();
        PortIO::outb(0x60, leds);
        PortIO::io_wait();
    }
    
    bool isShiftPressed() const { return shiftPressed; }
    bool isCtrlPressed() const { return ctrlPressed; }
    bool isAltPressed() const { return altPressed; }
};

// Scancode tables
const char KeyboardDriver::scancodeToAscii[128] = {
    0, 0, '1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '-', '=', '\b',
    '\t', 'q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p', '[', ']', '\n',
    0, 'a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', ';', '\'', '`',
    0, '\\', 'z', 'x', 'c', 'v', 'b', 'n', 'm', ',', '.', '/', 0, '*',
    0, ' '
};

const char KeyboardDriver::scancodeToAsciiShift[128] = {
    0, 0, '!', '@', '#', '$', '%', '^', '&', '*', '(', ')', '_', '+', '\b',
    '\t', 'Q', 'W', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P', '{', '}', '\n',
    0, 'A', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L', ':', '"', '~',
    0, '|', 'Z', 'X', 'C', 'V', 'B', 'N', 'M', '<', '>', '?', 0, '*',
    0, ' '
};

// ========== ATA/IDE Disk Driver ==========
class ATADriver : public Driver {
private:
    static const uint16_t ATA_PRIMARY_IO = 0x1F0;
    static const uint16_t ATA_PRIMARY_CONTROL = 0x3F6;
    
    uint32_t sectorCount;
    char model[41];
    
    void wait400ns() {
        for (int i = 0; i < 4; i++)
            PortIO::inb(ATA_PRIMARY_CONTROL);
    }
    
    bool waitBusy() {
        for (int i = 0; i < 100000; i++) {
            uint8_t status = PortIO::inb(ATA_PRIMARY_IO + 7);
            if ((status & 0x80) == 0)
                return true;
        }
        return false;
    }
    
    bool waitDRQ() {
        for (int i = 0; i < 100000; i++) {
            uint8_t status = PortIO::inb(ATA_PRIMARY_IO + 7);
            if (status & 0x08)
                return true;
        }
        return false;
    }
    
public:
    ATADriver() : Driver("ATA/IDE Disk", 2, 14), sectorCount(0) {
        for (int i = 0; i < 41; i++)
            model[i] = 0;
    }
    
    bool init() override {
        // Select master drive
        PortIO::outb(ATA_PRIMARY_IO + 6, 0xA0);
        wait400ns();
        
        // Disable interrupts
        PortIO::outb(ATA_PRIMARY_CONTROL, 0x02);
        
        // Send IDENTIFY command
        PortIO::outb(ATA_PRIMARY_IO + 7, 0xEC);
        wait400ns();
        
        // Check if drive exists
        uint8_t status = PortIO::inb(ATA_PRIMARY_IO + 7);
        if (status == 0) {
            return false;
        }
        
        if (!waitBusy() || !waitDRQ()) {
            return false;
        }
        
        // Read identification data
        uint16_t identify[256];
        for (int i = 0; i < 256; i++) {
            identify[i] = PortIO::inw(ATA_PRIMARY_IO);
        }
        
        // Extract model name
        for (int i = 0; i < 20; i++) {
            model[i * 2] = identify[27 + i] >> 8;
            model[i * 2 + 1] = identify[27 + i] & 0xFF;
        }
        model[40] = 0;
        
        // Get sector count
        sectorCount = (identify[61] << 16) | identify[60];
        
        initialized = true;
        return true;
    }
    
    void shutdown() override {
        initialized = false;
    }
    
    bool readSector(uint32_t lba, uint8_t* buffer) {
        if (!initialized || lba >= sectorCount)
            return false;
        
        // Wait for drive to be ready
        if (!waitBusy())
            return false;
        
        // Select drive and send LBA
        PortIO::outb(ATA_PRIMARY_IO + 6, 0xE0 | ((lba >> 24) & 0x0F));
        PortIO::outb(ATA_PRIMARY_IO + 2, 1);  // Sector count
        PortIO::outb(ATA_PRIMARY_IO + 3, lba & 0xFF);
        PortIO::outb(ATA_PRIMARY_IO + 4, (lba >> 8) & 0xFF);
        PortIO::outb(ATA_PRIMARY_IO + 5, (lba >> 16) & 0xFF);
        PortIO::outb(ATA_PRIMARY_IO + 7, 0x20);  // READ SECTORS
        
        if (!waitBusy() || !waitDRQ())
            return false;
        
        // Read 512 bytes (256 words)
        uint16_t* buf16 = (uint16_t*)buffer;
        for (int i = 0; i < 256; i++) {
            buf16[i] = PortIO::inw(ATA_PRIMARY_IO);
        }
        
        return true;
    }
    
    bool writeSector(uint32_t lba, const uint8_t* buffer) {
        if (!initialized || lba >= sectorCount)
            return false;
        
        if (!waitBusy())
            return false;
        
        PortIO::outb(ATA_PRIMARY_IO + 6, 0xE0 | ((lba >> 24) & 0x0F));
        PortIO::outb(ATA_PRIMARY_IO + 2, 1);
        PortIO::outb(ATA_PRIMARY_IO + 3, lba & 0xFF);
        PortIO::outb(ATA_PRIMARY_IO + 4, (lba >> 8) & 0xFF);
        PortIO::outb(ATA_PRIMARY_IO + 5, (lba >> 16) & 0xFF);
        PortIO::outb(ATA_PRIMARY_IO + 7, 0x30);  // WRITE SECTORS
        
        if (!waitBusy() || !waitDRQ())
            return false;
        
        const uint16_t* buf16 = (const uint16_t*)buffer;
        for (int i = 0; i < 256; i++) {
            PortIO::outw(ATA_PRIMARY_IO, buf16[i]);
        }
        
        // Flush cache
        PortIO::outb(ATA_PRIMARY_IO + 7, 0xE7);
        waitBusy();
        
        return true;
    }
    
    uint32_t getSectorCount() const { return sectorCount; }
    const char* getModel() const { return model; }
};

// ========== Timer Driver ==========
class TimerDriver : public Driver {
private:
    volatile uint32_t ticks;
    uint32_t frequency;
    
public:
    TimerDriver() : Driver("PIT Timer", 3, 0), ticks(0), frequency(100) {}
    
    bool init() override {
        return init(frequency);
    }
    
    bool init(uint32_t freq) {
        frequency = freq;
        uint32_t divisor = 1193180 / frequency;
        
        PortIO::outb(0x43, 0x36);
        PortIO::outb(0x40, divisor & 0xFF);
        PortIO::outb(0x40, (divisor >> 8) & 0xFF);
        
        ticks = 0;
        initialized = true;
        return true;
    }
    
    void shutdown() override {
        initialized = false;
    }
    
    void handleInterrupt() override {
        ticks++;
    }
    
    uint32_t getTicks() const { return ticks; }
    uint32_t getFrequency() const { return frequency; }
    
    void sleep(uint32_t ms) {
        uint32_t target = ticks + (ms * frequency / 1000);
        while (ticks < target) {
            asm volatile("hlt");
        }
    }
};

// ========== RTC Driver ==========
class RTCDriver : public Driver {
private:
    struct DateTime {
        uint8_t second;
        uint8_t minute;
        uint8_t hour;
        uint8_t day;
        uint8_t month;
        uint16_t year;
    };
    
    uint8_t readRegister(uint8_t reg) {
        PortIO::outb(0x70, reg);
        return PortIO::inb(0x71);
    }
    
    void writeRegister(uint8_t reg, uint8_t value) {
        PortIO::outb(0x70, reg);
        PortIO::outb(0x71, value);
    }
    
    uint8_t bcdToBinary(uint8_t bcd) {
        return ((bcd >> 4) * 10) + (bcd & 0x0F);
    }
    
public:
    RTCDriver() : Driver("RTC", 4, 8) {}
    
    bool init() override {
        // Disable NMI and select status register B
        uint8_t prev = readRegister(0x0B);
        
        // Enable RTC interrupts
        writeRegister(0x0B, prev | 0x40);
        
        // Read register C to enable interrupts
        readRegister(0x0C);
        
        initialized = true;
        return true;
    }
    
    void shutdown() override {
        uint8_t prev = readRegister(0x0B);
        writeRegister(0x0B, prev & ~0x40);
        initialized = false;
    }
    
    void handleInterrupt() override {
        readRegister(0x0C);
    }
    
    DateTime getDateTime() {
        DateTime dt;
        
        // Wait for update to complete
        while (readRegister(0x0A) & 0x80);
        
        dt.second = bcdToBinary(readRegister(0x00));
        dt.minute = bcdToBinary(readRegister(0x02));
        dt.hour = bcdToBinary(readRegister(0x04));
        dt.day = bcdToBinary(readRegister(0x07));
        dt.month = bcdToBinary(readRegister(0x08));
        dt.year = bcdToBinary(readRegister(0x09)) + 2000;
        
        return dt;
    }
};

// ========== Driver Manager ==========
class DriverManager {
private:
    static const int MAX_DRIVERS = 32;
    Driver* drivers[MAX_DRIVERS];
    int driverCount;
    
    static DriverManager* instance;
    
    DriverManager() : driverCount(0) {
        for (int i = 0; i < MAX_DRIVERS; i++)
            drivers[i] = nullptr;
    }
    
public:
    static DriverManager* getInstance() {
        if (!instance)
            instance = new DriverManager();
        return instance;
    }
    
    bool registerDriver(Driver* driver) {
        if (driverCount >= MAX_DRIVERS)
            return false;
        
        if (driver->init()) {
            drivers[driverCount++] = driver;
            return true;
        }
        
        return false;
    }
    
    void unregisterDriver(uint32_t id) {
        for (int i = 0; i < driverCount; i++) {
            if (drivers[i] && drivers[i]->getId() == id) {
                drivers[i]->shutdown();
                
                // Shift remaining drivers
                for (int j = i; j < driverCount - 1; j++) {
                    drivers[j] = drivers[j + 1];
                }
                
                drivers[--driverCount] = nullptr;
                break;
            }
        }
    }
    
    Driver* getDriver(uint32_t id) {
        for (int i = 0; i < driverCount; i++) {
            if (drivers[i] && drivers[i]->getId() == id)
                return drivers[i];
        }
        return nullptr;
    }
    
    Driver* getDriverByIRQ(uint32_t irq) {
        for (int i = 0; i < driverCount; i++) {
            if (drivers[i] && drivers[i]->getIRQ() == irq)
                return drivers[i];
        }
        return nullptr;
    }
    
    int getDriverCount() const { return driverCount; }
    
    void shutdownAll() {
        for (int i = 0; i < driverCount; i++) {
            if (drivers[i])
                drivers[i]->shutdown();
        }
        driverCount = 0;
    }
    
    void listDrivers() {
        // This would print driver info - needs external print function
    }
};

DriverManager* DriverManager::instance = nullptr;

// ========== C Interface ==========
extern "C" {
    void* driver_manager_get_instance() {
        return DriverManager::getInstance();
    }
    
    void* driver_manager_create_keyboard() {
        KeyboardDriver* kbd = new KeyboardDriver();
        DriverManager::getInstance()->registerDriver(kbd);
        return kbd;
    }
    
    void* driver_manager_create_disk() {
        ATADriver* disk = new ATADriver();
        DriverManager::getInstance()->registerDriver(disk);
        return disk;
    }
    
    void* driver_manager_create_timer() {
        TimerDriver* timer = new TimerDriver();
        DriverManager::getInstance()->registerDriver(timer);
        return timer;
    }
    
    void* driver_manager_create_rtc() {
        RTCDriver* rtc = new RTCDriver();
        DriverManager::getInstance()->registerDriver(rtc);
        return rtc;
    }
    
    void driver_manager_handle_irq(uint32_t irq) {
        Driver* driver = DriverManager::getInstance()->getDriverByIRQ(irq);
        if (driver)
            driver->handleInterrupt();
    }
}

// ========== Operator Overloads ==========
void* operator new(size_t size, void* ptr) {
    return ptr;
}

void* operator new(size_t size) {
    // Simple bump allocator
    static uint8_t heap[131072];
    static size_t heap_pos = 0;
    
    size = (size + 15) & ~15;
    
    if (heap_pos + size > sizeof(heap))
        return nullptr;
    
    void* ptr = &heap[heap_pos];
    heap_pos += size;
    return ptr;
}

void* operator new[](size_t size) {
    return operator new(size);
}

void operator delete(void* ptr) noexcept {
    // No-op for now
}

void operator delete(void* ptr, size_t size) noexcept {
    // No-op for now
}

void operator delete[](void* ptr) noexcept {
    // No-op for now
}