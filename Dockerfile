FROM python:3.9.13-alpine
RUN apk add nftables
#FROM python:3.9-slim-bullseye
#RUN apt-get update ; apt-get install -y nftables

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY nftables-exporter.py .

EXPOSE 9630

ENTRYPOINT ["/app/nftables-exporter.py"]
