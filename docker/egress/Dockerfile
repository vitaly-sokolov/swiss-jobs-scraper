# Forwarding proxy for Selenium (§5.1): Chrome cannot send proxy credentials, so
# it talks to this container without auth and tinyproxy adds the upstream login.
FROM alpine:3.20
RUN apk add --no-cache tinyproxy
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
EXPOSE 3128
ENTRYPOINT ["/entrypoint.sh"]
