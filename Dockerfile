# Build is divided into two stages "build" and "runtime"

FROM python:3.9 AS build
WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt
RUN pip install pyinstaller

COPY . .
CMD [ "pyinstaller", "--onefile", "nftables_exporter.py" ]

FROM alpine:latest
#RUN apk --no-cache add bash curl procps psmisc socat
### Empty (size = app)
#FROM scratch
WORKDIR /app
# Copy build directory as-is, it is prepared in the Makefile
COPY --from=buildstage /app/dist/nftables_exporter ./
EXPOSE 9630
ENTRYPOINT ["/app/nftables_exporter"]
