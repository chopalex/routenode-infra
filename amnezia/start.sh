#!/bin/bash

# This scripts copied from Amnezia client to Docker container to /opt/amnezia and launched every time container starts

echo "Container startup"
#ifconfig eth0:0 31.77.72.242 netmask 255.255.255.255 up

PIHOLE_DNS=172.29.172.10

# kill daemons in case of restart
awg-quick down /opt/amnezia/awg/awg0.conf

# start daemons if configured
if [ -f /opt/amnezia/awg/awg0.conf ]; then (awg-quick up /opt/amnezia/awg/awg0.conf); fi

# Allow traffic on the TUN interface.
iptables -A INPUT -i awg0 -j ACCEPT
iptables -A FORWARD -i awg0 -j ACCEPT
iptables -A OUTPUT -o awg0 -j ACCEPT

# Allow forwarding traffic only from the VPN.
iptables -A FORWARD -i awg0 -o eth0 -s 10.8.1.0/24 -j ACCEPT
iptables -A FORWARD -i awg0 -o eth1 -s 10.8.1.0/24 -j ACCEPT
# Allow replies / Pi-hole → VPN peers (no SNAT path)
iptables -A FORWARD -i eth0 -o awg0 -d 10.8.1.0/24 -j ACCEPT

iptables -A FORWARD -m state --state ESTABLISHED,RELATED -j ACCEPT

# Transparent DNS hijack: Amnezia DNS / 1.1.1.1 / 8.8.8.8 → Pi-hole
# Client keeps whatever DNS is set in the app; replies come back via conntrack.
iptables -t nat -A PREROUTING -i awg0 -s 10.8.1.0/24 -p udp --dport 53 ! -d ${PIHOLE_DNS} -j DNAT --to-destination ${PIHOLE_DNS}:53
iptables -t nat -A PREROUTING -i awg0 -s 10.8.1.0/24 -p tcp --dport 53 ! -d ${PIHOLE_DNS} -j DNAT --to-destination ${PIHOLE_DNS}:53

# Block DNS-over-TLS bypass
iptables -A FORWARD -i awg0 -p tcp --dport 853 -j REJECT --reject-with tcp-reset
iptables -A FORWARD -i awg0 -p udp --dport 853 -j REJECT

# Keep peer source IPs when talking to amnezia-dns-net (Pi-hole).
# Without this, MASQUERADE makes every query look like one host in Pi-hole.
iptables -t nat -A POSTROUTING -s 10.8.1.0/24 -d 172.29.172.0/24 -j RETURN
iptables -t nat -A POSTROUTING -s 10.8.1.0/24 -o eth0 -j MASQUERADE
iptables -t nat -A POSTROUTING -s 10.8.1.0/24 -o eth1 -j MASQUERADE


# MTU/MSS fix for vk-turn + AWG (web browsers)
iptables -t mangle -A FORWARD -i awg0 -p tcp -m tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1280
iptables -t mangle -A FORWARD -o awg0 -p tcp -m tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1280

tail -f /dev/null
