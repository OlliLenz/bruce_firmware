#include "core/powerSave.h"
#include "esp_sleep.h"
#include <Arduino.h>
#include <interface.h>

static constexpr uint8_t PIN_BUTTON_A = 32;
static constexpr uint8_t PIN_BUTTON_B = 33;
static constexpr uint8_t PIN_BUTTON_MENU = 13;
static constexpr uint8_t PIN_BUTTON_SELECT = 27;
static constexpr uint8_t PIN_BUTTON_VOLUME = 0;
static constexpr uint8_t PIN_BUTTON_START = 39;
static constexpr uint8_t PIN_DPAD_X = 34;
static constexpr uint8_t PIN_DPAD_Y = 35;
static constexpr int ADC_POSITIVE_LEVEL = 3072;
static constexpr int ADC_NEGATIVE_LEVEL = 1024;

static bool activeLow(uint8_t pin) { return digitalRead(pin) == LOW; }

void _setup_gpio() {
    pinMode(TFT_BL, OUTPUT);
    digitalWrite(TFT_BL, HIGH);
    bruceConfig.colorInverted = 0;

    pinMode(PIN_BUTTON_A, INPUT_PULLUP);
    pinMode(PIN_BUTTON_B, INPUT_PULLUP);
    pinMode(PIN_BUTTON_MENU, INPUT_PULLUP);
    pinMode(PIN_BUTTON_SELECT, INPUT_PULLUP);
    pinMode(PIN_BUTTON_VOLUME, INPUT_PULLUP);
    pinMode(PIN_BUTTON_START, INPUT_PULLUP);

    pinMode(PIN_DPAD_X, INPUT);
    pinMode(PIN_DPAD_Y, INPUT);

    analogReadResolution(12);
    analogSetPinAttenuation(PIN_DPAD_X, ADC_11db);
    analogSetPinAttenuation(PIN_DPAD_Y, ADC_11db);
    analogSetPinAttenuation(BAT_PIN, ADC_11db);
}

void _post_setup_gpio() {
    bruceConfigPins.rotation = ROTATION;
    tft.setRotation(bruceConfigPins.rotation);
    tft.setRotation(bruceConfigPins.rotation);
    bruceConfig.colorInverted = 0;
    tft.invertDisplay(false);
}

int getBattery() {
    int raw = analogRead(BAT_PIN);
    float voltage = (raw / 4095.0f) * 3.3f * 2.0f;
    int percent = roundf((voltage - 3.3f) * 100.0f / (4.2f - 3.3f));
    return constrain(percent, 1, 100);
}

void _setBrightness(uint8_t brightval) {
    (void)brightval;
    digitalWrite(TFT_BL, HIGH);
}

void InputHandler(void) {
    static unsigned long tm = 0;
    if (millis() - tm < 160 && !LongPress) return;

    bool aPressed = activeLow(PIN_BUTTON_A);
    bool bPressed = activeLow(PIN_BUTTON_B);
    bool menuPressed = activeLow(PIN_BUTTON_MENU);
    bool selectPressed = activeLow(PIN_BUTTON_SELECT);
    bool volumePressed = activeLow(PIN_BUTTON_VOLUME);
    bool startPressed = activeLow(PIN_BUTTON_START);

    int dpadX = analogRead(PIN_DPAD_X);
    int dpadY = analogRead(PIN_DPAD_Y);
    bool leftPressed = dpadX > ADC_POSITIVE_LEVEL;
    bool rightPressed = !leftPressed && dpadX > ADC_NEGATIVE_LEVEL;
    bool upPressed = dpadY > ADC_POSITIVE_LEVEL;
    bool downPressed = !upPressed && dpadY > ADC_NEGATIVE_LEVEL;

    bool anyPressed = aPressed || bPressed || menuPressed || selectPressed || volumePressed || startPressed ||
                      leftPressed || rightPressed || upPressed || downPressed;
    if (!anyPressed) return;

    tm = millis();
    if (wakeUpScreen()) return;

    AnyKeyPress = true;
    SelPress = aPressed || startPressed;
    EscPress = bPressed || menuPressed;
    PrevPress = leftPressed;
    NextPress = rightPressed;
    UpPress = upPressed;
    DownPress = downPressed;
    PrevPagePress = selectPressed;
    NextPagePress = volumePressed;
}

void powerOff() {
    digitalWrite(TFT_BL, LOW);
    tft.writecommand(0x10);
    esp_sleep_enable_ext0_wakeup((gpio_num_t)PIN_BUTTON_MENU, LOW);
    esp_deep_sleep_start();
}

void goToDeepSleep() { powerOff(); }

void checkReboot() {}
