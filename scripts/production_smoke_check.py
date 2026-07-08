from __future__ import annotations

import argparse

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="Check production HTTP surfaces for VRChat Avatar Watch.")
    parser.add_argument("base_url", help="Example: https://vrc-aw.choko1229.net")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    paths = ["/api/health", "/", "/avatars", "/search", "/sales", "/free", "/tools"]
    with httpx.Client(timeout=20, follow_redirects=False) as client:
        for path in paths:
            response = client.get(f"{base_url}{path}")
            print(f"{path} status={response.status_code} bytes={len(response.content)}")
            if response.status_code >= 500:
                raise SystemExit(1)


if __name__ == "__main__":
    main()
