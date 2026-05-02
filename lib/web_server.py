# Web server for configuration UI and API

import socket
import json
import time
import os
import hashlib
import binascii


UPLOAD_PATH = "/api/files/upload"
STAGING_DIR = "/staging"
LISTABLE_DIRS = ("/lib", "/web")
LISTABLE_ROOT_EXTS = (".py", ".json")
PROTECTED = {"/config.json"}
MAX_NON_UPLOAD_BODY = 8192
UPLOAD_CHUNK = 1024


def _url_decode(s):
    s = s.replace("+", " ")
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "%" and i + 2 < len(s):
            try:
                out.append(chr(int(s[i+1:i+3], 16)))
                i += 3
                continue
            except ValueError:
                pass
        out.append(c)
        i += 1
    return "".join(out)


def _parse_query(qs):
    out = {}
    if not qs:
        return out
    for part in qs.split("&"):
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
        else:
            k, v = part, ""
        out[k] = _url_decode(v)
    return out


def _split_path(raw):
    if "?" in raw:
        p, qs = raw.split("?", 1)
    else:
        p, qs = raw, ""
    return p, _parse_query(qs)


def _safe_rel_path(p):
    if not p:
        return None
    if p.startswith("/"):
        p = p[1:]
    if not p:
        return None
    if ".." in p.split("/"):
        return None
    for ch in p:
        if not (ch.isalpha() or ch.isdigit() or ch in "._-/"):
            return None
    return "/" + p


def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def _is_dir(path):
    try:
        return (os.stat(path)[0] & 0x4000) != 0
    except OSError:
        return False


def _mkdir_p(path):
    parts = [p for p in path.split("/") if p]
    cur = ""
    for part in parts:
        cur = cur + "/" + part
        if not _exists(cur):
            try:
                os.mkdir(cur)
            except OSError:
                pass


def _remove_file(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _file_size(path):
    try:
        return os.stat(path)[6]
    except OSError:
        return -1


def _walk_listing():
    out = []
    for d in LISTABLE_DIRS:
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        for name in entries:
            full = d + "/" + name
            if _is_dir(full):
                continue
            out.append({"path": full, "size": _file_size(full)})
    try:
        for name in os.listdir("/"):
            full = "/" + name
            if _is_dir(full):
                continue
            if full in PROTECTED:
                continue
            for ext in LISTABLE_ROOT_EXTS:
                if name.endswith(ext):
                    out.append({"path": full, "size": _file_size(full)})
                    break
    except OSError:
        pass
    out.sort(key=lambda e: e["path"])
    return out


def _sha256_of_file(path):
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(512)
                if not chunk:
                    break
                h.update(chunk)
        return binascii.hexlify(h.digest()).decode("ascii")
    except OSError:
        return None


class WebServer:
    def __init__(self, storage, wifi_manager, scheduler, sun_times, ntp_sync=None, tz_offset=None, game=None):
        """Initialize web server"""
        self.storage = storage
        self.wifi = wifi_manager
        self.scheduler = scheduler
        self.sun_times = sun_times
        self.ntp = ntp_sync
        self.tz_offset = tz_offset
        self.game = game
        self.socket = None
        self.preview_active = False

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
        """Read file content (text)"""
        try:
            with open(path, 'r') as f:
                return f.read()
        except Exception as e:
            print(f"Error reading file {path}: {e}")
            return None

    def _read_file_bytes(self, path):
        try:
            with open(path, 'rb') as f:
                return f.read()
        except Exception:
            return None

    def _send_response(self, client, status, content_type, body):
        """Send HTTP response"""
        try:
            body_bytes = body.encode('utf-8') if isinstance(body, str) else body

            response = f"HTTP/1.1 {status}\r\n"
            response += f"Content-Type: {content_type}; charset=utf-8\r\n"
            response += f"Content-Length: {len(body_bytes)}\r\n"
            response += "Connection: close\r\n"
            response += "\r\n"

            try:
                client.sendall(response.encode('utf-8') + body_bytes)
            except:
                client.send(response.encode('utf-8'))
                client.send(body_bytes)

        except Exception as e:
            print(f"Error sending response: {e}")
            import sys
            sys.print_exception(e)

    def _send_json(self, client, status, obj):
        self._send_response(client, status, "application/json", json.dumps(obj))

    def _send_static(self, client, path, content_type):
        # Stream the file directly: avoids allocating the whole body in RAM,
        # and uses chunked sendall so a partial write can't desync from the
        # advertised Content-Length (was causing ERR_CONTENT_LENGTH_MISMATCH
        # for larger files like script.js on memory-constrained devices).
        size = _file_size(path)
        if size < 0:
            self._send_response(client, "404 Not Found", "text/plain", "File not found")
            return
        try:
            header = (
                "HTTP/1.1 200 OK\r\n"
                f"Content-Type: {content_type}; charset=utf-8\r\n"
                f"Content-Length: {size}\r\n"
                "Connection: close\r\n"
                "\r\n"
            )
            client.sendall(header.encode("utf-8"))
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(1024)
                    if not chunk:
                        break
                    client.sendall(chunk)
        except Exception as e:
            print(f"static send failed for {path}: {e}")

    def _handle_api_status(self, client):
        """Handle /api/status request"""
        wifi_status = self.wifi.get_connection_status()
        schedule_info = self.scheduler.get_current_schedule_info()

        # Time: device RTC is UTC. Browser converts for display.
        utc_epoch = int(time.time())
        tz_offset_seconds = self.storage.get_tz_offset_seconds()
        tz_offset_updated = self.storage.get_tz_offset_updated()

        # Sun times are stored as UTC seconds-since-midnight; pass through.
        sun_times = None
        if self.scheduler.sun_times:
            sun_times = {
                "sunrise_utc_seconds": self.scheduler.sun_times.get("sunrise_utc", 0),
                "sunset_utc_seconds": self.scheduler.sun_times.get("sunset_utc", 0)
            }

        ntp_status = None
        if self.ntp:
            last_sync = self.ntp.get_last_sync_time()
            ntp_status = {
                "synced": last_sync is not None,
                "last_sync_seconds_ago": int(last_sync) if last_sync is not None else None
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
            "utc_epoch": utc_epoch,
            "tz_offset_seconds": tz_offset_seconds,
            "tz_offset_updated": tz_offset_updated,
            "sun_times": sun_times,
            "ntp": ntp_status,
            "non_auto_is_temporary": self.storage.get_non_auto_is_temporary()
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

            # If location changed, refresh tz offset + sun times
            if "location" in new_settings:
                print("Location updated, refreshing tz offset and sun times...")
                if self.tz_offset is not None:
                    self.tz_offset.refresh(force=True)
                self.sun_times.update_scheduler(self.scheduler, force_refresh=True)

            # If schedule changed, just ensure sun times are still set (don't re-fetch)
            elif "schedule" in new_settings:
                print("Schedule updated, recalculating transitions...")

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

            success = self.wifi.test_and_save_credentials(ssid, password)

            body = json.dumps({"success": success})
            self._send_response(client, "200 OK", "application/json", body)

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

    def _handle_api_preview(self, client, request_body):
        """POST /api/preview - drive LEDs directly with HSV. Suspends mode-driven updates."""
        try:
            data = json.loads(request_body)
            hue = data.get("hue")
            saturation = data.get("saturation")
            brightness = data.get("brightness")
            if hue is None or saturation is None or brightness is None:
                self._send_json(client, "400 Bad Request",
                                {"success": False, "error": "missing hsv"})
                return
            if not (0 <= hue <= 360 and 0 <= saturation <= 100 and 0 <= brightness <= 100):
                self._send_json(client, "400 Bad Request",
                                {"success": False, "error": "invalid hsv"})
                return
            self.preview_active = True
            self.scheduler.led.set_color_hsv(hue, saturation, brightness)
            self._send_json(client, "200 OK", {"success": True})
        except Exception as e:
            self._send_json(client, "400 Bad Request", {"success": False, "error": str(e)})

    def _handle_api_preview_stop(self, client):
        """POST /api/preview/stop - resume normal mode-driven LED updates."""
        self.preview_active = False
        self._send_json(client, "200 OK", {"success": True})

    def _handle_api_game_start(self, client, request_body):
        if self.game is None:
            self._send_json(client, "503 Service Unavailable", {"success": False, "error": "game unavailable"})
            return
        level = 1
        if request_body:
            try:
                data = json.loads(request_body)
                if isinstance(data, dict) and "level" in data:
                    level = int(data.get("level") or 1)
            except (ValueError, TypeError):
                level = 1
        self.game.start(level)
        self._send_json(client, "200 OK", {"success": True, "level": level})

    def _handle_api_game_stop(self, client):
        if self.game is None:
            self._send_json(client, "503 Service Unavailable", {"success": False, "error": "game unavailable"})
            return
        self.game.stop()
        self._send_json(client, "200 OK", {"success": True})

    def _handle_api_game_shoot(self, client, request_body):
        if self.game is None:
            self._send_json(client, "503 Service Unavailable", {"success": False, "error": "game unavailable"})
            return
        try:
            data = json.loads(request_body)
            color = data.get("color")
            if color not in ("R", "G", "B"):
                self._send_json(client, "400 Bad Request", {"success": False, "error": "invalid color"})
                return
            self.game.shoot(color)
            self._send_json(client, "200 OK", {"success": True})
        except Exception as e:
            self._send_json(client, "400 Bad Request", {"success": False, "error": str(e)})

    def _handle_api_game_upgrade(self, client, request_body):
        """POST /api/game/upgrade {"mix": "Y"|"C"|"M"} — promote the most
        recently launched in-flight ball to the mix color (only if its current
        color is one of the mix's two primaries; never downgrades)."""
        if self.game is None:
            self._send_json(client, "503 Service Unavailable", {"success": False, "error": "game unavailable"})
            return
        try:
            data = json.loads(request_body)
            mix = data.get("mix")
            if mix not in ("Y", "C", "M"):
                self._send_json(client, "400 Bad Request", {"success": False, "error": "invalid mix"})
                return
            self.game.upgrade_last_ball(mix)
            self._send_json(client, "200 OK", {"success": True})
        except Exception as e:
            self._send_json(client, "400 Bad Request", {"success": False, "error": str(e)})

    def _handle_upload(self, client, query, total_body_len, leftover):
        """Stream body to /staging/<path>, hash it, validate, atomically rename."""
        target = _safe_rel_path(query.get("path", ""))
        if not target:
            self._send_json(client, "400 Bad Request", {"success": False, "error": "invalid path"})
            return
        if target in PROTECTED:
            self._send_json(client, "403 Forbidden", {"success": False, "error": "protected path"})
            return
        expected_sha = (query.get("sha256") or "").lower().strip()
        if not expected_sha or len(expected_sha) != 64:
            self._send_json(client, "400 Bad Request", {"success": False, "error": "missing sha256"})
            return
        try:
            expected_size = int(query.get("size", "-1"))
        except ValueError:
            expected_size = -1
        if expected_size < 0 or expected_size != total_body_len:
            self._send_json(client, "400 Bad Request",
                            {"success": False, "error": "size/content-length mismatch",
                             "size": expected_size, "content_length": total_body_len})
            return

        _mkdir_p(STAGING_DIR)
        staged = STAGING_DIR + target
        staged_dir = staged.rsplit("/", 1)[0]
        _mkdir_p(staged_dir)
        part = staged + ".part"
        _remove_file(part)

        h = hashlib.sha256()
        written = 0
        try:
            with open(part, "wb") as f:
                if leftover:
                    f.write(leftover)
                    h.update(leftover)
                    written += len(leftover)
                while written < total_body_len:
                    try:
                        chunk = client.recv(min(UPLOAD_CHUNK, total_body_len - written))
                    except OSError:
                        chunk = b""
                    if not chunk:
                        break
                    f.write(chunk)
                    h.update(chunk)
                    written += len(chunk)
        except OSError as e:
            _remove_file(part)
            self._send_json(client, "500 Internal Server Error",
                            {"success": False, "error": "write failed", "detail": str(e)})
            return

        if written != total_body_len:
            _remove_file(part)
            self._send_json(client, "400 Bad Request",
                            {"success": False, "error": "short upload",
                             "got": written, "expected": total_body_len})
            return

        got_sha = binascii.hexlify(h.digest()).decode("ascii")
        if got_sha != expected_sha:
            _remove_file(part)
            self._send_json(client, "400 Bad Request",
                            {"success": False, "error": "sha256 mismatch",
                             "got": got_sha, "expected": expected_sha})
            return

        _remove_file(staged)
        try:
            os.rename(part, staged)
        except OSError as e:
            _remove_file(part)
            self._send_json(client, "500 Internal Server Error",
                            {"success": False, "error": "rename to staging failed", "detail": str(e)})
            return

        target_dir = target.rsplit("/", 1)[0]
        if target_dir:
            _mkdir_p(target_dir)
        try:
            if _exists(target):
                _remove_file(target)
            os.rename(staged, target)
        except OSError as e:
            self._send_json(client, "500 Internal Server Error",
                            {"success": False, "error": "rename to live failed",
                             "detail": str(e), "staged": staged})
            return

        print(f"upload: wrote {target} ({written} bytes, sha {got_sha[:12]}...)")
        self._send_json(client, "200 OK",
                        {"success": True, "path": target, "size": written, "sha256": got_sha})

    def _handle_files_list(self, client):
        self._send_json(client, "200 OK", {"success": True, "files": _walk_listing()})

    def _handle_files_sha(self, client, query):
        target = _safe_rel_path(query.get("path", ""))
        if not target or not _exists(target):
            self._send_json(client, "404 Not Found", {"success": False, "error": "not found"})
            return
        if target in PROTECTED:
            self._send_json(client, "403 Forbidden", {"success": False, "error": "protected path"})
            return
        sha = _sha256_of_file(target)
        if sha is None:
            self._send_json(client, "500 Internal Server Error",
                            {"success": False, "error": "read failed"})
            return
        self._send_json(client, "200 OK",
                        {"success": True, "path": target,
                         "size": _file_size(target), "sha256": sha})

    def _handle_files_download(self, client, query):
        target = _safe_rel_path(query.get("path", ""))
        if not target or not _exists(target):
            self._send_json(client, "404 Not Found", {"success": False, "error": "not found"})
            return
        if target in PROTECTED:
            self._send_json(client, "403 Forbidden", {"success": False, "error": "protected path"})
            return
        size = _file_size(target)
        if size < 0:
            self._send_json(client, "500 Internal Server Error", {"success": False, "error": "stat failed"})
            return
        filename = target.rsplit("/", 1)[-1]
        try:
            header = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: application/octet-stream\r\n"
                f"Content-Length: {size}\r\n"
                f"Content-Disposition: attachment; filename=\"{filename}\"\r\n"
                "Connection: close\r\n"
                "\r\n"
            )
            client.sendall(header.encode("utf-8"))
            with open(target, "rb") as f:
                while True:
                    chunk = f.read(1024)
                    if not chunk:
                        break
                    client.sendall(chunk)
        except Exception as e:
            print(f"download failed: {e}")

    def _handle_files_delete(self, client, query):
        target = _safe_rel_path(query.get("path", ""))
        if not target:
            self._send_json(client, "400 Bad Request", {"success": False, "error": "invalid path"})
            return
        if target in PROTECTED:
            self._send_json(client, "403 Forbidden", {"success": False, "error": "protected path"})
            return
        if not _exists(target):
            self._send_json(client, "404 Not Found", {"success": False, "error": "not found"})
            return
        try:
            os.remove(target)
        except OSError as e:
            self._send_json(client, "500 Internal Server Error",
                            {"success": False, "error": "remove failed", "detail": str(e)})
            return
        self._send_json(client, "200 OK", {"success": True, "path": target})

    def _handle_reboot(self, client):
        self._send_json(client, "200 OK", {"success": True, "rebooting": True})
        try:
            client.close()
        except Exception:
            pass
        time.sleep(1)
        import machine
        machine.reset()

    def _read_headers(self, client):
        """Read until end-of-headers. Returns (headers_text, leftover_body_bytes)."""
        buf = b""
        while True:
            try:
                chunk = client.recv(1024)
            except OSError:
                return None, None
            if not chunk:
                return None, None
            buf += chunk
            idx = buf.find(b"\r\n\r\n")
            if idx >= 0:
                try:
                    headers = buf[:idx].decode("utf-8")
                except UnicodeError:
                    headers = buf[:idx].decode("latin1")
                return headers, buf[idx+4:]
            if len(buf) > 16384:
                return None, None

    def _content_length(self, headers_text):
        for line in headers_text.split("\r\n"):
            if line.lower().startswith("content-length:"):
                try:
                    return int(line.split(":", 1)[1].strip())
                except ValueError:
                    return 0
        return 0

    def handle_request(self):
        """Handle incoming HTTP requests (non-blocking)"""
        if not self.socket:
            return

        try:
            client, addr = self.socket.accept()
        except OSError:
            return

        try:
            client.settimeout(10.0)

            headers_text, leftover = self._read_headers(client)
            if headers_text is None:
                return

            first_line = headers_text.split("\r\n", 1)[0]
            parts = first_line.split(" ")
            if len(parts) < 2:
                return
            method, raw_path = parts[0], parts[1]
            path, query = _split_path(raw_path)
            cl = self._content_length(headers_text)

            if path.startswith("/api/"):
                print(f"API: {method} {raw_path}")

            # Streaming upload — never buffer the body in RAM.
            if path == UPLOAD_PATH and method == "POST":
                self._handle_upload(client, query, cl, leftover)
                return

            # Buffer remaining body for non-upload requests, with a hard cap.
            body_bytes = leftover or b""
            if cl > MAX_NON_UPLOAD_BODY:
                self._send_json(client, "413 Payload Too Large",
                                {"success": False, "error": "body too large for this endpoint"})
                return
            while len(body_bytes) < cl:
                try:
                    chunk = client.recv(min(1024, cl - len(body_bytes)))
                except OSError:
                    break
                if not chunk:
                    break
                body_bytes += chunk

            try:
                body = body_bytes.decode("utf-8")
            except UnicodeError:
                body = body_bytes.decode("latin1")
            body = body.strip("\x00").strip()

            # Route requests
            if path == '/' or path == '/index.html':
                if self.wifi.is_ap_mode:
                    self._send_static(client, '/web/setup.html', "text/html")
                else:
                    self._send_static(client, '/web/index.html', "text/html")

            elif path == '/test.html':
                self._send_static(client, '/web/test.html', "text/html")

            elif path == '/style.css':
                self._send_static(client, '/web/style.css', "text/css")

            elif path == '/script.js':
                self._send_static(client, '/web/script.js', "application/javascript")

            elif path == '/files' or path == '/files.html':
                self._send_static(client, '/web/files.html', "text/html")

            elif path == '/files.js':
                self._send_static(client, '/web/files.js', "application/javascript")

            elif path == '/options' or path == '/options.html':
                self._send_static(client, '/web/options.html', "text/html")

            elif path == '/options.js':
                self._send_static(client, '/web/options.js', "application/javascript")

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

            elif path == '/api/preview' and method == 'POST':
                self._handle_api_preview(client, body)

            elif path == '/api/preview/stop' and method == 'POST':
                self._handle_api_preview_stop(client)

            elif path == '/game' or path == '/game.html':
                self._send_static(client, '/web/game.html', "text/html")

            elif path == '/game.js':
                self._send_static(client, '/web/game.js', "application/javascript")

            elif path == '/api/game/start' and method == 'POST':
                self._handle_api_game_start(client, body)

            elif path == '/api/game/stop' and method == 'POST':
                self._handle_api_game_stop(client)

            elif path == '/api/game/shoot' and method == 'POST':
                self._handle_api_game_shoot(client, body)

            elif path == '/api/game/upgrade' and method == 'POST':
                self._handle_api_game_upgrade(client, body)

            elif path == '/api/files/list' and method == 'GET':
                self._handle_files_list(client)

            elif path == '/api/files/sha' and method == 'GET':
                self._handle_files_sha(client, query)

            elif path == '/api/files/download' and method == 'GET':
                self._handle_files_download(client, query)

            elif path == '/api/files/delete' and method == 'POST':
                self._handle_files_delete(client, query)

            elif path == '/api/reboot' and method == 'POST':
                self._handle_reboot(client)

            else:
                self._send_response(client, "404 Not Found", "text/plain", "Not found")

        except Exception as e:
            print(f"Error handling request: {e}")
            import sys
            sys.print_exception(e)
        finally:
            try:
                client.close()
            except Exception:
                pass
