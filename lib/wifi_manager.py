# WiFi manager with AP mode and connection testing

import network
import time
import machine
from config import AP_SSID_PREFIX, AP_IP


class WiFiManager:
    def __init__(self, storage, led_controller):
        """Initialize WiFi manager"""
        self.storage = storage
        self.led = led_controller
        self.wlan_sta = network.WLAN(network.STA_IF)
        self.wlan_ap = network.WLAN(network.AP_IF)
        self.is_ap_mode = False

    def get_mac_suffix(self):
        """Get last 4 characters of MAC address for unique SSID"""
        mac = machine.unique_id()
        return ''.join('{:02X}'.format(b) for b in mac[-2:])

    def start_ap_mode(self):
        """
        Start Access Point mode for WiFi configuration
        Returns: AP IP address
        """
        print("Starting AP mode...")

        # Disable station mode
        self.wlan_sta.active(False)
        time.sleep(0.5)

        # Activate AP first
        self.wlan_ap.active(True)
        time.sleep(0.5)

        # Configure AP with proper settings
        mac_suffix = self.get_mac_suffix()
        ssid = f"{AP_SSID_PREFIX}-{mac_suffix}"

        # Set AP configuration as OPEN network (no password)
        # Note: WPA2 support on Pico W AP mode is limited, using open network for setup
        self.wlan_ap.config(essid=ssid, security=0)

        # Wait for AP to stabilize
        time.sleep(1)

        # Set IP configuration
        self.wlan_ap.ifconfig((AP_IP, '255.255.255.0', AP_IP, AP_IP))

        # Wait a bit more for AP to be fully ready
        time.sleep(1)

        print(f"AP started: SSID={ssid}, Security=OPEN (no password), IP={AP_IP}")
        print(f"AP Active: {self.wlan_ap.active()}")
        print(f"AP Config: {self.wlan_ap.config('essid')}")

        self.is_ap_mode = True
        self.led.flash_white()  # Visual indicator

        return AP_IP

    def stop_ap_mode(self):
        """Stop Access Point mode"""
        self.wlan_ap.active(False)
        self.is_ap_mode = False
        print("AP mode stopped")

    def connect_to_wifi(self, ssid=None, password=None, timeout=20, retries=20):
        """
        Connect to WiFi network with retry logic
        ssid: WiFi SSID (if None, use stored credentials)
        password: WiFi password (if None, use stored credentials)
        timeout: Connection timeout in seconds
        retries: Number of retry attempts
        Returns: True if connected, False otherwise
        """
        if ssid is None:
            ssid = self.storage.get_wifi_ssid()
            password = self.storage.get_wifi_password()

        if ssid is None:
            print("No WiFi credentials available")
            return False

        # Start flashing orange status LED
        self.led.status_led_connecting()

        for attempt in range(retries):
            if attempt > 0:
                print(f"Retry attempt {attempt + 1}/{retries}...")
                time.sleep(2)

            print(f"Connecting to WiFi: {ssid}")
            print(f"SSID length: {len(ssid)}, Password length: {len(password)}")

            # Ensure AP mode is off
            self.wlan_ap.active(False)
            time.sleep(1)

            # Deactivate and reactivate station mode for clean slate
            self.wlan_sta.active(False)
            time.sleep(1)
            self.wlan_sta.active(True)
            time.sleep(1)

            # Force 2.4GHz by disabling power management
            # This helps with mesh/multiband routers
#             try:
#                 self.wlan_sta.config(pm=0xa11140)  # Disable power management
#             except:
#                 pass

            print(f"Calling wlan.connect()...")
            self.wlan_sta.connect(ssid, password)
            print(f"Connect called, waiting for connection...")

            # Wait for connection
            start_time = time.time()
            check_attempts = 0
            connected = False

            while not self.wlan_sta.isconnected():
                elapsed = time.time() - start_time
                status = self.wlan_sta.status()

                # Update flashing status LED
                self.led.update_status_led_flash()

                # Check for error states
                if status == -1:  # STAT_GENERIC_FAILURE
                    print(f"Connection attempt {attempt + 1} failed (status -1)")
                    break
                elif status == -2:  # STAT_NO_AP_FOUND
                    print(f"Network '{ssid}' not found")
                    break
                elif status == -3:  # STAT_WRONG_PASSWORD
                    print(f"Wrong password for '{ssid}'")
                    self.led.status_led_failed()
                    self.led.status_led_connecting()

                if elapsed > timeout:
                    print(f"Connection attempt {attempt + 1} timeout after {timeout}s")
                    break

                check_attempts += 1
                if check_attempts % 4 == 0:  # Every 2 seconds
                    print(f"Connecting... ({int(elapsed)}s, status={status})")

                time.sleep(0.5)

            if self.wlan_sta.isconnected():
                print(f"Connected to WiFi! IP: {self.wlan_sta.ifconfig()[0]}")
                self.led.status_led_success()
                return True

        # All retries failed
        print(f"Failed to connect after {retries} attempts")
        self.led.status_led_failed()
        return False

    def test_and_save_credentials(self, ssid, password):
        """
        Test WiFi credentials and save if successful
        Returns: True if successful, False otherwise
        """
        print(f"=== Testing WiFi credentials ===")
        print(f"SSID: {ssid}")
        print(f"Stopping AP mode before testing...")

        # Must stop AP mode before testing WiFi connection
        self.stop_ap_mode()
        time.sleep(1)

        if self.connect_to_wifi(ssid, password):
            # Connection successful - save credentials
            print("WiFi connection successful!")
            self.storage.set_wifi_credentials(ssid, password)
            print(f"WiFi credentials saved to storage")

            # Try to flash LED (won't error if not connected)
            try:
                self.led.flash_green()
            except:
                pass

            return True
        else:
            # Connection failed - restart AP mode
            print("WiFi connection failed, restarting AP mode...")
            try:
                self.led.flash_red()
            except:
                pass

            time.sleep(2)
            self.start_ap_mode()
            return False

    def ensure_connected(self):
        """
        Ensure WiFi is connected, try to reconnect if not
        Returns: True if connected, False otherwise
        """
        if self.is_ap_mode:
            return False  # Don't try to connect while in AP mode

        if self.wlan_sta.isconnected():
            return True

        # Try to reconnect
        print("WiFi disconnected, attempting to reconnect...")
        return self.connect_to_wifi()

    def get_connection_status(self):
        """
        Get current WiFi connection status
        Returns: dict with status info
        """
        if self.is_ap_mode:
            return {
                "mode": "ap",
                "ssid": f"{AP_SSID_PREFIX}-{self.get_mac_suffix()}",
                "ip": AP_IP,
                "connected": False
            }
        elif self.wlan_sta.isconnected():
            return {
                "mode": "sta",
                "ssid": self.storage.get_wifi_ssid(),
                "ip": self.wlan_sta.ifconfig()[0],
                "connected": True
            }
        else:
            return {
                "mode": "disconnected",
                "ssid": None,
                "ip": None,
                "connected": False
            }
