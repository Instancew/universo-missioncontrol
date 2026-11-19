
from pathlib import Path
from getpass import getpass
import httpx

# NetMetal configuration
ROUTER_IP = "192.168.88.2"
URL = f"https://{ROUTER_IP}/rest/system/resource"

# NetMetal CA certificate
CA_CERTIFICATE = (
    Path(__file__).resolve().parent
    / "backend"
    / "certificates"
    / "netmetal-rest-ca.crt"
)

if not CA_CERTIFICATE.is_file():
    raise FileNotFoundError(
        f"NetMetal CA certificate not found: {CA_CERTIFICATE}"
    )

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

        print("\nNETMETAL HTTPS CONNECTION SUCCESSFUL!")
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
