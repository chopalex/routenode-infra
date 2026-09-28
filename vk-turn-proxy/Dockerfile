FROM alpine:3.20
ARG VK_TURN_VERSION=v1.8.3
ARG VK_TURN_URL=https://github.com/cacggghp/vk-turn-proxy/releases/download/${VK_TURN_VERSION}/server-linux-amd64
RUN apk add --no-cache ca-certificates curl \
 && curl -fsSL -o /usr/local/bin/vk-turn-proxy "$VK_TURN_URL" \
 && chmod +x /usr/local/bin/vk-turn-proxy \
 && apk del curl
ENTRYPOINT ["/usr/local/bin/vk-turn-proxy"]
CMD ["-listen", "0.0.0.0:56000", "-connect", "127.0.0.1:47054"]
