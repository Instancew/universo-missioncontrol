
from pathlib import Path
from getpass import getpass
import json
import httpx

ROUTER_IP = "192.168.88.2"

CA_CERT = (
    Path(__file__).resolve().parent
    / "backend"
    / "certificates"
    / "netmetal-rest-ca.crt"
)

if not CA_CERT.is_file():
    raise FileNotFoundError(f"Certificate not found: {CA_CERT}")

username = input("NetMetal username: ")
password = getpass("NetMetal password: ")

BASE_URL = f"https://{ROUTER_IP}/rest"

queries = {
    "System Resource": (
        "system/resource",
        "board-name,version,uptime,cpu-load,free-memory,total-memory"
    ),
    "Wireless Registration": (
        "interface/wifi/registration-table",
        "interface,ssid,mac-address,authorized,signal,"
        "tx-rate,rx-rate,uptime,last-activity,"
        "tx-bits-per-second,rx-bits-per-second"
    )
}

try:
    with httpx.Client(
        auth=(username, password),
        verify=str(CA_CERT),
        timeout=10
    ) as client:

        for title, (endpoint, fields) in queries.items():
            print(f"\n{'=' * 50}\n{title}\n{'=' * 50}")

            response = client.get(
                f"{BASE_URL}/{endpoint}",
                params={".proplist": fields}
            )
            response.raise_for_status()

            print(json.dumps(response.json(), indent=4))

    print("\nNETMETAL RADIO DATA TEST COMPLETED!")

except httpx.HTTPStatusError as error:
    print("HTTP error:", error.response.status_code)
    print(error.response.text)

except httpx.TransportError as error:
    print("Connection/TLS error:", error)

