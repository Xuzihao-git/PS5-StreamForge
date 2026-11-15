"""Small netifaces compatibility surface used by pyremoteplay's IPv4 discovery.

Uses psutil's supported Windows adapter API; no netifaces C extension required.
"""
import ipaddress
import socket
import psutil

AF_INET = socket.AF_INET
AF_INET6 = socket.AF_INET6


def interfaces():
    return list(psutil.net_if_addrs())


def ifaddresses(name):
    result = {}
    for item in psutil.net_if_addrs().get(name, []):
        data = {"addr": item.address, "netmask": item.netmask}
        if item.family == AF_INET and item.netmask:
            data["broadcast"] = str(ipaddress.IPv4Network(
                f"{item.address}/{item.netmask}", strict=False).broadcast_address)
        result.setdefault(item.family, []).append(data)
    return result
