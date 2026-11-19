
from pathlib import Path
from getpass import getpass
import json
import httpx

ROUTER_IP = "192.168.88.1"
BASE_URL = f"https://{ROUTER_IP}/rest"

CA_CERTIFICATE = (
    Path(__file__).resolve().parent
    / "backend"
    / "certificates"
    / "rest-ca.crt"
)

username = input("Router username: ")
password = getpass("Router password: ")

requests_to_make = {
    "SYSTEM RESOURCE": (
        "system/resource",
        "board-name,version,uptime,cpu-load,free-memory,total-memory"
    ),
    "WIFI REGISTRATION TABLE": (
        "interface/wifi/registration-table",
        "interface,ssid,mac-address,authorized,signal,"
        "tx-rate,rx-rate,uptime,last-activity,"
        "tx-bits-per-second,rx-bits-per-second"
    )
}

try:
    with httpx.Client(
        auth=(username, password),
        verify=str(CA_CERTIFICATE),
        timeout=10
    ) as client:

        for title, (endpoint, fields) in requests_to_make.items():

            print("\n" + "=" * 55)
            print(title)
            print("=" * 55)

            response = client.get(
                f"{BASE_URL}/{endpoint}",
                params={".proplist": fields}
            )

            response.raise_for_status()

            data = response.json()

            if isinstance(data, list) and not data:
                print("No records returned.")
            else:
                print(json.dumps(data, indent=4))

    print("\nAll requests completed successfully!")

except httpx.HTTPStatusError as error:
    print("HTTP error:", error.response.status_code)
    print(error.response.text)

except httpx.TransportError as error:
    print("Connection/TLS error:", error)

except FileNotFoundError as error:
    print(error)
