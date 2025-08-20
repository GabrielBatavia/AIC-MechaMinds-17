import requests
from typing import Optional, Dict, Any

class MedVerifyClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}

    def verify(self, *, session_id: Optional[str], nie: Optional[str]=None, text: Optional[str]=None, timeout:int=30) -> Dict[str,Any]:
        h = dict(self.headers)
        if session_id: h["X-Session-Id"] = session_id
        payload = {}
        if nie: payload["nie"] = nie
        if text: payload["text"] = text
        r = requests.post(f"{self.base_url}/v1/verify", json=payload, headers=h, timeout=timeout)
        r.raise_for_status(); return r.json()

    def scan_photo(self, *, session_id: Optional[str], filepath: str, return_partial: bool=True, timeout:int=60) -> Dict[str,Any]:
        h = {"X-Api-Key": self.headers["X-Api-Key"]}
        if session_id: h["X-Session-Id"] = session_id
        files = {"img": (filepath, open(filepath, "rb"), "image/jpeg")}
        data = {"return_partial": "true" if return_partial else "false"}
        r = requests.post(f"{self.base_url}/v1/scan/photo", headers=h, files=files, data=data, timeout=timeout)
        r.raise_for_status(); return r.json()

    def verify_photo(self, *, session_id: Optional[str], filepath: str, nie: Optional[str]=None, text: Optional[str]=None, timeout:int=60) -> Dict[str,Any]:
        h = {"X-Api-Key": self.headers["X-Api-Key"]}
        if session_id: h["X-Session-Id"] = session_id
        files = {"img": (filepath, open(filepath, "rb"), "image/jpeg")}
        data = {}
        if nie: data["nie"] = nie
        if text: data["text"] = text
        r = requests.post(f"{self.base_url}/v1/verify-photo", headers=h, files=files, data=data, timeout=timeout)
        r.raise_for_status(); return r.json()

    def agent(self, *, session_id: str, text: str, timeout:int=60) -> Dict[str,Any]:
        payload = {"session_id": session_id, "text": text}
        r = requests.post(f"{self.base_url}/v1/agent", json=payload, headers=self.headers, timeout=timeout)
        r.raise_for_status(); return r.json()
