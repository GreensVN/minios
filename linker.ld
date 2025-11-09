/* linker.ld - Advanced Linker Script for MiniOS v4.0 ULTIMATE */

OUTPUT_FORMAT("elf32-i386")
OUTPUT_ARCH("i386")
ENTRY(kernel_main)

SECTIONS
{
    /* Kernel starts at 4KB (0x1000) */
    . = 0x1000;
    
    _kernel_start = .;
    _kernel_physical_start = .;
    
    /* ========== Boot Section ========== */
    .text.boot ALIGN(4K) : {
        *(.text.boot)
        . = ALIGN(4K);
    }
    
    /* ========== Code Section ========== */
    .text ALIGN(4K) : {
        *(.multiboot)
        *(.text)
        *(.text.*)
        . = ALIGN(4K);
    }
    
    /* ========== Read-Only Data ========== */
    .rodata ALIGN(4K) : {
        *(.rodata)
        *(.rodata.*)
        
        /* Constructor/Destructor tables */
        . = ALIGN(4);
        __CTOR_LIST__ = .;
        KEEP (*(.ctors))
        KEEP (*(SORT(.ctors.*)))
        __CTOR_END__ = .;
        
        . = ALIGN(4);
        __DTOR_LIST__ = .;
        KEEP (*(.dtors))
        KEEP (*(SORT(.dtors.*)))
        __DTOR_END__ = .;
        
        . = ALIGN(4K);
    }
    
    /* ========== Initialized Data ========== */
    .data ALIGN(4K) : {
        *(.data)
        *(.data.*)
        
        /* GOT (Global Offset Table) */
        . = ALIGN(4);
        *(.got)
        *(.got.plt)
        
        . = ALIGN(4K);
    }
    
    /* ========== BSS (Uninitialized Data) ========== */
    .bss ALIGN(4K) : {
        _bss_start = .;
        *(COMMON)
        *(.bss)
        *(.bss.*)
        . = ALIGN(4K);
        _bss_end = .;
    }
    
    /* ========== Kernel Heap ========== */
    .heap ALIGN(4K) : {
        _heap_start = .;
        . += 32M;  /* 32MB heap */
        _heap_end = .;
    }
    
    /* ========== Kernel Stack ========== */
    .stack ALIGN(4K) : {
        _stack_bottom = .;
        . += 16K;  /* 16KB stack */
        _stack_top = .;
    }
    
    /* ========== Symbols Table (Debug) ========== */
    .symtab : {
        *(.symtab)
    }
    
    .strtab : {
        *(.strtab)
    }
    
    /* ========== Kernel End Marker ========== */
    . = ALIGN(4K);
    _kernel_end = .;
    _kernel_physical_end = .;
    _kernel_size = _kernel_end - _kernel_start;
    
    /* ========== Discard Sections ========== */
    /DISCARD/ : {
        *(.comment)
        *(.eh_frame)
        *(.eh_frame_hdr)
        *(.note.gnu.build-id)
        *(.note)
        *(.note.*)
        *(.gcc_except_table)
        *(.rel.*)
        *(.rela.*)
    }
}

/* ========== Exported Symbols ========== */

/* Section start/end markers */
_text_start = ADDR(.text);
_text_end = ADDR(.text) + SIZEOF(.text);
_rodata_start = ADDR(.rodata);
_rodata_end = ADDR(.rodata) + SIZEOF(.rodata);
_data_start = ADDR(.data);
_data_end = ADDR(.data) + SIZEOF(.data);

/* Size calculations */
_text_size = SIZEOF(.text);
_rodata_size = SIZEOF(.rodata);
_data_size = SIZEOF(.data);
_bss_size = _bss_end - _bss_start;

/* Total kernel size in pages (4KB each) */
_kernel_pages = (_kernel_size + 0xFFF) >> 12;

/* Memory layout verification */
ASSERT(_kernel_start == 0x1000, "Kernel must start at 0x1000")
ASSERT(_bss_start % 4096 == 0, "BSS must be page-aligned")
ASSERT(_heap_start % 4096 == 0, "Heap must be page-aligned")
ASSERT(_stack_bottom % 4096 == 0, "Stack must be page-aligned")