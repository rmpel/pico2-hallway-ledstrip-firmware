# PIO-based WS2812 driver for RP2040/RP2350.
# Drop-in for `neopixel.NeoPixel`: supports buf[i] = (r,g,b) and .write().
# Uses the PIO peripheral for cycle-accurate WS2812 timing, which avoids the
# bit-banged glitches seen with MicroPython's `neopixel` on RP2350 (Pico 2 W).

import array
import rp2
from machine import Pin


@rp2.asm_pio(
    sideset_init=rp2.PIO.OUT_LOW,
    out_shiftdir=rp2.PIO.SHIFT_LEFT,
    autopull=True,
    pull_thresh=24,
)
def _ws2812_prog():
    T1 = 2
    T2 = 5
    T3 = 3
    wrap_target()
    label("bitloop")
    out(x, 1)               .side(0)    [T3 - 1]
    jmp(not_x, "do_zero")   .side(1)    [T1 - 1]
    jmp("bitloop")          .side(1)    [T2 - 1]
    label("do_zero")
    nop()                   .side(0)    [T2 - 1]
    wrap()


class WS2812PIO:
    def __init__(self, pin, num_leds, sm_id=0):
        self.num_leds = num_leds
        self.buf = array.array("I", [0] * num_leds)
        self.sm = rp2.StateMachine(
            sm_id, _ws2812_prog, freq=8_000_000, sideset_base=Pin(pin)
        )
        self.sm.active(1)

    def __setitem__(self, i, color):
        r, g, b = color
        # WS2812 wire order is GRB, packed in the high 24 bits.
        self.buf[i] = (g << 16 | r << 8 | b) << 8

    def __getitem__(self, i):
        v = self.buf[i] >> 8
        return ((v >> 8) & 0xFF, (v >> 16) & 0xFF, v & 0xFF)

    def __len__(self):
        return self.num_leds

    def fill(self, color):
        for i in range(self.num_leds):
            self[i] = color

    def write(self):
        self.sm.put(self.buf, 0)
