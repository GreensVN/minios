/* driver_manager.h - C interface to the C++ driver framework (driver_manager.cpp)
 *
 * The drivers themselves are C++ classes; the kernel (C) talks to them through
 * these plain functions.  Everything here is safe to call from C.
 */
#ifndef MINIOS_DRIVER_MANAGER_H
#define MINIOS_DRIVER_MANAGER_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    uint8_t  second, minute, hour;
    uint8_t  day, month;
    uint16_t year;
} rtc_datetime_t;

/* driver ids (see Driver::getId()) */
enum {
    DRIVER_KEYBOARD = 1,
    DRIVER_ATA      = 2,
    DRIVER_TIMER    = 3,
    DRIVER_RTC      = 4,
};

/* registration – each returns true if the driver initialised successfully */
bool     driver_manager_init_keyboard(void);
bool     driver_manager_init_disk(void);
bool     driver_manager_init_timer(uint32_t hz);
bool     driver_manager_init_rtc(void);

/* dispatch a hardware IRQ (0..15) to the driver that registered it */
void     driver_manager_handle_irq(uint32_t irq);
int      driver_manager_count(void);
const char *driver_manager_name(int index);          /* NULL when out of range */
bool     driver_manager_present(uint32_t id);

/* keyboard */
bool     driver_keyboard_has_key(void);
char     driver_keyboard_get_key(void);

/* ATA (primary master, 28-bit LBA, PIO) */
uint32_t driver_disk_sector_count(void);
const char *driver_disk_model(void);
bool     driver_disk_read(uint32_t lba, uint8_t *buf512);
bool     driver_disk_write(uint32_t lba, const uint8_t *buf512);

/* timer */
uint32_t driver_timer_ticks(void);
uint32_t driver_timer_frequency(void);

/* RTC */
bool     driver_rtc_read(rtc_datetime_t *out);

#ifdef __cplusplus
}
#endif

#endif /* MINIOS_DRIVER_MANAGER_H */
