#pragma once
#include "esphome/core/component.h"
#include "esphome/components/mqtt/mqtt_client.h"
#include <Arduino.h>
#include <NimBLEDevice.h>
#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <cstring>
#include <string>
extern "C" {
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
}

namespace esphome {
namespace airbnk_gateway {

static constexpr const char *TAG = "airbnk_mqtt";
static constexpr uint16_t SERVICE_UUID = 0xFFF0;
static constexpr uint16_t CHARACTERISTIC_UUID = 0xFFF2;
static constexpr uint16_t STATUS_CHARACTERISTIC_UUID = 0xFFF3;
static constexpr uint8_t SCAN_INTERVAL = 0x80;
static constexpr uint8_t SCAN_WINDOW = 0x40;

class AirbnkGateway : public Component {
 public:
  AirbnkGateway(const std::string &mac, const std::string &root_topic)
      : lock_mac_(capitalize_(mac)),
        advert_topic_(root_topic + "/adv"),
        command_topic_(root_topic + "/command"),
        command_result_topic_(root_topic + "/command_result") {}

  void setup() override {
    NimBLEDevice::init("");
    NimBLEDevice::setPower(ESP_PWR_LVL_P9);
    scan_ = NimBLEDevice::getScan();
    // REZOLVARE: Schimbat din setCallbacks în setScanCallbacks conform noii librării NimBLE
    scan_->setScanCallbacks(new AdvertisedCallbacks(*this), true);
    scan_->setInterval(SCAN_INTERVAL);
    scan_->setWindow(SCAN_WINDOW);
    scan_->setActiveScan(false);
    scan_->setMaxResults(0);
    client_ = NimBLEDevice::createClient();

    if (mqtt::global_mqtt_client == nullptr) {
      ESP_LOGE(TAG, "MQTT client is not available");
      mark_failed();
      return;
    }

    // REZOLVARE: Corectat definiția lambda pentru a include și string-ul "topic" solicitat de ESPHome
    mqtt::global_mqtt_client->subscribe_json(
        command_topic_,
        [this](const std::string &topic, JsonObject root) { on_command_(root); });

    start_scan_task_();
  }

  void dump_config() override {
    ESP_LOGCONFIG(TAG, "Airbnk BLE Gateway");
    ESP_LOGCONFIG(TAG, "  Lock MAC: %s", lock_mac_.c_str());
    ESP_LOGCONFIG(TAG, "  Advert topic: %s", advert_topic_.c_str());
    ESP_LOGCONFIG(TAG, "  Command topic: %s", command_topic_.c_str());
    ESP_LOGCONFIG(TAG, "  Result topic: %s", command_result_topic_.c_str());
  }

 protected:
  std::string lock_mac_, advert_topic_, command_topic_, command_result_topic_;
  NimBLEScan *scan_{nullptr};
  NimBLEClient *client_{nullptr};
  NimBLEAddress lock_address_{};
  TaskHandle_t scan_task_{nullptr};
  volatile bool is_sending_{false};

  static std::string capitalize_(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(),
      [](unsigned char c) { return static_cast<char>(std::toupper(c)); });
    return s;
  }

  static int from_hex_(uint8_t *dest, const char *src, int maxlen) {
    if (!src) return 0;
    int srclen = static_cast<int>(std::strlen(src) / 2);
    if (srclen > maxlen) return 0;
    std::memset(dest, 0, maxlen);
    for (int i = 0; i < srclen; i++) {
      char t[3] = {src[i * 2], src[i * 2 + 1], 0};
      if (t[0] == '/') t[0] = '0';
      if (t[1] == '/') t[1] = '0';
      if (!std::isalnum((unsigned char)t[0]) ||
          !std::isalnum((unsigned char)t[1])) return 0;
      t[0] |= 0x20; t[1] |= 0x20;
      if (std::isalpha((unsigned char)t[0]) && (t[0] < 'a' || t[0] > 'f')) return 0;
      if (std::isalpha((unsigned char)t[1]) && (t[1] < 'a' || t[1] > 'f')) return 0;
      *dest++ = static_cast<uint8_t>(std::strtol(t, nullptr, 16));
    }
    return srclen;
  }

  // REZOLVARE: Redenumit din HEX în HEX_CHARS pentru a opri conflictul cu macro-ul nativ Arduino (#define HEX 16)
  static std::string to_hex_(const std::string& data) {
    static constexpr char HEX_CHARS[] = "0123456789ABCDEF";
    std::string out;
    out.reserve(data.size() * 2);
    for (size_t i = 0; i < data.size(); ++i) {
      uint8_t c = data[i];
      out.push_back(HEX_CHARS[(c >> 4) & 0x0F]);
      out.push_back(HEX_CHARS[c & 0x0F]);
    }
    return out;
  }

  bool report_device_(NimBLEAdvertisedDevice &device) {
    NimBLEAddress address = device.getAddress();
    std::string mac = capitalize_(address.toString());
    if (mac != lock_mac_) return false;
    lock_address_ = address;

    std::string data = device.getManufacturerData();
    std::string hex_str = to_hex_(data);

    if (mqtt::global_mqtt_client != nullptr) {
      int rssi = device.getRSSI();
      mqtt::global_mqtt_client->publish_json(
          advert_topic_,
          [=](JsonObject root) {
            root["mac"] = mac;
            root["rssi"] = rssi;
            root["data"] = hex_str;
          }, 1, false);
    }
    return true;
  }

  void send_result_(bool success, const std::string &error, int sign,
                    const std::string &status) {
    while (mqtt::global_mqtt_client != nullptr &&
           !mqtt::global_mqtt_client->is_connected()) delay(100);
    if (mqtt::global_mqtt_client == nullptr) return;

    std::string mac = lock_mac_;
    mqtt::global_mqtt_client->publish_json(
        command_result_topic_,
        [=](JsonObject root) {
          root["success"] = success;
          root["error"] = error;
          root["sign"] = sign;
          root["mac"] = mac;
          root["lockStatus"] = status;
        }, 1, false);
  }

  void send_ble_payload_(JsonObject &root) {
    is_sending_ = true;
    if (scan_) {
      scan_->stop();
      while (scan_->isScanning()) delay(100);
    }
    if (scan_task_) {
      vTaskDelete(scan_task_);
      scan_task_ = nullptr;
    }

    bool result = false;
    std::string error, status;
    int sign = root["sign"] | 0;
    const char *cmnd1 = root["command1"] | "";
    const char *cmnd2 = root["command2"] | "";
    uint8_t command1[20], command2[20];
    int len1 = from_hex_(command1, cmnd1, 20);
    int len2 = from_hex_(command2, cmnd2, 20);

    if (!len1 || !len2) {
      error = "INVALID COMMAND";
    } else {
      int retry = 1;
      while (retry < 5 && !result) {
        if (retry > 1) delay(500);

        if (client_ && client_->connect(lock_address_, true)) {
          NimBLERemoteService *service = client_->getService(BLEUUID(SERVICE_UUID));
          if (!service) {
            error = "FAILED TO GET SERVICE";
          } else {
            NimBLERemoteCharacteristic *cmd =
                service->getCharacteristic(NimBLEUUID(CHARACTERISTIC_UUID));
            if (!cmd) {
              error = "FAILED TO GET CHARACTERISTIC";
            } else if (!cmd->writeValue(command1, len1, true) ||
                       !cmd->writeValue(command2, len2, true)) {
              error = "FAILED TO WRITE";
            } else {
              NimBLERemoteCharacteristic *st =
                  service->getCharacteristic(NimBLEUUID(STATUS_CHARACTERISTIC_UUID));
              if (!st) {
                error = "FAILED TO GET STATUS CHARACTERISTIC";
              } else {
                time_t timestamp = 0;
                int tries = 10;
                while (tries > 0 &&
                       (status.empty() ||
                        (status.size() >= 2 &&
                         status.compare(status.size() - 2, 2, "00") == 0))) {
                  if (tries < 10) delay(100);
                  std::string read_status = st->readValue(&timestamp);
                  if (read_status.empty()) {
                    error = "FAILED TO READ STATUS";
                    tries = 0;
                  } else {
                    result = true;
                    error.clear();
                    status = to_hex_(read_status);
                  }
                  --tries;
                }
              }
            }
          }
          client_->disconnect();
        } else {
          error = "FAILED TO CONNECT";
        }
        ++retry;
      }
    }

    is_sending_ = false;
    send_result_(result, error, sign, status);
    start_scan_task_();
  }

  void on_command_(JsonObject root) {
    if (is_sending_) return;
    send_ble_payload_(root);
  }

  void scan_loop_() {
    while (true) {
      if (scan_ && !scan_->isScanning())
        // REZOLVARE: Schimbat al doilea argument din nullptr în false conform noii semnături NimBLEScan::start
        scan_->start(0, false, false);
      delay(5000);
    }
  }

  static void scan_task_entry_(void *arg) {
    static_cast<AirbnkGateway *>(arg)->scan_loop_();
  }

  void start_scan_task_() {
    xTaskCreatePinnedToCore(scan_task_entry_, "scan_task", 4096, this, 1, &scan_task_, 0);
  }

  // REZOLVARE: Modificat moștenirea în NimBLEScanCallbacks și adăugat modificatorul "const" în onResult
  class AdvertisedCallbacks : public NimBLEScanCallbacks {
    AirbnkGateway &gateway_;
   public:
    AdvertisedCallbacks(AirbnkGateway &gateway) : gateway_(gateway) {}
    void onResult(const NimBLEAdvertisedDevice *device) override {
      gateway_.report_device_(*const_cast<NimBLEAdvertisedDevice*>(device));
    }
  };
};

}  // namespace airbnk_gateway
}  // namespace esphome
