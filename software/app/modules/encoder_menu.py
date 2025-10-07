import RPi.GPIO as GPIO
import time

class EncoderHandler:
    def __init__(self, clk_pin=22, dt_pin=18, sw_pin=27):
        self.clk_pin = clk_pin
        self.dt_pin = dt_pin
        self.sw_pin = sw_pin

        GPIO.setmode(GPIO.BCM)
        GPIO.setup(clk_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(dt_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(sw_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        self.last_clk = GPIO.input(clk_pin)
        self.position = 0
        self.was_pressed = False

        # Setup interrupciones
        GPIO.add_event_detect(clk_pin, GPIO.BOTH, callback=self._rotated, bouncetime=2)
        GPIO.add_event_detect(sw_pin, GPIO.FALLING, callback=self._pressed, bouncetime=200)

    def _rotated(self, channel):
        clk_state = GPIO.input(self.clk_pin)
        dt_state = GPIO.input(self.dt_pin)
        if clk_state != self.last_clk:
            if dt_state != clk_state:
                self.position += 1
            else:
                self.position -= 1
            self.last_clk = clk_state

    def _pressed(self, channel):
        self.was_pressed = True

    def read(self):
        pos = self.position
        pressed = self.was_pressed
        self.position = 0
        self.was_pressed = False
        return pos, pressed

    def cleanup(self):
        GPIO.cleanup()
