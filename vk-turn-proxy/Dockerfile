FROM alpine:3.20
COPY server-linux-amd64 /usr/local/bin/vk-turn-proxy
RUN chmod +x /usr/local/bin/vk-turn-proxy
ENTRYPOINT ["/usr/local/bin/vk-turn-proxy"]
CMD ["-listen", "0.0.0.0:56000", "-connect", "127.0.0.1:47054"]
