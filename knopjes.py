import time
import micropython
import hardware_setup
from machine import Pin

# Globale menu variabelen
menu_active = False
menu_options = ["Discard", "Emulate", "Crack"]
current_menu_index = 0

class Button:
    def __init__(self, row, col, width, height, text, callback, litcolor=1):
        self.row = row
        self.col = col
        self.width = width
        self.height = height
        self.text = text
        self.callback = callback
        self.litcolor = litcolor
        self.bgcolor = 0
        self.fgcolor = 1

    def show(self):
        hardware_setup.ssd.fill_rect(self.col, self.row, self.width, self.height, self.bgcolor)
        hardware_setup.ssd.rect(self.col, self.row, self.width, self.height, self.fgcolor)
        x_text = self.col + (self.width - len(self.text)*6) // 2
        y_text = self.row + (self.height - 8) // 2
        hardware_setup.ssd.text(self.text, x_text, y_text, self.fgcolor)
        hardware_setup.ssd.show()

    def do_sel(self):
        self.bgcolor = self.litcolor
        self.show()
        time.sleep(0.2)
        self.bgcolor = 0
        self.show()
        self.callback(self)

def update_menu_display():
    from hardware_setup import ssd
    ssd.fill(0)
    global current_menu_index
    prev_index = (current_menu_index - 1) % len(menu_options)
    next_index = (current_menu_index + 1) % len(menu_options)
    ssd.text(" " + menu_options[prev_index], 0, 0, 1)
    ssd.text(">" + menu_options[current_menu_index], 0, 10, 1)
    ssd.text(" " + menu_options[next_index], 0, 20, 1)
    ssd.show()

# Callback-functies voor de knoppen
def menu_pressed(btn):
    global menu_active, current_menu_index
    menu_active = True
    current_menu_index = 0
    update_menu_display()

def next_pressed(btn):
    global menu_active, current_menu_index
    if menu_active:
        current_menu_index = (current_menu_index + 1) % len(menu_options)
        update_menu_display()

def confirm_pressed(btn, emulate_callback, crack_callback, discard_callback, resume_callback):
    global menu_active, current_menu_index
    if menu_active:
        selected = menu_options[current_menu_index]
        if selected == "Discard":
            discard_callback()
        elif selected == "Emulate":
            emulate_callback()
        elif selected == "Crack":
            crack_callback()
        menu_active = False
        if resume_callback:
            resume_callback()

def setup_button_irqs(btn_menu, btn_next, btn_confirm):
    def menu_irq(pin):
        micropython.schedule(lambda _: btn_menu.do_sel(), 0)
    def next_irq(pin):
        micropython.schedule(lambda _: btn_next.do_sel(), 0)
    def confirm_irq(pin):
        micropython.schedule(lambda _: btn_confirm.do_sel(), 0)
    phys_sw_menu = Pin(26, Pin.IN, Pin.PULL_UP)
    phys_sw_next = Pin(27, Pin.IN, Pin.PULL_UP)
    phys_sw_confirm = Pin(28, Pin.IN, Pin.PULL_UP)
    phys_sw_menu.irq(trigger=Pin.IRQ_FALLING, handler=menu_irq)
    phys_sw_next.irq(trigger=Pin.IRQ_FALLING, handler=next_irq)
    phys_sw_confirm.irq(trigger=Pin.IRQ_FALLING, handler=confirm_irq)

def create_buttons(menu_cb, next_cb, confirm_cb):
    btn_menu = Button(40, 0, 40, 20, "Menu", menu_cb)
    btn_next = Button(40, 45, 40, 20, "Next", next_cb)
    btn_confirm = Button(40, 90, 40, 20, "OK", confirm_cb)
    btn_menu.show()
    btn_next.show()
    btn_confirm.show()
    setup_button_irqs(btn_menu, btn_next, btn_confirm)
    return btn_menu, btn_next, btn_confirm
