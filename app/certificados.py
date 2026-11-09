"""Contexto SSL que funciona también con el Python de python.org en Mac.

Ese Python no trae certificados raíz hasta que se ejecuta "Install Certificates.command".
Si no hay certificados, se cargan los del llavero del sistema de macOS.
"""
import ssl
import subprocess
import sys


def contexto_ssl() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if sys.platform == "darwin" and ctx.cert_store_stats().get("x509_ca", 0) == 0:
        try:
            pem = subprocess.run(
                ["/usr/bin/security", "find-certificate", "-a", "-p",
                 "/System/Library/Keychains/SystemRootCertificates.keychain"],
                capture_output=True, text=True, timeout=20,
            ).stdout
            if pem:
                ctx.load_verify_locations(cadata=pem)
        except Exception:
            pass
    return ctx
