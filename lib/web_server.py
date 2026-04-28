# Web server for configuration UI and API

import socket
import json
import time


class WebServer:
    def __init__(self, storage, wifi_manager, scheduler, sun_times, ntp_sync=None):
        """Initialize web server"""
        self.storage = storage
        self.wifi = wifi_manager
        self.scheduler = scheduler
        self.sun_times = sun_times
        self.ntp = ntp_sync
        self.socket = None

    def start(self, port=80):
        """Start the web server"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind(('0.0.0.0', port))
            self.socket.listen(5)
            self.socket.setblocking(False)  # Non-blocking mode
            print(f"Web server started on port {port}")
            return True
        except Exception as e:
            print(f"Failed to start web server: {e}")
            return False

    def stop(self):
        """Stop the web server"""
        if self.socket:
            self.socket.close()
            self.socket = None
            print("Web server stopped")

    def _read_file(self, path):
        """Read file content"""
        try:
            with open(path, 'r') as f:
                return f.read()
        except Exception as e:
            print(f"Error reading file {path}: {e}")
            return None

    def _send_response(self, client, status, content_type, body):
        """Send HTTP response"""
        try:
            # Convert body to bytes if it's a string
            body_bytes = body.encode('utf-8') if isinstance(body, str) else body

            # Build complete response
            response = f"HTTP/1.1 {status}\r\n"
            response += f"Content-Type: {content_type}; charset=utf-8\r\n"
            response += f"Content-Length: {len(body_bytes)}\r\n"
            response += "Connection: close\r\n"
            response += "\r\n"

            # Send headers + body together
            try:
                client.sendall(response.encode('utf-8') + body_bytes)
            except:
                # If sendall fails, try regular send
                client.send(response.encode('utf-8'))
                client.send(body_bytes)

        except Exception as e:
            print(f"Error sending response: {e}")
            import sys
            sys.print_exception(e)

    def _handle_api_status(self, client):
        """Handle /api/status request"""
        wifi_status = self.wifi.get_connection_status()
        schedule_info = self.scheduler.get_current_schedule_info()

        # Get current time
        t = time.localtime()
        current_time_str = "{:02d}:{:02d}:{:02d}".format(t[3], t[4], t[5])
        current_time_seconds = t[3] * 3600 + t[4] * 60 + t[5]

        # Get sun times if available
        sun_times = None
        if self.scheduler.sun_times:
            sunrise_secs = self.scheduler.sun_times.get("sunrise", 0)
            sunset_secs = self.scheduler.sun_times.get("sunset", 0)
            sun_times = {
                "sunrise": "{:02d}:{:02d}".format(int(sunrise_secs // 3600), int((sunrise_secs % 3600) // 60)),
                "sunset": "{:02d}:{:02d}".format(int(sunset_secs // 3600), int((sunset_secs % 3600) // 60))
            }

        # Get NTP sync status
        ntp_status = None
        if self.ntp:
            last_sync = self.ntp.get_last_sync_time()
            if last_sync is not None:
                ntp_status = {
                    "synced": True,
                    "last_sync_seconds_ago": int(last_sync)
                }
            else:
                ntp_status = {
                    "synced": False,
                    "last_sync_seconds_ago": None
                }

        status = {
            "mode": self.storage.get_mode(),
            "wifi": wifi_status,
            "manual": {
                "brightness": self.storage.get_manual_settings()[0],
                "hue": self.storage.get_manual_settings()[1],
                "saturation": self.storage.get_manual_settings()[2]
            },
            "schedule_info": schedule_info,
            "location_configured": self.storage.has_location_config(),
            "current_time": current_time_str,
            "current_time_seconds": current_time_seconds,
            "sun_times": sun_times,
            "ntp": ntp_status
        }

        body = json.dumps(status)
        self._send_response(client, "200 OK", "application/json", body)

    def _handle_api_config_get(self, client):
        """Handle GET /api/config request - returns settings only (no WiFi credentials)"""
        settings = self.storage.get_all_settings()
        body = json.dumps(settings)
        self._send_response(client, "200 OK", "application/json", body)

    def _handle_api_config_post(self, client, request_body):
        """Handle POST /api/config request - saves settings only (no WiFi credentials)"""
        try:
            print(f"Received config update, body length: {len(request_body)}")

            if not request_body or len(request_body.strip()) == 0:
                raise ValueError("Empty request body")

            new_settings = json.loads(request_body)
            print(f"Parsed settings: {list(new_settings.keys())}")

            self.storage.update_settings(new_settings)

            # If location changed, refresh sun times
            if "location" in new_settings:
                print("Location updated, refreshing sun times...")
                self.sun_times.update_scheduler(self.scheduler, force_refresh=True)

            # If schedule changed, just ensure sun times are still set (don't re-fetch)
            elif "schedule" in new_settings:
                print("Schedule updated, recalculating transitions...")
                # Scheduler will automatically recalculate on next update() call
                # No need to refresh sun times from API

            body = json.dumps({"success": True})
            self._send_response(client, "200 OK", "application/json", body)
        except ValueError as e:
            print(f"JSON parse error: {e}")
            body = json.dumps({"success": False, "error": f"Invalid JSON: {str(e)}"})
            self._send_response(client, "400 Bad Request", "application/json", body)
        except Exception as e:
            print(f"Config update error: {e}")
            import sys
            sys.print_exception(e)
            body = json.dumps({"success": False, "error": str(e)})
            self._send_response(client, "400 Bad Request", "application/json", body)

    def _handle_api_wifi_test(self, client, request_body):
        """Handle POST /api/wifi/test request"""
        try:
            print(f"=== WiFi Test Request ===")
            print(f"Body length: {len(request_body) if request_body else 0}")

            data = json.loads(request_body)

            ssid = data.get("ssid")
            password = data.get("password")
            print(f"SSID: {ssid}, Password: ***")

            if not ssid or not password:
                body = json.dumps({"success": False, "error": "Missing ssid or password"})
                self._send_response(client, "400 Bad Request", "application/json", body)
                return

            # Test credentials (this will also save if successful)
            success = self.wifi.test_and_save_credentials(ssid, password)

            body = json.dumps({"success": success})
            self._send_response(client, "200 OK", "application/json", body)

            # If successful, we should reboot to connect to new WiFi
            if success:
                time.sleep(2)
                import machine
                machine.reset()

        except Exception as e:
            body = json.dumps({"success": False, "error": str(e)})
            self._send_response(client, "400 Bad Request", "application/json", body)

    def _handle_api_mode(self, client, request_body):
        """Handle POST /api/mode request"""
        try:
            data = json.loads(request_body)
            mode = data.get("mode")

            if mode not in ["auto", "on", "rainbow", "off"]:
                body = json.dumps({"success": False, "error": "Invalid mode"})
                self._send_response(client, "400 Bad Request", "application/json", body)
                return

            self.storage.set_mode(mode)
            body = json.dumps({"success": True})
            self._send_response(client, "200 OK", "application/json", body)
        except Exception as e:
            body = json.dumps({"success": False, "error": str(e)})
            self._send_response(client, "400 Bad Request", "application/json", body)

    def _handle_api_manual(self, client, request_body):
        """Handle POST /api/manual request - set manual mode color"""
        try:
            data = json.loads(request_body)
            hue = data.get("hue")
            saturation = data.get("saturation")
            brightness = data.get("brightness")

            # Validate values
            if hue is None or saturation is None or brightness is None:
                body = json.dumps({"success": False, "error": "Missing hue, saturation, or brightness"})
                self._send_response(client, "400 Bad Request", "application/json", body)
                return

            if not (0 <= hue <= 360 and 0 <= saturation <= 100 and 0 <= brightness <= 100):
                body = json.dumps({"success": False, "error": "Invalid HSV values"})
                self._send_response(client, "400 Bad Request", "application/json", body)
                return

            self.storage.set_manual_settings(brightness, hue, saturation)
            body = json.dumps({"success": True})
            self._send_response(client, "200 OK", "application/json", body)
        except Exception as e:
            body = json.dumps({"success": False, "error": str(e)})
            self._send_response(client, "400 Bad Request", "application/json", body)

    def _parse_request(self, request):
        """Parse HTTP request"""
        try:
            # Handle empty requests
            if not request or len(request.strip()) == 0:
                return None, None, None

            # Split headers and body
            parts_split = request.split('\r\n\r\n', 1)
            headers_section = parts_split[0]
            body = parts_split[1] if len(parts_split) > 1 else ''

            # Parse request line
            lines = headers_section.split('\r\n')
            if not lines or len(lines) == 0:
                return None, None, None

            request_line = lines[0]
            request_parts = request_line.split(' ')

            # Validate we have at least method and path
            if len(request_parts) < 2:
                print(f"Invalid request line: {request_line}")
                return None, None, None

            method = request_parts[0]
            path = request_parts[1]

            # Trim body (remove any trailing nulls or whitespace)
            body = body.strip('\x00').strip()

            # Only log API requests, not static files
            if path.startswith('/api/'):
                print(f"API: {method} {path}")

            return method, path, body
        except Exception as e:
            print(f"Error parsing request: {e}")
            import sys
            sys.print_exception(e)
            return None, None, None

    def handle_request(self):
        """Handle incoming HTTP requests (non-blocking)"""
        if not self.socket:
            return

        try:
            client, addr = self.socket.accept()
            client.settimeout(2.0)

            # Read the complete request
            try:
                request_data = b''
                while True:
                    chunk = client.recv(1024)
                    if not chunk:
                        break
                    request_data += chunk

                    # Check if we have complete headers
                    if b'\r\n\r\n' in request_data:
                        # Parse Content-Length if present
                        headers_end = request_data.find(b'\r\n\r\n')
                        try:
                            headers = request_data[:headers_end].decode('utf-8')
                        except:
                            headers = str(request_data[:headers_end])

                        # Find Content-Length
                        content_length = 0
                        for line in headers.split('\r\n'):
                            if line.lower().startswith('content-length:'):
                                content_length = int(line.split(':')[1].strip())
                                break

                        # Check if we have all the body
                        body_received = len(request_data) - headers_end - 4
                        if body_received >= content_length:
                            break

                request = request_data.decode('utf-8')
            except Exception as e:
                print(f"Failed to read request: {e}")
                import sys
                sys.print_exception(e)
                client.close()
                return
            method, path, body = self._parse_request(request)

            if method is None:
                client.close()
                return

            # Route requests
            if path == '/' or path == '/index.html':
                if self.wifi.is_ap_mode:
                    # In AP mode, serve setup page
                    content = self._read_file('/web/setup.html')
                else:
                    # Normal mode, serve main UI
                    content = self._read_file('/web/index.html')

                if content:
                    self._send_response(client, "200 OK", "text/html", content)
                else:
                    self._send_response(client, "404 Not Found", "text/plain", "File not found")

            elif path == '/test.html':
                content = self._read_file('/web/test.html')
                if content:
                    self._send_response(client, "200 OK", "text/html", content)
                else:
                    self._send_response(client, "404 Not Found", "text/plain", "File not found")

            elif path == '/style.css':
                content = self._read_file('/web/style.css')
                if content:
                    self._send_response(client, "200 OK", "text/css", content)
                else:
                    self._send_response(client, "404 Not Found", "text/plain", "File not found")

            elif path == '/api/status':
                self._handle_api_status(client)

            elif path == '/api/config' and method == 'GET':
                self._handle_api_config_get(client)

            elif path == '/api/config' and method == 'POST':
                self._handle_api_config_post(client, body)

            elif path == '/api/wifi/test' and method == 'POST':
                self._handle_api_wifi_test(client, body)

            elif path == '/api/mode' and method == 'POST':
                self._handle_api_mode(client, body)

            elif path == '/api/manual' and method == 'POST':
                self._handle_api_manual(client, body)

            else:
                self._send_response(client, "404 Not Found", "text/plain", "Not found")

            try:
                client.close()
            except:
                pass

        except OSError:
            # No pending connections (non-blocking)
            pass
        except Exception as e:
            print(f"Error handling request: {e}")
            import sys
            sys.print_exception(e)
            try:
                client.close()
            except:
                pass
