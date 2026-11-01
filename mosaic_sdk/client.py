"""Small dependency-free client for the MOSAIC application API."""
import base64
import json
import os
import urllib.error
import urllib.request


class MosaicError(RuntimeError):
    pass


class MosaicClient:
    def __init__(self, base_url=None, token=None, org_id=None, username=None, password=None):
        self.base_url = (base_url or os.getenv("MOSAIC_URL", "http://localhost:8000")).rstrip("/")
        self.token = token or os.getenv("MOSAIC_TOKEN")
        self.org_id = org_id or os.getenv("MOSAIC_ORG_ID")
        self.username = username or os.getenv("MOSAIC_USERNAME")
        self.password = password or os.getenv("MOSAIC_PASSWORD")

    def request(self, method, path, body=None):
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        elif self.username is not None and self.password is not None:
            raw = (self.username + ":" + self.password).encode()
            headers["Authorization"] = "Basic " + base64.b64encode(raw).decode()
        if self.org_id:
            headers["X-Organisation-ID"] = self.org_id
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = response.read()
                return json.loads(payload) if payload else None
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(detail).get("detail", detail)
            except (ValueError, AttributeError):
                pass
            raise MosaicError(f"{exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise MosaicError(f"Could not reach MOSAIC at {self.base_url}: {exc.reason}") from exc

    def get_app(self, app_id):
        apps = self.request("GET", "/api/v1/apps")
        try:
            return next(app for app in apps if app["id"] == app_id)
        except StopIteration as exc:
            raise MosaicError(f"Application {app_id} was not found in this organisation") from exc

    def save_manifest(self, app_id, manifest, expected_version):
        return self.request("PUT", f"/api/v1/apps/{app_id}", {
            "config": manifest, "expected_version": expected_version
        })

    def release(self, app_id, environment):
        return self.request("POST", f"/api/v1/apps/{app_id}/releases", {"environment": environment})

    def releases(self, app_id):
        return self.request("GET", f"/api/v1/apps/{app_id}/releases")
