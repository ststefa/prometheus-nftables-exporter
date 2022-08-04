## alpine does not work for linux/arm/v7, linux/arm64: "uname -rs" fails on pyinstaller setup
FROM python:3.9.13-alpine
RUN apk add nftables
#FROM python:3.9-slim-bullseye

WORKDIR /app

COPY requirements.txt ./
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

COPY nftables_exporter.py .

EXPOSE 9630

ENTRYPOINT ["/app/nftables_exporter.py"]
