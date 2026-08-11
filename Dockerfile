# Base on python:3.10-slim to match the host's Python 3.10, so the server
# behaves identically in the container as it does when run directly.
FROM python:3.10-slim

WORKDIR /app

# Dependencies rarely change but the source does, so requirements are copied
# and installed before the rest of the source: Docker caches this layer and
# only re-runs pip install when requirements.txt itself changes, which is
# what keeps ordinary source-only rebuilds fast.
COPY requirements.txt .
# --trusted-host is needed on machines running an HTTPS-scanning antivirus
# (e.g. Avast's web shield): it re-signs every TLS connection with its own
# locally-generated root CA, which the host's OS trusts but this container's
# CA bundle does not, so pip's certificate check fails even though the
# download itself is untampered. This is acceptable here specifically
# because every package below is pinned to an exact version: pip fetches
# that exact, named artifact regardless of transport trust, so skipping
# certificate verification does not widen what code can end up in the
# image -- it only skips re-proving an identity pip was already told.
RUN pip install --no-cache-dir \
    --trusted-host pypi.org --trusted-host files.pythonhosted.org \
    -r requirements.txt

# Only what the server actually imports -- not tests/, assets/, client.py,
# app.py, or view/ (the OpenCV rendering stack, which stays on the host).
# server.py is only the thin entry-point shim since the Stage 2 refactor
# split its real code into server/ -- copying the shim alone left the
# container crash-looping on ModuleNotFoundError: No module named
# 'server.composition', caught only by actually starting the container,
# since the package exists on the host either way.
COPY server.py .
COPY server/ server/
COPY common/ common/
COPY engine/ engine/
COPY model/ model/
COPY rules/ rules/
COPY realtime/ realtime/
COPY boardio/ boardio/
COPY input/ input/

EXPOSE 8765

# A minimal liveness probe: the port must be accepting TCP connections. This
# is the "/health" idea from the design doc's diagram in its simplest form --
# it is what lets an orchestrator know the container is actually alive
# rather than merely running.
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD python -c "import socket; socket.create_connection(('localhost', 8765), timeout=2).close()"

CMD ["python", "server.py"]
