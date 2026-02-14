#include <Arduino.h>
#include "generated/daemon_runtime.h"

static float g_speed = 0.0f;
static float g_heading_deg = 0.0f;

// @daemon:export token=FWD desc="Move forward" args="speed:float[0..1]" safety="rate_hz=10,watchdog_ms=500,clamp=true" function=drive_fwd
void drive_fwd(float speed) {
  g_speed = speed;
  Serial.print("drive_fwd speed=");
  Serial.println(speed, 3);
}

// @daemon:export token=TURN desc="Turn" args="deg:float[-180..180]" safety="rate_hz=10,watchdog_ms=500,clamp=true" function=turn_deg
void turn_deg(float deg) {
  g_heading_deg += deg;
  Serial.print("turn_deg deg=");
  Serial.println(deg, 3);
}

void daemon_init(void) {
  daemon_runtime_init();
}

void daemon_loop(uint32_t now_ms) {
  static char line[128];
  static size_t idx = 0;

  while (Serial.available() > 0) {
    char c = static_cast<char>(Serial.read());
    if (c == '\r') {
      continue;
    }
    if (c == '\n') {
      line[idx] = '\0';
      daemon_runtime_handle_line(line, now_ms);
      idx = 0;
      continue;
    }
    if (idx + 1 < sizeof(line)) {
      line[idx++] = c;
    }
  }

  daemon_runtime_tick(now_ms);
}

void setup() {
  Serial.begin(115200);
  while (!Serial) {
  }
  daemon_init();
}

void loop() {
  daemon_loop(millis());
}
