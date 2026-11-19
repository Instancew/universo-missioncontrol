
from pathlib import Path
from getpass import getpass
import httpx

# mANTBox configuration
ROUTER_IP = "192.168.88.1"
URL = f"https://{ROUTER_IP}/rest/system/resource"

# Locate the CA certificate
CA_CERTIFICATE = (
    Path(__file__).resolve().parent
    / "backend"
    / "certificates"
    / "rest-ca.crt"
)

if not CA_CERTIFICATE.is_file():
    raise FileNotFoundError(
        f"CA certificate not found: {CA_CERTIFICATE}"
    )

# Ask for credentials without saving the password in this file
username = input("Router username: ")
password = getpass("Router password: ")

try:
    with httpx.Client(
        auth=(username, password),
        verify=str(CA_CERTIFICATE),
        timeout=10
    ) as client:

        response = client.get(URL)
        response.raise_for_status()

        print("\nHTTPS CONNECTION SUCCESSFUL!")
        print("\nRouter information:")
        print(response.json())

except httpx.HTTPStatusError as error:
    print("\nHTTP error:", error.response.status_code)
    print(error.response.text)

except httpx.ConnectError as error:
    print("\nConnection/TLS error:", error)

except httpx.TimeoutException:
    print("\nConnection timed out.")

except httpx.TransportError as error:
    print("\nHTTPS transport error:", error)
