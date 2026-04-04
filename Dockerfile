FROM python:3.11.8-slim-bookworm
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Europe/Prague
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies (SNMP only, no VPN)
RUN apt-get update && apt-get install -y \
    snmp \
    snmpd \
    libsnmp-dev \
    iproute2 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Configure SNMP
RUN mkdir -p /opt/mibs /root/.snmp/mibs && \
    echo "mibdirs /opt/mibs/cisco:/opt/mibs/standard:/usr/share/snmp/mibs" > /etc/snmp/snmp.conf && \
    echo "mibs +ALL" >> /etc/snmp/snmp.conf

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY entrypoint.sh .
COPY init_db.py .
COPY detail_ports.py .
COPY arp.py .
COPY snmp_helper.py .
COPY snmp_detail.py .
COPY templates/ ./templates/
COPY static/ ./static/

RUN mkdir -p /app/data /app/config /app/templates /app/static /app/languages

RUN chmod +x /app/entrypoint.sh

EXPOSE 4999

ENTRYPOINT ["/app/entrypoint.sh"]
